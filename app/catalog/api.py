"""/api/catalog — Hub tool catalog (data-driven cards + filter facets)."""
from flask import Blueprint, jsonify, request

from app.catalog.models import SolverCatalog, CATEGORIES, INTEGRATION_LEVELS, AVAILABILITY
from app.catalog.seed_data import VOCABULARY

bp = Blueprint('catalog', __name__)


def _has(entry: SolverCatalog, key: str, value: str) -> bool:
    return value in ((entry.capabilities or {}).get(key) or [])


@bp.route('', methods=['GET'])
def list_catalog():
    """Filters (all optional, comma-separated = OR within a filter, AND across filters):
    category, level (integration_level), availability, analysis, method, deployment."""
    rows = (SolverCatalog.query.filter_by(enabled=True)
            .order_by(SolverCatalog.sort_order, SolverCatalog.name).all())

    def csv(name):
        v = request.args.get(name)
        return set(v.split(',')) if v else None

    flt = {k: csv(k) for k in ('category', 'level', 'availability', 'analysis', 'method', 'deployment')}
    out = []
    for r in rows:
        if flt['category'] and r.category not in flt['category']:
            continue
        if flt['level'] and r.integration_level not in flt['level']:
            continue
        if flt['availability'] and r.availability not in flt['availability']:
            continue
        if any(flt[k] and not any(_has(r, k, v) for v in flt[k]) for k in ('analysis', 'method', 'deployment')):
            continue
        out.append(r.to_dict())
    return jsonify({'tools': out, 'total': len(rows)})


@bp.route('/facets', methods=['GET'])
def facets():
    """Filter values with counts, so the Hub only shows filters that match something."""
    rows = SolverCatalog.query.filter_by(enabled=True).all()
    counts = {k: {v: 0 for v in vals} for k, vals in VOCABULARY.items()}
    for r in rows:
        for k in counts:
            for v in (r.capabilities or {}).get(k) or []:
                counts[k][v] = counts[k].get(v, 0) + 1
    count_by = lambda attr, values: {v: sum(1 for r in rows if getattr(r, attr) == v) for v in values}  # noqa: E731
    return jsonify({
        'category': count_by('category', CATEGORIES),
        'level': count_by('integration_level', INTEGRATION_LEVELS),
        'availability': count_by('availability', AVAILABILITY),
        **counts,
    })


@bp.route('/<string:slug>', methods=['GET'])
def get_tool(slug):
    r = SolverCatalog.query.filter_by(slug=slug, enabled=True).first()
    if r is None:
        return jsonify({'error': 'Herramienta no encontrada'}), 404
    return jsonify(r.to_dict())
