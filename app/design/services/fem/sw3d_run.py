"""3-D stratified σ-layer study run (FASE 10.4): same domain_2d mesh, boundaries, wind, outfalls and probes as the
2-D shallow-water run (``sw_run.setup``), solved by ``sw3d`` with L layers. Called by ``sw_run.run`` when the
material has ``layers`` > 1.

Extra material keys: ``layers``, ``closure`` (k_epsilon | constant), ``nu_v`` / ``kappa_v`` [m²/s] (background or
constant), ``bottom_roughness`` z₀ [m] (empty → from Manning per cell), ``eos`` (unesco | linear), ``temperature`` /
``salinity`` initial (scalar or [[depth m, value], …]; absent → not modelled: constant 10 °C / 0 psu), ``D_h``
[m²/s] horizontal diffusivity of T and S. BCs: ``temperature`` / ``salinity`` of the inflowing water (tide / level /
river; absent → the initial scalar, or zero gradient for a profile). Outfalls: ``temperature`` / ``salinity`` of the
effluent (absent → ambient initial scalar / 0 psu), ``release`` bottom | surface | column (default bottom).
"""
from __future__ import annotations

import time

import numpy as np

from app.design.services.fem import sw3d
from app.design.services.fem.sw_run import setup

RELEASE_SIGMA = {'bottom': 0.0, 'surface': 0.999999, 'column': None}


