"""Simulation ↔ experiment correlation and confidence (FASE 8).

Metrics of a comparison (measured m vs simulated s at the same points):
  R²            1 − Σ(m − s)² / Σ(m − m̄)²   (identity line, not a regression: a model that is off by
                a constant factor is penalized). With a single point or constant m, R² is
                computed against zero (1 − Σ(m − s)² / Σm²).
  max_rel_error max |s − m| / max(|m|, 5 % of max|m|)   (floor keeps near-zero readings from exploding)
  slope         k = Σ s·m / Σ s²  (least squares m ≈ k s): k > 1 → the model is too stiff
Confidence factor ∈ [0, 1]:
  c = max(R², 0) · exp(−max_rel_error / 0.25) · (1 − exp(−n / 3))
  — perfect agreement with many points → 1; a 25 % worst error divides by e; one point is worth ~0.28.

``SimulationCorrelator`` (plan 8.2): before simulating, finds past correlated runs similar to
the study (same CAD geometry, material, element type, load types, size) and turns their
correlation history into a confidence factor; ``recommend_validation_test`` proposes the next
test (material tensile test and/or sensors at the most informative points of the latest run).
"""
from __future__ import annotations

import math

import numpy as np


def correlation_metrics(measured, simulated) -> dict:
    m = np.asarray(measured, float)
    s = np.asarray(simulated, float)
    n = len(m)
    res = m - s
    ssr = float(res @ res)
    sst = float(((m - m.mean()) ** 2).sum())
    # R² about the mean is only meaningful when the readings spread: with < 3 sensors or nearly equal
    # readings (CV < 10 %) a uniform 5 % offset would give R² ≪ 0 → use R² about zero instead
    if n >= 3 and sst > 0.01 * max(float(m @ m), 1e-300):
        r2 = 1 - ssr / sst
        r2_kind = 'identidad'
    else:
        r2 = 1 - ssr / max(float(m @ m), 1e-300)
        r2_kind = 'respecto a cero'
    floor = 0.05 * float(np.max(np.abs(m))) if n else 0.0
    rel = np.abs(res) / np.maximum(np.abs(m), max(floor, 1e-300))
    k = float(s @ m / (s @ s)) if float(s @ s) > 0 else float('nan')
    out = {'n': n, 'r2': float(r2), 'r2_kind': r2_kind, 'rmse': math.sqrt(ssr / n) if n else float('nan'),
           'max_rel_error': float(rel.max()) if n else float('nan'), 'mean_rel_error': float(rel.mean()) if n else float('nan'),
           'slope': k, 'relative_errors': rel.tolist()}
    out['confidence_factor'] = confidence_factor(out['r2'], out['max_rel_error'], n)
    return out


def group_scales(measured, groups) -> np.ndarray:
    """Per-sensor scale = max |measured| of its quantity group, so that mm and µε can be pooled
    in one fit / one metric (each group then weighs by its relative errors, not by its units)."""
    m = np.abs(np.asarray(measured, float))
    if groups is None:
        return np.full(len(m), max(float(m.max()) if len(m) else 1.0, 1e-300))
    g = np.asarray(groups)
    out = np.empty(len(m))
    for q in set(g.tolist()):
        idx = g == q
        out[idx] = max(float(m[idx].max()), 1e-300)
    return out


def confidence_factor(r2: float, max_rel_error: float, n: int) -> float:
    if not n or not np.isfinite(r2) or not np.isfinite(max_rel_error):
        return 0.0
    return float(max(r2, 0.0) * math.exp(-max_rel_error / 0.25) * (1 - math.exp(-n / 3)))


# ── similarity / confidence before simulating ─────────────────────────────────

def study_signature(spec: dict, material_id: str | None = None, n_dof: int | None = None) -> dict:
    """Features of a study used for similarity (from a solver spec / SimulationRun.inputs)."""
    mat = spec.get('material') or {}
    geo = spec.get('geometry') if isinstance(spec.get('geometry'), dict) else None
    loads = sorted({k for ld in spec.get('loads') or [] for k in ('force', 'pressure', 'gravity', 'force_per_node')
                    if k in ld})
    mp = spec.get('mesh_params') or {}
    if geo:                                   # canonical inputs: CAD identity = STEP sha256
        ident = geo.get('step_sha256') or geo.get('geometry_id')
    elif spec.get('geometry_id'):
        ident = str(spec['geometry_id'])
    elif isinstance(spec.get('cae_mesh'), dict):
        ident = spec['cae_mesh'].get('mesh_file_sha256') or spec['cae_mesh'].get('mesh_id')
    elif spec.get('inline_mesh_sha256'):
        ident = spec['inline_mesh_sha256']
    else:                                     # parametric meshes: their parameters are the identity
        import json
        ident = json.dumps([spec.get('mesh_source'), spec.get('mesh_params')], sort_keys=True, default=str)
    return {
        'geometry': ident,
        'mesh_source': spec.get('mesh_source'),
        'E': float(mat.get('E', 210e9)), 'nu': float(mat.get('nu', 0.3)),
        'material_id': material_id,
        'order': int(mp.get('order', spec.get('element_order', 1)) or 1),
        'loads': loads, 'n_bcs': len(spec.get('bcs') or []), 'n_dof': n_dof,
    }


