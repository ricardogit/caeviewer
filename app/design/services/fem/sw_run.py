"""Shallow-water study run (FASE 10.3): domain_2d spec → Mesh2D (FASE 10.5 cache) → finite-volume solve → kernel
result (nodal fields for the Results viewer, transient series, summary). Called by FEMKernel._solve.

Spec:
  material  {'type': 'shallow_water', 'rho', 'manning' (n), 'manning_zone_key' (zone attribute, default
             'manning'), 'coriolis' (bool), 'nu_t' [m²/s], 'h_dry' [m], 'eta0' [m] (None → level of the tide /
             level BC, else 0), 'order' (1|2), 'cfl'}
  time      {'t_end' [s], 'n_output'}
  bcs       {'sw_bc': 'tide'|'level'|'river'|'free'|'wall', 'boundaries': [ids], + 'tide': {constituents, z0} |
             'level': m | 'discharge': m³/s | 'forcing_dataset' (+ 'column'), 'ramp_s', 'label'}
  loads     {'wind': {'speed', 'direction'} | {'forcing_dataset', 'u_column', 'v_column'}, 'label'}
  probes    [{'label', 'lon', 'lat'}]
Boundary ids are those of the mesh (``edge<i>`` per drawn side, ``coast``); unassigned ``open`` sides are
transmissive (warning), ``river`` sides need a discharge, coast is a wall.
"""
from __future__ import annotations

import time

import numpy as np

from app.design.services.fem import shallow_water as sw

SW_BC_KINDS = ('tide', 'level', 'river', 'free', 'wall')


def is_sw_bc(b: dict) -> bool:
    return 'sw_bc' in b


def is_sw_load(ld: dict) -> bool:
    return 'wind' in ld


def _series_signal(fc: dict, column: str | None, label: str, ramp: float):
    if fc['kind'] == 'harmonics':
        return sw.make_signal({'constituents': fc['constituents'], 'z0': fc['z0'], 'ramp': ramp}), \
            {'source': 'harmonics', 'constituents': [c['name'] for c in fc['constituents']]}
    cols = fc['columns']
    if column is None:
        column = next(iter(cols))
    if column not in cols:
        raise ValueError(f'"{label}": la serie no tiene la columna «{column}» ({", ".join(cols)}).')
    return sw.make_signal({'series': {'t': fc['t'], 'v': cols[column]}, 'ramp': ramp}), \
        {'source': 'series', 'column': column}


def boundary_setup(bcs: list, mesh) -> tuple[dict, list, list]:
    """{boundary id: {'kind', 'signal', 'label'}}, info rows, warnings."""
    from app.geodata.service import load_forcing
    known = {b['id']: b for b in mesh.boundary_info}
    out, info, warnings = {}, [], []
    for b in bcs:
        kind = b['sw_bc']
        if kind not in SW_BC_KINDS:
            raise ValueError(f'"{b.get("label")}": contorno de aguas someras desconocido «{kind}».')
        ids = b.get('boundaries') or []
        if not ids:
            raise ValueError(f'"{b.get("label")}": no se aplica a ningún contorno del dominio.')
        for i in ids:
            if i not in known:
                raise ValueError(f'"{b.get("label")}": el contorno «{i}» no existe en la malla '
                                 f'({", ".join(known)}).')
            if i in out:
                raise ValueError(f'El contorno «{known[i]["label"]}» tiene dos condiciones '
                                 f'(«{out[i]["label"]}» y «{b.get("label")}»).')
        ramp = float(b.get('ramp_s') or 0)
        meta = {}
        if kind == 'tide':
            if b.get('forcing_dataset'):
                sig, meta = _series_signal(load_forcing(b['forcing_dataset']), b.get('column'), b.get('label'), ramp)
            else:
                t = b.get('tide') or {}
                if not t.get('constituents'):
                    raise ValueError(f'"{b.get("label")}": la marea necesita constituyentes o un forzamiento.')
                sig = sw.make_signal({**t, 'ramp': ramp})
                meta = {'source': 'harmonics', 'constituents': [c['name'] for c in t['constituents']]}
        elif kind == 'level':
            sig = sw.make_signal({'value': float(b.get('level', 0.0))})
        elif kind == 'river':
            if b.get('forcing_dataset'):
                sig, meta = _series_signal(load_forcing(b['forcing_dataset']), b.get('column'), b.get('label'), ramp)
            else:
                q = float(b.get('discharge', 0.0))
                sig = sw.make_signal({'value': q}) if ramp <= 0 else (
                    lambda t, q=q, r=ramp: q * (1.0 if t >= r else 0.5 * (1 - np.cos(np.pi * t / r))))
        else:
            sig = None
        for i in ids:
            out[i] = {'kind': kind, 'signal': sig, 'label': b.get('label') or kind}
        info.append({'label': b.get('label'), 'kind': kind, 'boundaries': ids, **meta})
    for i, bi in known.items():
        if i in out:
            continue
        if bi['kind'] == 'river':
            raise ValueError(f'El contorno «{bi["label"]}» es de río pero no tiene caudal (BC «Caudal de río»).')
        if bi['kind'] == 'open':
            out[i] = {'kind': 'free', 'signal': None, 'label': bi['label']}
            warnings.append(f'Mar abierto «{bi["label"]}» sin marea ni nivel: salida libre (transmisiva).')
        else:
            out[i] = {'kind': 'wall', 'signal': None, 'label': bi['label']}
    return out, info, warnings


