"""Simulation reporter — JSON-LD (schema.org/Dataset) and Markdown reports (FASE 7).

Works from the SimulationRun record alone (inputs, environment, provenance, summary), so a
report can be produced for any finished run without reopening the HDF5 file.
"""
from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)

PURPOSE_LABEL = {'run': 'Simulación', 'reproduce': 'Reproducción', 'adaptive': 'Adaptativa',
                 'topology': 'Optimización topológica', 'rom': 'Modelo de orden reducido (ROM)'}
STATUS_LABEL = {'queued': 'en cola', 'running': 'calculando', 'done': 'completada',
                'failed': 'fallida', 'cancelled': 'cancelada'}

# (summary key, schema name, label, unitText, UN/CEFACT unitCode)
KEY_RESULTS = [
    ('max_displacement_mm', 'maxDisplacement', 'Desplazamiento máximo', 'mm', 'MMT'),
    ('max_von_mises_mpa', 'maxVonMises', 'Von Mises máximo (elemental)', 'MPa', 'MPA'),
    ('max_von_mises_nodal_mpa', 'maxVonMisesNodal', 'Von Mises máximo (nodal)', 'MPa', 'MPA'),
    ('equilibrium_error', 'equilibriumError', 'Error de equilibrio (relativo)', None, None),
    ('final_residual', 'finalResidual', 'Residuo final', None, None),
    # topology optimization (FASE 4); compliance = Fᵀu [J]
    ('compliance_initial', 'complianceInitial', 'Flexibilidad inicial (densidad uniforme)', 'J', 'JOU'),
    ('compliance_bw', 'complianceOptimum', 'Flexibilidad del diseño 0/1', 'J', 'JOU'),
    ('volume_fraction_bw', 'volumeFraction', 'Fracción de volumen del diseño 0/1', None, None),
    ('grayness', 'grayness', 'Fracción con densidad intermedia', None, None),
    # ROM (FASE 5)
    ('n_modes', 'romModes', 'Modos POD retenidos', None, None),
    ('validation_max_error_u', 'romErrorU', 'Error de validación máx. (desplazamientos)', None, None),
    ('validation_max_error_vm', 'romErrorVM', 'Error de validación máx. (von Mises máx.)', None, None),
]


def _fmt(v, nd=6):
    if v is None:
        return '—'
    if isinstance(v, float):
        return f'{v:.{nd}g}'
    if isinstance(v, (list, tuple)):
        return '[' + ', '.join(_fmt(x, nd) for x in v) + ']'
    return str(v)


