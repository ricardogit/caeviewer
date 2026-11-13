"""REST API for jobs — /api/jobs"""
from flask import Blueprint, jsonify, request

from app.extensions import db
from app.jobs.models import Job, JOB_STATUSES, TERMINAL_STATUSES
from app.jobs import queue as q
from app.jobs.handlers import registered_kinds

bp = Blueprint('jobs', __name__)


@bp.route('', methods=['GET'])
def list_jobs():
    limit = min(int(request.args.get('limit', 50)), 500)
    query = Job.query
    if request.args.get('include_completed', 'true').lower() == 'false':
        query = query.filter(Job.status.notin_(TERMINAL_STATUSES))
    if status := request.args.get('status'):
        query = query.filter(Job.status.in_(status.split(',')))
    if kind := request.args.get('kind'):
        query = query.filter(Job.kind == kind)
    if run_id := request.args.get('simulation_run_id'):
        query = query.filter(Job.simulation_run_id == run_id)
    jobs = query.order_by(Job.created_at.desc()).limit(limit).all()
    return jsonify({'jobs': [j.to_dict() for j in jobs]})


@bp.route('', methods=['POST'])
def create_job():
    """Only kinds marked api_enqueueable (e.g. 'dummy'); real work is enqueued by domain routes."""
    body = request.get_json(silent=True) or {}
    kind = body.get('kind', 'dummy')
    spec = registered_kinds().get(kind)
    if spec is None or not spec.api_enqueueable:
        return jsonify({'error': f"Job kind '{kind}' cannot be created via this endpoint"}), 400
    job = q.enqueue(kind, body.get('payload') or {}, priority=int(body.get('priority', 0)))
    return jsonify(job.to_dict()), 202


@bp.route('/<uuid:job_id>', methods=['GET'])
def get_job(job_id):
    job = db.session.get(Job, job_id)
    if job is None:
        return jsonify({'error': 'Job not found'}), 404
    d = job.to_dict()
    if request.args.get('payload') in ('1', 'true'):
        d['payload'] = job.payload
    return jsonify(d)


@bp.route('/<uuid:job_id>/log', methods=['GET'])
def get_job_log(job_id):
    job = db.session.get(Job, job_id)
    if job is None:
        return jsonify({'error': 'Job not found'}), 404
    tail = min(int(request.args.get('tail', 200)), 5000)
    lines = []
    if job.log_uri:
        try:
            with open(job.log_uri, encoding='utf-8', errors='replace') as f:
                lines = f.readlines()[-tail:]
        except OSError:
            pass   # worker may run on another host/volume
    return jsonify({'job_id': str(job.id), 'lines': [l.rstrip('\n') for l in lines]})


@bp.route('/<uuid:job_id>/cancel', methods=['POST'])
def cancel_job(job_id):
    job = q.request_cancel(job_id)
    if job is None:
        return jsonify({'error': 'Job not found'}), 404
    return jsonify(job.to_dict())


@bp.route('/stats', methods=['GET'])
def stats():
    """Counts per status/queue + live workers (heartbeat in the last 60 s)."""
    rows = db.session.execute(db.text(
        "SELECT queue, status, count(*) FROM jobs GROUP BY queue, status")).all()
    workers = db.session.execute(db.text(
        "SELECT DISTINCT worker_id FROM jobs WHERE status = 'running' "
        "AND heartbeat_at > timezone('utc', now()) - interval '60 seconds'")).scalars().all()
    out = {}
    for queue, status, n in rows:
        out.setdefault(queue, {s: 0 for s in JOB_STATUSES})[status] = n
    return jsonify({'queues': out, 'busy_workers': workers})
