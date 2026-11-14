"""Availability of the STEP entity graph (Part 21 instances stored as rows: step_entities/edges).

The parser/storage that fills those tables (``step_graph_storage``) lives in CAPP, where it was written
to show that STEP exchange files can be stored relationally and recovered; it was never ported here.
CAE Viewer's simulation path does not need it (CAD faces come from ``app/geometry`` via pythonOCC), so
the panels that read the tables (entity tree, features, PMI, analysis) report "not available" instead
of returning empty results that look valid.
"""
from flask import jsonify

ENTITY_GRAPH_AVAILABLE = False

UNAVAILABLE_MESSAGE = ('El análisis de entidades STEP (árbol de entidades, features, PMI y calidad) no está '
                       'disponible en CAE Viewer. El visor 3D, la medición y el corte sí funcionan.')


def unavailable_response():
    return jsonify({'error': UNAVAILABLE_MESSAGE, 'kind': 'entity_graph_unavailable'}), 501


def guard_blueprint(bp):
    """Answer every route of ``bp`` with 501 while the entity graph is not available."""
    @bp.before_request
    def _entity_graph_guard():
        if not ENTITY_GRAPH_AVAILABLE:
            return unavailable_response()
    return bp