def _scalar(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def run(spec: dict, emit, tier: int, check_tier) -> dict:
    from app.design.services.traceability.hasher import array_hash, mesh_hash
    t_start = time.perf_counter()
    mat = spec.get('material') or {}
    L = int(mat.get('layers') or 1)
    if not 2 <= L <= 100:
        raise ValueError('Estratificado 3D: entre 2 y 100 capas σ.')
    T0, S0 = mat.get('temperature'), mat.get('salinity')
    n_act = (T0 is not None) + (S0 is not None)
    ctx = setup(spec, emit, tier, check_tier, lambda ns: 1 + 2 * L + (n_act + ns) * L)
    mesh, cached, tracers, ns, grid, nc = (ctx[k] for k in ('mesh', 'cached', 'tracers', 'ns', 'grid', 'nc'))
    zinfo, lat, bnd, binfo, warnings, wind = (ctx[k] for k in ('zinfo', 'lat', 'bnd', 'binfo', 'warnings', 'wind'))
    t_end, n_out, eta0, params, probes = (ctx[k] for k in ('t_end', 'n_out', 'eta0', 'params', 'probes'))
    closure = mat.get('closure') or 'k_epsilon'
    eos = mat.get('eos') or 'unesco'
    params.update({'layers': L, 'closure': closure, 'eos': {'model': eos} if isinstance(eos, str) else eos,
                   'temperature': T0, 'salinity': S0, 'D_h': float(mat.get('D_h') or 0.0)})
    for k in ('nu_v', 'kappa_v', 'bottom_roughness'):
        if mat.get(k) is not None:
            params[k] = float(mat[k])
    if ns:
        params['tracers'] = tracers
    names_act = (['T'] if T0 is not None else []) + (['S'] if S0 is not None else [])
    # inflow values per boundary: [T, S, passive…]; None = zero gradient
    bnd3 = {}
    for i, b in bnd.items():
        b3 = dict(b)
        if b['kind'] in ('tide', 'level', 'river'):
            row = []
            for nm, init, key in (('T', T0, 'T_in'), ('S', S0, 'S_in')):
                if nm in names_act:
                    v = b.get(key)
                    row.append(float(v) if v is not None else (float(init) if _scalar(init) else None))
            row += list(b.get('c_in') or [0.0] * ns)
            b3['c_in'] = row
        bnd3[i] = b3
    # outfalls: water + [T, S, passive] mass rates, released in one layer (or the whole column)
    sources = []
    for o in ctx['outfalls']:
        raw = o['raw']
        act = []
        for nm, init, key, dflt in (('T', T0, 'temperature', None), ('S', S0, 'salinity', 0.0)):
            if nm in names_act:
                v = raw.get(key)
                if v is None:
                    v = dflt if dflt is not None else (float(init) if _scalar(init) else 10.0)
                act.append(o['Q'] * float(v))
        rel = raw.get('release') or 'bottom'
        if rel not in RELEASE_SIGMA:
            raise ValueError(f'"{o["label"]}": liberación del vertido desconocida «{rel}» (bottom | surface | column).')
        sources.append({'cell': o['cell'], 'Q': o['Q'], 'mass': np.r_[act, o['mass'] if ns else []],
                        'factor': o['factor'], 'label': o['label'], 'sigma': RELEASE_SIGMA[rel]})
    if sources:
        params['sources'] = sources
    emit(6, f'estratificado 3D: {nc:,} celdas × {L} capas, {len(bnd3)} contornos, t = {t_end / 3600:.3g} h')

    def prog(k, total, t):
        emit(6 + 90 * k / total, f'estratificado 3D: t = {t / 3600:.3g} h ({k}/{total})')
    r = sw3d.solve(grid, params, bnd3, t_end=t_end, eta0=eta0, wind=wind, n_output=n_out, probes=probes, progress=prog)
    s3 = r['solver']
    nt = s3.nt
    iT, iS = s3.iT, s3.iS
    bed_nodes = -mesh.depth

    def nodal(U):
        u, v, c, wet = s3.primitive(U)
        wf = wet.astype(float)
        eta, den = grid.node_average(U[0] + grid.zb, wf)
        eta = np.where(den > 0, eta, bed_nodes)
        H, _ = grid.node_average(U[0])
        um, vm = (s3.frac[:, None] * u).sum(0), (s3.frac[:, None] * v).sum(0)
        out = {'eta': eta, 'H': H, 'speed': grid.node_average(np.hypot(um, vm))[0],
               'speed_s': grid.node_average(np.hypot(u[-1], v[-1]))[0],
               'u': grid.node_average(um)[0], 'v': grid.node_average(vm)[0],
               'us': grid.node_average(u[-1])[0], 'vs': grid.node_average(v[-1])[0],
               'ub': grid.node_average(u[0])[0], 'vb': grid.node_average(v[0])[0]}

        def nav(x):
            val, d_ = grid.node_average(x, wf)
            return np.where(d_ > 0, val, 0.0)
        if nt:
            for k in range(nt):
                nm = s3.names[k] if k in (iT, iS) else f'c{k - n_act}'
                out[nm + '_s'] = nav(c[k, -1])
                out[nm + '_b'] = nav(c[k, 0])
                if k not in (iT, iS):
                    out[nm] = nav((s3.frac[:, None] * c[k]).sum(0))
            if s3.active:
                rho = s3.density(c)
                out['strat'] = nav(rho[0] - rho[-1])
                out['rho_s'] = nav(rho[-1])
        return out
    times = [float(t) for t, _ in r['snaps']]
    series = [nodal(U) for _, U in r['snaps']]
    last = series[-1]
    U_end = r['snaps'][-1][1]
    wet_end = U_end[0] > params['h_dry']
    flooded_c = r['wet_ever'] & ~r['wet0']

    rows = []
    for b in mesh.boundary_info:
        rows.append({'id': b['id'], 'label': b['label'], 'kind': bnd3[b['id']]['kind'], 'length_m': b['length_m'],
                     'volume_in_m3': r['boundary_volume_in'].get(b['id'], 0.0),
                     'net_outflow_m3': r['boundary_volume_out'].get(b['id'], 0.0)})
    d = {'n_cells': nc, 'n_steps': r['n_steps'], 'dt_min_s': r['dt_min'], 'dt_max_s': r['dt_max'],
         'order': params['order'], 'h_dry_m': params['h_dry'], 'eta0_m': eta0,
         'volume_initial_m3': r['mass0'], 'volume_final_m3': r['mass1'], 'balance_error': r['balance_error'],
         'clipped_volume_m3': r['clipped_mass'], 'boundaries': rows, 'conditions': binfo,
         'inflow_open_boundaries_m3': sum(rw['volume_in_m3'] for rw in rows if rw['kind'] in ('tide', 'level')),
         'max_speed_m_s': float(r['max_speed'].max()), 'max_surface_speed_m_s': float(r['max_speed_surface'].max()),
         'max_eta_m': float(np.max(r['max_eta'][r['wet_ever']])) if r['wet_ever'].any() else None,
         'flooded_area_m2': float(grid.area[flooded_c].sum()),
         'wet_area_final_m2': float(grid.area[wet_end].sum()), 'area_m2': float(grid.area.sum()),
         'manning_default': float(mat.get('manning', 0.025)), 'manning_zones': zinfo,
         'coriolis': bool(mat.get('coriolis', True)), 'latitude_mean': float(np.mean(lat)), 'wind': bool(wind),
         'times': times, 'frame': mesh.frame.to_dict(), 'mesh_key': mesh.key, 'boundary_info': mesh.boundary_info}
    st = {'layers': L, 'closure': closure, 'eos': eos if isinstance(eos, str) else eos.get('model'),
          'rho0': s3.rho0, 'nu_v': s3.nu_b, 'kappa_v': s3.ka_b,
          'bottom_roughness_m': [float(s3.z0b.min()), float(s3.z0b.max())], 'active': names_act,
          'nut_max_m2_s': float(s3.nut.max())}
    if s3.active:
        u_, v_, c_, w_ = s3.primitive(U_end)
        rho = s3.density(c_)
        dr = np.where(w_, rho[0] - rho[-1], 0.0)
        st['stratification_max_kg_m3'] = float(dr.max())
        st['stratified_area_m2'] = float(grid.area[dr > 0.5].sum())        # Δρ > 0.5 kg/m³ bottom − surface
        st['density_range_kg_m3'] = [float(rho[:, w_].min()), float(rho[:, w_].max())] if w_.any() else None
        if not np.all(np.diff(rho[:, w_], axis=0) <= 1e-6) and w_.any():
            st['unstable_columns'] = int(np.sum(np.any(np.diff(rho, axis=0) > 1e-3, axis=0) & w_))
    if r['probe_rows']:
        P = np.asarray(r['probe_rows'])
        stride = max(1, len(P) // 500)
        idx = np.r_[np.arange(0, len(P), stride), len(P) - 1] if (len(P) - 1) % stride else np.arange(0, len(P), stride)
        w_ = 8 + 2 * nt
        d['probes'] = []
        for j, p in enumerate(probes):
            base = 1 + w_ * j
            e_, um_, vm_, h_, us_, vs_, ub_, vb_ = (P[:, base + q] for q in range(8))
            row = {'label': p['label'], 'lon': p['lon'], 'lat': p['lat'],
                   'depth_m': float(-grid.zb[r['probe_cells'][j]]),
                   'max_eta_m': float(e_.max()), 'min_eta_m': float(e_.min()),
                   'max_speed_m_s': float(np.hypot(um_, vm_).max()),
                   'curve': [[float(P[i, 0]), float(e_[i]), float(np.hypot(um_[i], vm_[i])), float(h_[i]),
                              float(np.hypot(us_[i], vs_[i])), float(np.hypot(ub_[i], vb_[i]))] for i in idx],
                   'curve_columns': ['t', 'eta', 'speed', 'H', 'speed_surface', 'speed_bottom']}
            if nt:
                cc = P[:, base + 8:base + 8 + 2 * nt]
                row['tracer_curve'] = [[float(P[i, 0])] + [float(x) for x in cc[i]] for i in idx]
                row['tracer_columns'] = ['t'] + [f'{s3.names[k]}_{lv}' for k in range(nt)
                                                 for lv in ('surface', 'bottom')]
            prof = r['profiles']
            keep = np.unique(np.linspace(0, len(prof) - 1, min(len(prof), 25)).round().astype(int))
            row['profiles'] = [prof[i][j] for i in keep]
            d['probes'].append(row)
    # fields
    nodes3 = np.column_stack([mesh.nodes, np.zeros(mesh.n_nodes)])
    fields = [{'key': 'eta', 'label': 'Nivel η', 'unit': 'm', 'series': True},
              {'key': 'speed', 'label': 'Velocidad media |ū|', 'unit': 'm/s', 'series': True},
              {'key': 'speed_s', 'label': 'Velocidad en superficie', 'unit': 'm/s', 'series': True},
              {'key': 'H', 'label': 'Calado H', 'unit': 'm', 'series': True},
              {'key': 'u', 'label': 'ū (este)', 'unit': 'm/s'}, {'key': 'v', 'label': 'v̄ (norte)', 'unit': 'm/s'},
              {'key': 'us', 'label': 'u superficie (este)', 'unit': 'm/s'},
              {'key': 'vs', 'label': 'v superficie (norte)', 'unit': 'm/s'},
              {'key': 'ub', 'label': 'u fondo (este)', 'unit': 'm/s'},
              {'key': 'vb', 'label': 'v fondo (norte)', 'unit': 'm/s'},
              {'key': 'smax', 'label': 'Velocidad media máxima', 'unit': 'm/s'},
              {'key': 'smax_b', 'label': 'Velocidad de fondo máxima', 'unit': 'm/s'},
              {'key': 'depth', 'label': 'Profundidad (batimetría)', 'unit': 'm'},
              {'key': 'flooded', 'label': 'Zona inundada (intermareal)', 'unit': ''}]
    extra = {k: last[k] for k in ('eta', 'speed', 'speed_s', 'H', 'u', 'v', 'us', 'vs', 'ub', 'vb')}
    extra.update({'smax': grid.node_average(r['max_speed'])[0], 'smax_b': grid.node_average(r['max_speed_bottom'])[0],
                  'depth': mesh.depth, 'flooded': grid.node_average(flooded_c.astype(float))[0]})
    ts = {'times': times, 'fields': {k: np.stack([s_[k] for s_ in series]) for k in ('eta', 'speed', 'speed_s', 'H')}}
    for nm, label, unit in (('T', 'Temperatura', '°C'), ('S', 'Salinidad', 'psu')):
        if nm in names_act:
            for lv, lvl in (('s', 'superficie'), ('b', 'fondo')):
                key = f'{nm}_{lv}'
                fields.append({'key': key, 'label': f'{label} ({lvl})', 'unit': unit, 'series': True})
                extra[key] = last[key]
                ts['fields'][key] = np.stack([s_[key] for s_ in series])
    if s3.active:
        fields.append({'key': 'strat', 'label': 'Estratificación Δρ fondo − superficie', 'unit': 'kg/m³',
                       'series': True})
        fields.append({'key': 'rho_s', 'label': 'Densidad en superficie', 'unit': 'kg/m³'})
        extra['strat'], extra['rho_s'] = last['strat'], last['rho_s']
        ts['fields']['strat'] = np.stack([s_['strat'] for s_ in series])
    if ns:
        names = list(s3.groups)
        blabel = {b['id']: b['label'] for b in mesh.boundary_info}
        d['tracers'] = []
        for k, sp_ in enumerate(tracers):
            kk = n_act + k
            unit = sp_.get('unit') or 'mg/L'
            nm = sp_.get('name') or f'Especie {k + 1}'
            ck = f'c{k}'
            fields += [{'key': ck, 'label': f'{nm} (media en la columna)', 'unit': unit, 'series': True},
                       {'key': ck + '_s', 'label': f'{nm} (superficie)', 'unit': unit, 'series': True},
                       {'key': ck + '_b', 'label': f'{nm} (fondo)', 'unit': unit, 'series': True},
                       {'key': f'cmax{k}', 'label': f'{nm} máx. (todas las capas)', 'unit': unit}]
            for key in (ck, ck + '_s', ck + '_b'):
                extra[key] = last[key]
                ts['fields'][key] = np.stack([s_[key] for s_ in series])
            extra[f'cmax{k}'] = grid.node_average(r['cmax'][kk])[0]
            tb = r['tracers'][kk]
            row = {'name': nm, 'unit': unit, 'D_m2_s': float(sp_.get('D') or 0),
                   'decay_1_s': float(sp_.get('decay') or 0),
                   'mass_initial': tb['mass0'], 'mass_final': tb['mass1'], 'source': tb['source'],
                   'decayed': tb['decayed'], 'clipped': tb['clipped'], 'balance_error': tb['balance_error'],
                   'boundary_out': [{'id': n_, 'label': blabel.get(n_, n_), 'net_out': tb['boundary_out'][n_],
                                     'in': tb['boundary_in'][n_]}
                                    for n_ in names if tb['boundary_out'][n_] or tb['boundary_in'][n_]],
                   'max': float(r['cmax'][kk].max())}
            thr = sp_.get('threshold')
            if thr is not None:
                row['threshold'] = float(thr)
                row['area_above_max_m2'] = float(grid.area[r['cmax'][kk] > thr].sum())
                row['hours_above_max'] = float(r['t_above'][kk].max() / 3600.0)
                fields.append({'key': f'tabove{k}', 'label': f'{nm}: horas sobre el umbral', 'unit': 'h'})
                extra[f'tabove{k}'] = grid.node_average(r['t_above'][kk] / 3600.0)[0]
            d['tracers'].append(row)
    st['budgets'] = [{'name': t_['name'], 'content_initial': t_['mass0'], 'content_final': t_['mass1'],
                      'balance_error': t_['balance_error']} for t_ in r['tracers'][:n_act]]
    errs = [t_['balance_error'] for t_ in r['tracers']]
    d['tracer_balance_error'] = max(errs) if errs else 0.0
    d['stratified'] = st
    if ctx['src_info']:
        d['outfalls'] = [dict(si, release=(o['raw'].get('release') or 'bottom'))
                         for si, o in zip(ctx['src_info'], ctx['outfalls'])]
        d['source_volume_m3'] = r['source_volume']
    if params['order'] == 2 and r['clipped_mass'] > 1e-9 * max(r['mass0'], 1):
        warnings.append(f'Se recortaron {r["clipped_mass"]:.3g} m³ de calado negativo (frentes de secado).')
    if st.get('unstable_columns'):
        warnings.append(f'{st["unstable_columns"]} columnas con densidad inestable al final (mezcla convectiva en '
                        f'curso).')
    n_dof = (1 + 2 * L + nt * L) * nc
    s = {'physics': ['shallow_water'], 'n_nodes': mesh.n_nodes, 'n_elements': mesh.n_elements, 'n_dof': n_dof,
         'element_type': 'TRI3', 'tier': tier,
         'converged': bool(r['balance_error'] < 1e-8 and all(e < 1e-8 for e in errs)),
         'n_iterations': r['n_steps'], 'final_residual': r['balance_error'],
         'solver_method': f'FV multicapa σ ({L} capas), HLL + reconstrucción hidrostática, orden {params["order"]}, '
                          f'SSP-RK2; vertical implícito ({"k-ε" if closure == "k_epsilon" else "ν constante"})',
         'wall_time_s': round(time.perf_counter() - t_start, 3), 'material_model': 'shallow_water_3d',
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