class AutoReporter:
    """Generate human- and machine-readable reports for simulation runs."""

    def __init__(self, base_url: str = ''):
        self.base_url = base_url.rstrip('/')

    # ── JSON-LD ───────────────────────────────────────────────────────────────

    def generate_jsonld(self, run) -> dict:
        s = run.summary or {}
        env = run.environment or {}
        prov = run.provenance or {}
        measured = []
        for key, name, label, unit, code in KEY_RESULTS:
            if s.get(key) is not None:
                pv = {'@type': 'PropertyValue', 'name': name, 'description': label, 'value': s[key]}
                if unit:
                    pv['unitText'] = unit
                    pv['unitCode'] = code
                measured.append(pv)
        doc = {
            '@context': 'https://schema.org',
            '@type': 'Dataset',
            '@id': f'{self.base_url}/api/design/solver/{run.id}/report?format=jsonld',
            'identifier': [
                {'@type': 'PropertyValue', 'propertyID': 'sha256:inputs', 'value': run.hash},
                *([{'@type': 'PropertyValue', 'propertyID': 'sha256:mesh', 'value': run.mesh_hash}]
                  if run.mesh_hash else []),
                *([{'@type': 'PropertyValue', 'propertyID': 'sha256:displacement',
                    'value': run.result_hash}] if run.result_hash else []),
            ],
            'name': f'CAE Simulation {run.hash[:12]}',
            'description': self._description(run),
            'dateCreated': run.created_at.isoformat() if run.created_at else None,
            'creativeWorkStatus': run.status,
            'variableMeasured': measured,
            'measurementTechnique': f"Método de elementos finitos ({s.get('element_type', '?')}, "
                                    f"{s.get('solver_method', '?')})",
            'isAccessibleForFree': False,
            'additionalProperty': [
                {'@type': 'PropertyValue', 'name': 'tier', 'value': run.tier},
                {'@type': 'PropertyValue', 'name': 'purpose', 'value': run.purpose},
                {'@type': 'PropertyValue', 'name': 'inputs', 'value': json.dumps(run.inputs or {},
                                                                                sort_keys=True)},
            ],
            'softwareVersion': None,
            'distribution': [{
                '@type': 'DataDownload', 'encodingFormat': 'application/x-hdf5',
                'contentUrl': f'{self.base_url}/api/design/solver/{run.id}/results',
            }],
            'isBasedOn': ([f'{self.base_url}/api/design/solver/{run.parent_run_id}/report?format=jsonld']
                          if run.parent_run_id else []),
            'producer': {
                '@type': 'SoftwareApplication', 'name': 'CAE Lab FEM kernel',
                'softwareVersion': str(env.get('fem_kernel')),
                'softwareRequirements': [f'{k} {v}' for k, v in sorted(env.items()) if k != 'fem_kernel'],
                **({'version': prov['git_commit']} if prov.get('git_commit') else {}),
            },
        }
        doc['softwareVersion'] = doc['producer']['softwareVersion']
        return doc

    def _description(self, run) -> str:
        s = run.summary or {}
        parts = [f"{PURPOSE_LABEL.get(run.purpose, run.purpose)} {STATUS_LABEL.get(run.status, run.status)}"]
        if s.get('n_nodes'):
            parts.append(f"{s['n_nodes']:,} nodos, {s.get('n_elements', 0):,} elementos "
                         f"{s.get('element_type', '')}")
        if s.get('max_von_mises_mpa') is not None:
            parts.append(f"von Mises máx. {s['max_von_mises_mpa']:.4g} MPa")
        if s.get('max_displacement_mm') is not None:
            parts.append(f"desplazamiento máx. {s['max_displacement_mm']:.4g} mm")
        return '; '.join(parts) + '.'

    # ── Markdown ──────────────────────────────────────────────────────────────

    def generate_markdown(self, run, reproducibility: dict | None = None) -> str:
        s = run.summary or {}
        inp = run.inputs or {}
        L = [f'# Reporte de simulación `{run.hash[:12]}`', '',
             f'- **Run:** `{run.id}`',
             f"- **Tipo:** {PURPOSE_LABEL.get(run.purpose, run.purpose)}"
             + (f' de `{run.parent_run_id}`' if run.purpose == 'reproduce' and run.parent_run_id else ''),
             f"- **Estado:** {STATUS_LABEL.get(run.status, run.status)}",
             f"- **Fecha:** {run.created_at.isoformat(timespec='seconds') if run.created_at else '—'}",
             f'- **Tier:** {run.tier}', '']

        L += ['## Entradas', '']
        L += self._inputs_md(inp)

        L += ['', '## Configuración del solver', '',
              '| Parámetro | Valor |', '|---|---|',
              f"| Elemento | {s.get('element_type', '—')} |",
              f"| Método | {s.get('solver_method', '—')} |",
              f"| Tolerancia | {_fmt(inp.get('tolerance'))} |",
              f"| Iteraciones | {_fmt(s.get('n_iterations'))} |",
              f"| Convergió | {'sí' if s.get('converged') else 'no' if s else '—'} |",
              f"| Tiempo total | {_fmt(run.wall_time, 3)} s |"]
        mesh = s.get('mesh') or {}
        if s.get('n_nodes'):
            L.append(f"| Malla | {s['n_nodes']:,} nodos, {s.get('n_elements', 0):,} elementos, "
                     f"{s.get('n_dof', 0):,} GDL |")
        if mesh.get('mesh_size'):
            L.append(f"| Tamaño de elemento | {_fmt(mesh['mesh_size'], 4)} mm |")

        L += ['', '## Resultados', '']
        if run.status == 'failed':
            L += [f"**La simulación falló:** {(run.mesh_stats or {}).get('error', 'error desconocido')}", '']
        elif s:
            L += ['| Magnitud | Valor |', '|---|---|']
            for key, _, label, unit, _ in KEY_RESULTS:
                if s.get(key) is not None:
                    L.append(f'| {label} | {_fmt(s[key])}{" " + unit if unit else ""} |')
            if s.get('applied_load_N'):
                L.append(f"| Carga aplicada [N] | {_fmt(s['applied_load_N'])} |")
                L.append(f"| Reacciones [N] | {_fmt(s.get('reaction_N'))} |")
        else:
            L += ['Sin resultados todavía.']

        warnings = self._warnings(run)
        if warnings:
            L += ['', '## Advertencias', ''] + [f'- {w}' for w in warnings]

        if run.parameter_delta and run.parent_run_id and run.purpose != 'reproduce':
            L += ['', '## Cambios respecto a la corrida anterior', '',
                  f'Anterior: `{run.parent_run_id}`', '', '| Parámetro | Antes | Ahora |', '|---|---|---|']
            for k, (a, b) in run.parameter_delta.items():
                L.append(f'| `{k}` | {_fmt(a)} | {_fmt(b)} |')

        L += ['', '## Reproducibilidad', '']
        L += self._format_hash_block(run, reproducibility)
        return '\n'.join(L) + '\n'

    def _inputs_md(self, inp: dict) -> list:
        L = []
        mat = inp.get('material') or {}
        if mat:
            L.append(f"- **Material:** {mat.get('type', '?')}, E = {_fmt((mat.get('E') or 0) / 1e9, 5)} GPa, "
                     f"ν = {_fmt(mat.get('nu'))}, ρ = {_fmt(mat.get('rho'))} kg/m³")
        src = inp.get('mesh_source')
        geo = inp.get('geometry') or {}
        mp = inp.get('mesh_params') or {}
        if src == 'geometry':
            L.append(f"- **Geometría CAD:** STEP sha256 `{str(geo.get('step_sha256', geo.get('geometry_id', '?')))[:16]}…`, "
                     f"orden {int(mp.get('order', 2))}, tamaño "
                     + (f"{_fmt(mp['mesh_size'], 4)} mm" if mp.get('mesh_size') else 'automático'))
        elif src == 'cantilever':
            L.append('- **Malla:** viga en voladizo paramétrica ' +
                     ', '.join(f'{k}={_fmt(v)}' for k, v in sorted(mp.items())))
        else:
            L.append(f'- **Malla:** {src}')
        topo = inp.get('topology') or {}
        if topo:
            L.append(f"- **Optimización topológica:** {str(topo.get('method', 'simp')).upper()}, fracción de volumen "
                     f"{_fmt(topo.get('volume_fraction'))}, p = {_fmt(topo.get('p_penalization'))}, filtro "
                     + (f"{_fmt(topo['filter_radius'] * 1000, 3)} mm" if topo.get('filter_radius')
                        else f"{_fmt(topo.get('filter_factor'))} × arista media")
                     + f", proyección {'sí' if topo.get('projection') else 'no'}, máx. {_fmt(topo.get('max_iter'))} iteraciones")
        for bc in inp.get('bcs') or []:
            where = bc.get('face_set') or bc.get('node_set') or '?'
            dofs = ''.join('XYZ'[int(d)] for d in bc.get('dofs') or [] if 0 <= int(d) < 3)
            L.append(f"- **Restricción** U{dofs or '?'} en {_fmt(where)}"
                     + (f", valores {_fmt(bc['values'])} m" if any(bc.get('values') or []) else ''))
        for ld in inp.get('loads') or []:
            where = ld.get('face_set') or ld.get('node_set') or ld.get('node')
            if 'gravity' in ld:
                L.append(f"- **Gravedad** {_fmt(ld['gravity'])} m/s²")
            elif 'pressure' in ld:
                L.append(f"- **Presión** {_fmt(ld['pressure'])} Pa en {_fmt(where)}")
            elif 'force' in ld:
                L.append(f"- **Fuerza** {_fmt(ld['force'])} N en {_fmt(where)}")
            else:
                L.append(f'- **Carga** {json.dumps(ld, sort_keys=True)}')
        return L

    def _warnings(self, run) -> list:
        s = run.summary or {}
        w = []
        if s and not s.get('converged', True):
            w.append(f"El solver no alcanzó la tolerancia (residuo {_fmt(s.get('final_residual'))}).")
        if (s.get('equilibrium_error') or 0) > 1e-6:
            w.append(f"Error de equilibrio alto ({_fmt(s['equilibrium_error'])}): revisar cargas/restricciones.")
        if s.get('element_type') == 'T4':
            w.append('T4 subestima la rigidez en flexión (bloqueo por cortante); usar T10 para resultados.')
        mesh = s.get('mesh') or {}
        if mesh.get('curved_t10_rejected'):
            w.append('Malla T10 con nodos intermedios rectos: los curvos invertían elementos '
                     '(la geometría curva se aproxima por facetas).')
        if (run.provenance or {}).get('git_commit', '').endswith('-dirty'):
            w.append('El código tenía cambios sin commit al ejecutar: el commit registrado no basta para '
                     'reconstruir el kernel.')
        return w

    def _format_field_summary(self, summary: dict) -> dict:
        return {name: summary[key] for key, name, *_ in KEY_RESULTS if summary.get(key) is not None}

    def _format_hash_block(self, run, reproducibility: dict | None = None) -> list:
        env = run.environment or {}
        prov = run.provenance or {}
        L = ['| Huella | SHA-256 |', '|---|---|',
             f'| Entradas + entorno (hash de la corrida) | `{run.hash}` |',
             f"| Malla (nodos + conectividad) | `{run.mesh_hash or '—'}` |",
             f"| Campo de desplazamientos | `{run.result_hash or '—'}` |", '',
             '**Entorno numérico (incluido en el hash):** ' +
             ', '.join(f'{k} {v}' for k, v in sorted(env.items())), '',
             f"**Procedencia (no incluida en el hash):** host `{prov.get('host', '?')}`, "
             f"commit `{prov.get('git_commit') or '?'}`, Python {prov.get('python_full', '?')}, "
             f"{prov.get('platform', '?')}.", '',
             'Mismas entradas y mismo entorno producen el mismo hash. Para reproducir: '
             f'`POST /api/design/solver/{run.id}/reproduce` (o botón *Reproducir* en el historial); '
             'la reproducción es exacta si su hash de desplazamientos coincide.']
        if reproducibility:
            r = reproducibility
            L += ['', f"**Comparación con `{r.get('reference_run_id')}`:** "
                  f"hash de entradas {'igual' if r.get('same_hash') else 'distinto'}, "
                  f"malla {'igual' if r.get('same_mesh') else 'distinta'}, "
                  f"resultado {'idéntico bit a bit' if r.get('bitwise_identical') else 'distinto'}"
                  + (f", diferencia relativa máx. {_fmt(r['max_rel_diff_displacement'], 3)}"
                     if r.get('max_rel_diff_displacement') is not None else '') + '.']
        return L