def run(spec: dict, emit, tier: int, check_tier) -> dict:
    """``emit(pct, message)``; ``check_tier(n_nodes, n_elements, n_dof, tier)``."""
    from app.design.services.traceability.hasher import array_hash, mesh_hash
    from app.geodata.service import get_or_build_mesh, load_forcing
    t_start = time.perf_counter()
    mat = spec.get('material') or {}
    if mat.get('type') != 'shallow_water':
        raise ValueError('Dominio 2D: el material debe ser «Agua (aguas someras)».')
    emit(2, 'malla 2D del dominio')
    mesh, cached = get_or_build_mesh(spec['domain_2d'], progress=lambda p, m: emit(2 + p * 0.03, m))
    check_tier(mesh.n_nodes, mesh.n_elements, 3 * mesh.n_elements, tier)
    if not mesh.stats.get('has_bathymetry', True) or not np.isfinite(mesh.depth).all():
        raise ValueError('Aguas someras: el dominio necesita batimetría (marque una capa de batimetría en el modo '
                         'Mapa y regenere la malla).')
    grid = sw.SWGrid(mesh.nodes, mesh.tris, mesh.depth, mesh.boundary)
    nc = grid.nc
    # Manning per cell (zone attribute overrides the default n)
    n = np.full(nc, float(mat.get('manning', 0.025)))
    key = mat.get('manning_zone_key') or 'manning'
    zinfo = []
    for zi, z in enumerate(mesh.zones or []):
        val = (z.get('props') or {}).get(key)
        try:
            val = float(val)
        except (TypeError, ValueError):
            continue
        sel = mesh.zone == zi
        n[sel] = val
        zinfo.append({'label': z['label'], 'manning': val, 'n_cells': int(sel.sum())})
    lon, lat = mesh.frame.to_lonlat(grid.cen[:, 0], grid.cen[:, 1])
    f = 2 * sw.OMEGA * np.sin(np.radians(lat)) if mat.get('coriolis', True) else 0.0
    bnd, binfo, warnings = boundary_setup([b for b in spec.get('bcs') or [] if is_sw_bc(b)], mesh)
    # wind
    wind = None
    winds = [ld for ld in spec.get('loads') or [] if is_sw_load(ld)]
    if len(winds) > 1:
        raise ValueError('Aguas someras: solo un viento por estudio.')
    if winds:
        w = winds[0]['wind']
        if w.get('forcing_dataset'):
            fc = load_forcing(w['forcing_dataset'])
            if fc['kind'] != 'series':
                raise ValueError('Viento: el forzamiento debe ser una serie temporal (columnas u, v en m/s).')
            cu, cv = w.get('u_column') or 'u', w.get('v_column') or 'v'
            if cu not in fc['columns'] or cv not in fc['columns']:
                raise ValueError(f'Viento: la serie necesita columnas «{cu}» y «{cv}» ({", ".join(fc["columns"])}).')
            wind = sw.wind_vector({'series': {'t': fc['t'], 'u': fc['columns'][cu], 'v': fc['columns'][cv]}})
        else:
            wind = sw.wind_vector(w)
    tm = spec.get('time') or {}
    t_end = float(tm.get('t_end') or 0)
    if not t_end > 0:
        raise ValueError('Aguas someras: indique la duración de la simulación (t_end > 0).')
    n_out = int(min(max(int(tm.get('n_output') or 48), 1), 400))
    eta0 = mat.get('eta0')
    if eta0 is None:
        lv = [v['signal'](0.0) for v in bnd.values() if v['kind'] in ('tide', 'level')]
        eta0 = float(np.mean(lv)) if lv else 0.0
    params = {'manning': n, 'coriolis_f': f, 'nu_t': float(mat.get('nu_t') or 0), 'h_dry': float(mat.get('h_dry') or 0.01),
              'order': int(mat.get('order') or 2), 'rho': float(mat.get('rho') or 1025.0)}
    if mat.get('cfl'):
        params['cfl'] = float(mat['cfl'])
    probes = []
    for i, p in enumerate(spec.get('probes') or []):
        x, y = mesh.frame.from_lonlat([p['lon']], [p['lat']])
        probes.append({'label': p.get('label') or f'P{i + 1}', 'xy': [float(x[0]), float(y[0])],
                       'lon': p['lon'], 'lat': p['lat']})
    emit(6, f'aguas someras: {nc:,} celdas, {len(bnd)} contornos, t = {t_end / 3600:.3g} h')

    def prog(k, total, t):
        emit(6 + 90 * k / total, f'aguas someras: t = {t / 3600:.3g} h ({k}/{total})')
    r = sw.solve(grid, params, bnd, t_end=t_end, eta0=eta0, wind=wind, n_output=n_out, probes=probes, progress=prog)

    # ── fields on the nodes ───────────────────────────────────────────────────
    bed_nodes = -mesh.depth

    def nodal(U):
        u, v, wet = r['solver'].velocity(U)
        eta_c = U[0] + grid.zb
        eta, den = grid.node_average(eta_c, wet.astype(float))
        eta = np.where(den > 0, eta, bed_nodes)                 # dry: ground level
        H, _ = grid.node_average(U[0])
        sp, _ = grid.node_average(np.hypot(u, v))
        un, _ = grid.node_average(u)
        vn, _ = grid.node_average(v)
        return eta, H, sp, un, vn
    times = [float(t) for t, _ in r['snaps']]
    series = [nodal(U) for _, U in r['snaps']]
    eta, H, sp, un, vn = series[-1]
    smax, _ = grid.node_average(r['max_speed'])
    flooded_c = r['wet_ever'] & ~r['wet0']
    flooded, _ = grid.node_average(flooded_c.astype(float))
    U_end = r['snaps'][-1][1]
    wet_end = U_end[0] > params['h_dry']

    rows = []
    for b in mesh.boundary_info:
        k = bnd[b['id']]['kind']
        rows.append({'id': b['id'], 'label': b['label'], 'kind': k, 'length_m': b['length_m'],
                     'volume_in_m3': r['boundary_volume_in'].get(b['id'], 0.0),
                     'net_outflow_m3': r['boundary_volume_out'].get(b['id'], 0.0)})
    tide_in = sum(rw['volume_in_m3'] for rw in rows if rw['kind'] in ('tide', 'level'))
    d = {'n_cells': nc, 'n_steps': r['n_steps'], 'dt_min_s': r['dt_min'], 'dt_max_s': r['dt_max'],
         'order': params['order'], 'h_dry_m': params['h_dry'], 'eta0_m': eta0,
         'volume_initial_m3': r['mass0'], 'volume_final_m3': r['mass1'], 'balance_error': r['balance_error'],
         'clipped_volume_m3': r['clipped_mass'], 'boundaries': rows, 'conditions': binfo,
         'inflow_open_boundaries_m3': tide_in,
         'max_speed_m_s': float(r['max_speed'].max()), 'froude_max': r['froude_max'],
         'max_eta_m': float(np.max(r['max_eta'][r['wet_ever']])) if r['wet_ever'].any() else None,
         'flooded_area_m2': float(grid.area[flooded_c].sum()),
         'wet_area_final_m2': float(grid.area[wet_end].sum()), 'area_m2': float(grid.area.sum()),
         'manning_default': float(mat.get('manning', 0.025)), 'manning_zones': zinfo,
         'coriolis': bool(mat.get('coriolis', True)),
         'latitude_mean': float(np.mean(lat)), 'wind': bool(wind), 'times': times,
         'frame': mesh.frame.to_dict(), 'mesh_key': mesh.key, 'boundary_info': mesh.boundary_info}
    if r['probe_rows']:
        P = np.asarray(r['probe_rows'])
        stride = max(1, len(P) // 500)
        idx = np.r_[np.arange(0, len(P), stride), len(P) - 1] if (len(P) - 1) % stride else np.arange(0, len(P), stride)
        d['probes'] = []
        for j, p in enumerate(probes):
            e_, u_, v_, h_ = (P[:, 1 + 4 * j + q] for q in range(4))
            d['probes'].append({'label': p['label'], 'lon': p['lon'], 'lat': p['lat'],
                                'depth_m': float(-grid.zb[r['probe_cells'][j]]),
                                'max_eta_m': float(e_.max()), 'min_eta_m': float(e_.min()),
                                'max_speed_m_s': float(np.hypot(u_, v_).max()),
                                'curve': [[float(P[i, 0]), float(e_[i]), float(np.hypot(u_[i], v_[i])), float(h_[i])]
                                          for i in idx]})
    if r['froude_max'] > 1:
        warnings.append(f'Flujo supercrítico (Froude {r["froude_max"]:.2f}).')
    if params['order'] == 2 and r['clipped_mass'] > 1e-9 * max(r['mass0'], 1):
        warnings.append(f'Se recortaron {r["clipped_mass"]:.3g} m³ de calado negativo (frentes de secado).')
    nodes3 = np.column_stack([mesh.nodes, np.zeros(mesh.n_nodes)])
    fields = [{'key': 'eta', 'label': 'Nivel η', 'unit': 'm', 'series': True},
              {'key': 'speed', 'label': 'Velocidad |u|', 'unit': 'm/s', 'series': True},
              {'key': 'H', 'label': 'Calado H', 'unit': 'm', 'series': True},
              {'key': 'u', 'label': 'u (este)', 'unit': 'm/s'}, {'key': 'v', 'label': 'v (norte)', 'unit': 'm/s'},
              {'key': 'smax', 'label': 'Velocidad máxima', 'unit': 'm/s'},
              {'key': 'depth', 'label': 'Profundidad (batimetría)', 'unit': 'm'},
              {'key': 'flooded', 'label': 'Zona inundada (intermareal)', 'unit': ''}]
    extra = {'eta': eta, 'speed': sp, 'H': H, 'u': un, 'v': vn, 'smax': smax, 'depth': mesh.depth,
             'flooded': flooded}
    ts = {'times': times, 'fields': {'eta': np.stack([s_[0] for s_ in series]),
                                      'speed': np.stack([s_[2] for s_ in series]),
                                      'H': np.stack([s_[1] for s_ in series])}}
    s = {'physics': ['shallow_water'], 'n_nodes': mesh.n_nodes, 'n_elements': mesh.n_elements, 'n_dof': 3 * nc,
         'element_type': 'TRI3', 'tier': tier, 'converged': bool(r['balance_error'] < 1e-8),
         'n_iterations': r['n_steps'], 'final_residual': r['balance_error'],
         'solver_method': f'FV HLL + reconstrucción hidrostática, orden {params["order"]}, SSP-RK2',
         'wall_time_s': round(time.perf_counter() - t_start, 3), 'material_model': 'shallow_water',
         'shallow_water': d, 'extra_fields': fields,
         'mesh_hash': mesh_hash(mesh.nodes, mesh.tris), 'result_hash': array_hash(U_end),
         'mesh': {'source': 'domain_2d', 'cached': cached, **{k: mesh.stats.get(k) for k in
                                                              ('n_nodes', 'n_elements', 'min_angle_deg', 'h_min_m',
                                                               'h_max_m', 'depth_min_m', 'depth_max_m')}}}
    if warnings:
        s['warnings'] = warnings
    return {'extra_fields': extra, 'time_series': ts,
            'solve_info': {'method': s['solver_method'], 'converged': s['converged'],
                           'final_residual': r['balance_error']},
            'surface_triangles': mesh.tris.tolist(), 'nodes': nodes3.tolist(), 'elements': mesh.tris.tolist(),
            'summary': s}