def similarity(a: dict, b: dict) -> float:
    """Weighted similarity in [0, 1] of two study signatures."""
    w, score = 0.0, 0.0

    def add(weight, value):
        nonlocal w, score
        w += weight
        score += weight * value

    same_geo = a.get('geometry') and a.get('geometry') == b.get('geometry')
    add(0.35, 1.0 if same_geo else (0.3 if a.get('mesh_source') == b.get('mesh_source') else 0.0))
    if a.get('material_id') and b.get('material_id'):
        add(0.25, 1.0 if a['material_id'] == b['material_id'] else 0.0)
    else:
        add(0.25, math.exp(-abs(math.log(a['E'] / b['E'])) / 0.05) * math.exp(-abs(a['nu'] - b['nu']) / 0.02))
    add(0.1, 1.0 if a.get('order') == b.get('order') else 0.5)
    la, lb = set(a.get('loads') or []), set(b.get('loads') or [])
    add(0.2, len(la & lb) / len(la | lb) if la | lb else 1.0)
    if a.get('n_dof') and b.get('n_dof'):
        add(0.1, math.exp(-abs(math.log(a['n_dof'] / b['n_dof']))))
    return score / w if w else 0.0


class SimulationCorrelator:
    """Confidence before simulating from the correlation history (plan 8.2)."""

    def history(self):
        """[(signature, correlation dict)] of every structural correlation with its run inputs."""
        from app.design.models.validation import SimExperimentCorrelation
        from app.design.models.simulation import SimulationRun
        rows = (SimExperimentCorrelation.query.filter(SimExperimentCorrelation.kind == 'structural',
                                                      SimExperimentCorrelation.run_id.isnot(None))
                .order_by(SimExperimentCorrelation.created_at.desc()).limit(500).all())
        out, seen = [], set()
        for c in rows:                      # newest first: one piece of evidence per (experiment, run)
            if (c.experiment_id, c.run_id) in seen:
                continue
            seen.add((c.experiment_id, c.run_id))
            run = c.run or None
            if run is None:
                continue
            spec = run.inputs or run.solver_config or {}
            out.append((study_signature(spec, str(c.material_id) if c.material_id else None,
                                        (run.mesh_stats or {}).get('n_dof')),
                        {'correlation_id': str(c.id), 'run_id': str(c.run_id), 'graph_id': str(run.graph_id),
                         'experiment_id': str(c.experiment_id), 'r2': c.correlation_r2,
                         'max_relative_error': c.max_relative_error, 'confidence_factor': c.confidence_factor or 0.0,
                         'recalibrated': bool(c.recalibration_delta),
                         'created_at': c.created_at.isoformat() if c.created_at else None}))
        return out

    def find_similar_runs(self, graph_id: str, top_k: int = 5, signature: dict | None = None) -> list[dict]:
        sig = signature or self._graph_signature(graph_id)
        scored = []
        for s, c in self.history():
            sim = similarity(sig, s)
            if sim > 0.2:
                scored.append({**c, 'similarity': round(sim, 3), 'same_graph': c['graph_id'] == str(graph_id)})
        scored.sort(key=lambda x: -x['similarity'])          # stable: newest first among ties
        return scored[:top_k]

    @staticmethod
    def compute_confidence_factor(similar_runs: list[dict]) -> float:
        """Similarity-weighted mean of the historical confidence, shrunk toward 0 by the evidence:
        C = (Σ sᵢcᵢ / Σ sᵢ) · (1 − e^(−Σ sᵢ)). No history → 0; one identical perfect case → 0.63."""
        if not similar_runs:
            return 0.0
        s = np.array([r['similarity'] for r in similar_runs])
        c = np.array([r['confidence_factor'] or 0.0 for r in similar_runs])
        return float((s @ c) / s.sum() * (1 - math.exp(-s.sum())))

    def _graph_signature(self, graph_id):
        from app.design.services.graph_to_solver_spec import graph_to_solver_spec
        from app.design.services.traceability.hasher import canonical_inputs
        spec = graph_to_solver_spec(graph_id)
        try:
            spec = canonical_inputs(spec)
        except Exception:
            pass
        return study_signature(spec, self._material_id(graph_id))

    @staticmethod
    def _material_id(graph_id):
        from app.design.models.graph import DesignNode
        n = (DesignNode.query.filter_by(graph_id=graph_id, node_type='MATERIAL')
             .order_by(DesignNode.created_at, DesignNode.id).first())
        return (n.properties or {}).get('material_id') if n else None

    def recommend_validation_test(self, graph_id: str, n_sensors: int = 3) -> dict:
        """Next most useful test: tensile test if the material is uncalibrated, then sensors at the
        points of largest displacement (LVDT, along the dominant component) and largest von Mises
        (strain gauge along the principal direction) of the latest finished run."""
        from app.design.models.material import MaterialModel
        from app.design.models.validation import ExperimentalRecord
        recs = []
        mid = self._material_id(graph_id)
        mat = None
        if mid:
            try:
                import uuid
                from app.extensions import db
                mat = db.session.get(MaterialModel, uuid.UUID(str(mid)))
            except (ValueError, TypeError):
                mat = None
        has_tensile = mid and ExperimentalRecord.query.filter_by(material_id=mid, test_type='tensile').count() > 0
        if not mat or not ((mat.calibration or {}).get('best_model') or has_tensile):
            recs.append({'test_type': 'tensile', 'priority': 1,
                         'title': 'Ensayo de tracción del material',
                         'reason': ('El material del estudio no está calibrado con ensayos: E y σy vienen de una tabla. '
                                    'Un ensayo de tracción (ASTM E8/E111, ISO 6892-1) fija E, σ0.2 y su dispersión.')})
        has_struct = ExperimentalRecord.query.filter_by(graph_id=graph_id, test_type='structural').count() > 0
        pts = self.sensor_locations(graph_id, n_sensors)
        if not has_struct:
            recs.append({'test_type': 'structural', 'priority': 2 if recs else 1,
                         'title': 'Ensayo estático de la pieza con sensores',
                         'reason': ('Ninguna medición sobre la pieza: comparar desplazamientos/deformaciones medidos con '
                                    'la simulación valida condiciones de contorno, cargas y rigidez real.'),
                         'sensors': pts})
        elif pts:
            recs.append({'test_type': 'structural', 'priority': 3, 'title': 'Repetir el ensayo estático',
                         'reason': 'Más puntos o repeticiones reducen la incertidumbre de la correlación.',
                         'sensors': pts})
        return {'recommendations': recs, 'material_id': mid}

    @staticmethod
    def sensor_locations(graph_id: str, n: int = 3) -> list[dict]:
        """Candidate sensor positions from the latest finished run: surface nodes of max |u| and
        max von Mises, kept at least 10 % of the model size apart."""
        import os
        import h5py
        from flask import current_app
        from app.design.models.simulation import SimulationRun
        run = (SimulationRun.query.filter(SimulationRun.graph_id == graph_id, SimulationRun.status == 'done',
                                          SimulationRun.purpose.in_(('run', 'reproduce')))
               .order_by(SimulationRun.created_at.desc()).first())
        if run is None:
            return []
        path = os.path.join(str(current_app.config.get('SOLVER_DATA_DIR', 'data/solver')), f'{run.id}.h5')
        if not os.path.exists(path):
            return []
        with h5py.File(path, 'r') as f:
            X = f['nodes'][:]
            U = f['fields/displacement/step_0'][:]
            vm = f['fields/von_mises_nodal/step_0'][:]
            surf = np.unique(f['surface_triangles'][:]) if 'surface_triangles' in f else np.arange(len(X))
        size = float(np.linalg.norm(X.max(0) - X.min(0)))
        out, chosen = [], []

        def pick(order, kind):
            for i in order:
                if all(np.linalg.norm(X[i] - X[j]) > 0.1 * size for j in chosen):
                    chosen.append(i)
                    return i
            return None

        mag = np.linalg.norm(U[surf], axis=1)
        for k in range(n):
            if k % 2 == 0:
                i = pick(surf[np.argsort(-mag)], 'u')
                if i is None:
                    continue
                comp = int(np.argmax(np.abs(U[i])))
                out.append({'quantity': ['ux', 'uy', 'uz'][comp],
                            'x': float(X[i, 0] * 1000), 'y': float(X[i, 1] * 1000), 'z': float(X[i, 2] * 1000),
                            'expected': float(U[i, comp] * 1000), 'unit': 'mm',
                            'why': 'Desplazamiento máximo (LVDT/comparador)'})
            else:
                i = pick(surf[np.argsort(-vm[surf])], 'vm')
                if i is None:
                    continue
                out.append({'quantity': 'strain', 'x': float(X[i, 0] * 1000), 'y': float(X[i, 1] * 1000),
                            'z': float(X[i, 2] * 1000), 'expected_von_mises_mpa': float(vm[i] / 1e6),
                            'why': 'Tensión máxima (galga en dirección principal)'})
        return out
