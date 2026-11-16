"""Graph-to-solver-spec translation layer.

Extrae propiedades de nodos y ARISTAS del grafo. Phase 2-3: edge-aware solver.

FASE 2 (caras CAD): un GEOMETRY con ``geometry_id`` se malla desde el CAD
(``mesh_source='geometry'``) y los BC/LOAD con ``entity_ids`` (UUID persistentes
de caras) se traducen a ``face_set`` = ['F_<índice>', ...] en esa versión.
Unidades: el solver trabaja en SI (m, N, Pa); fuerzas y presiones se convierten
desde la unidad declarada en el nodo.
"""
import math
from app.design.models.graph import DesignGraph, DesignNode, DesignEdge
from app.design.services.graph_service import DesignGraphService


class GraphSpecError(ValueError):
    """The graph cannot be turned into a solver spec (message is user-facing, Spanish)."""


FORCE_UNITS = {'N': 1.0, 'kN': 1e3, 'MN': 1e6, 'lbf': 4.4482216152605}
PRESSURE_UNITS = {'Pa': 1.0, 'kPa': 1e3, 'MPa': 1e6, 'GPa': 1e9, 'psi': 6894.757293168, 'bar': 1e5}
ACCEL_UNITS = {'m/s²': 1.0, 'm/s2': 1.0, 'g': 9.80665}
FLUX_UNITS = {'W/m²': 1.0, 'W/m2': 1.0, 'kW/m²': 1e3, 'kW/m2': 1e3}
SOURCE_UNITS = {'W/m³': 1.0, 'W/m3': 1.0, 'kW/m³': 1e3, 'kW/m3': 1e3, 'MW/m³': 1e6, 'MW/m3': 1e6}
THERMAL_LOAD_TYPES = ('heat_flux', 'convection', 'heat_source')
BC_TYPE_DOFS = {'fixed': [0, 1, 2], 'pinned': [0, 1, 2],
                'roller_x': [0], 'roller_y': [1], 'roller_z': [2]}


def graph_to_solver_spec(graph_id: str) -> dict:
    """Extrae material, BC, LOAD de nodos y aristas con edge-aware scoping.

    Phase 2-3: Si hay aristas CONSTRAINS_MATERIAL/CONSTRAINS_BC/APPLIED_TO,
    usa esas para scope. Si no, fallback a lógica global (Phase 1).

    Args:
        graph_id: UUID del DesignGraph

    Returns:
        dict: spec compatible con FEMKernel con:
            - material: { type, E, nu, rho }
            - bcs: [{ node_set, dofs, values, geometry_id? }]
            - loads: [{ node_set, force, geometry_id? }]
            - mesh_source, mesh_id, tier
    """

    graph = DesignGraph.query.filter_by(id=graph_id).first()
    if not graph:
        raise ValueError(f"Graph {graph_id} not found")

    spec = {
        'physics': ['structural'],
        'mesh_source': 'cantilever',
        'material': {
            'type': 'linear_elastic_isotropic',
            'E': 210e9,
            'nu': 0.3,
            'rho': 7800.0,
        },
        'bcs': [],
        'loads': [],
    }

    service = DesignGraphService()
    nodes = DesignNode.query.filter_by(graph_id=graph_id).order_by(DesignNode.created_at, DesignNode.id).all()
    node_map = {str(n.id): n for n in nodes}

    # Phase 1 fallback: collect all nodes by type
    material_nodes = [n for n in nodes if n.node_type == 'MATERIAL']
    geometry_nodes = [n for n in nodes if n.node_type == 'GEOMETRY']
    bc_nodes = [n for n in nodes if n.node_type == 'BC']
    load_nodes = [n for n in nodes if n.node_type == 'LOAD']

    # ── Material ───────────────────────────────────────────────────────────

    if material_nodes:
        mat_node = material_nodes[0]  # Use first material as default
        props = mat_node.properties or {}
        spec['material'] = {
            'type': props.get('model_type', 'linear_elastic_isotropic'),
            'E': float(props.get('E') if props.get('E') is not None else 210e9),
            'nu': float(props.get('nu') if props.get('nu') is not None else 0.3),
            'rho': float(props.get('rho') if props.get('rho') is not None else 7800.0),
        }
        if spec['material']['type'] == 'elastoplastic_vonmises':
            _plastic_material(spec, mat_node)
        elif spec['material']['type'] == 'linear_elastic_orthotropic':
            _orthotropic_material(spec, mat_node)
        elif spec['material']['type'] == 'hyperelastic_neohookean':
            # large deformations: Newton with load steps (dead loads), E and ν are the small-strain values
            spec['n_load_steps'] = int(props.get('load_steps') or 10)
        elif spec['material']['type'] == 'viscoelastic_maxwell':
            _viscoelastic_material(spec, mat_node)
        elif spec['material']['type'] in ('piezoelectric', 'thermopiezoelectric'):
            _piezo_material(spec, mat_node)
        elif spec['material']['type'] == 'newtonian_fluid':
            mu = props.get('mu')
            if mu in (None, '') or float(mu) <= 0:
                raise GraphSpecError(f'"{mat_node.label}": el fluido necesita la viscosidad dinámica μ > 0 (Pa·s).')
            spec['material'] = {'type': 'newtonian_fluid', 'mu': float(mu),
                                'rho': float(props.get('rho') if props.get('rho') is not None else 1000.0)}
            flow_model = props.get('flow_model') or 'stokes'
            if flow_model not in ('stokes', 'navier_stokes'):
                raise GraphSpecError(f'"{mat_node.label}": modelo de flujo desconocido «{flow_model}» '
                                     '(stokes | navier_stokes).')
            if flow_model == 'navier_stokes':        # only when on: Stokes studies keep their hash
                if not spec['material']['rho'] > 0:
                    raise GraphSpecError(f'"{mat_node.label}": Navier-Stokes necesita la densidad ρ > 0.')
                spec['material']['inertia'] = True
                if props.get('stabilization') == 'supg':     # opt-in: unstabilised studies keep their hash
                    spec['material']['stabilization'] = 'supg'
        elif spec['material']['type'] == 'scalar_transport':
            _transport_material(spec, mat_node)
        elif spec['material']['type'] == 'linear_magnetic':
            mu_r = props.get('mu_r')
            if mu_r in (None, '') or float(mu_r) <= 0:
                raise GraphSpecError(f'"{mat_node.label}": el material magnético necesita la permeabilidad '
                                     'relativa μr > 0.')
            spec['material'] = {'type': 'linear_magnetic', 'mu_r': float(mu_r),
                                'Br': [float(props.get(k) or 0) for k in ('Br_x', 'Br_y', 'Br_z')],
                                'rho': spec['material']['rho']}
            _magnetic_saturation(spec, mat_node)

    # ── GEOMETRY ───────────────────────────────────────────────────────────

    if geometry_nodes:
        geom_node = geometry_nodes[0]
        props = geom_node.properties or {}
        # Fase 1b: versioned CAD geometry with persistent face IDs (app.geometry).
        # Consumed by the Gmsh/CalculiX path in Fase 2; BC/LOAD entity_ids refer to its faces.
        if props.get('geometry_id'):
            spec['geometry_id'] = props['geometry_id']
        mesh_id = props.get('mesh_id')
        if props.get('geometry_id'):
            spec['mesh_source'] = 'geometry'
            spec['mesh_params'] = {'order': int(props.get('element_order', 2))}
            if props.get('mesh_size_mm'):
                spec['mesh_params']['mesh_size'] = float(props['mesh_size_mm'])
        elif mesh_id:
            spec['mesh_source'] = 'cae_mesh'
            spec['mesh_id'] = mesh_id
        elif props.get('shape') == 'beam':
            # FASE 9: parametric beam defined in the graph (no CAD). Dimensions in mm; faces
            # 'fixed' (x = 0) and 'tip' (x = L) are the default BC / LOAD sets. T10 by default.
            spec['mesh_params'] = {
                'length': float(props.get('length_mm') or 50) / 1000.0,
                'width': float(props.get('width_mm') or 10) / 1000.0,
                'height': float(props.get('height_mm') or 10) / 1000.0,
                'n_along_length': int(props.get('n_div') or 12),
                'order': int(props.get('element_order') or 2),
            }

        tier = geom_node.tier if geom_node.tier is not None else props.get('tier', 1)
        spec['tier'] = int(tier)

    # ── BC & LOAD with Phase 2-3 edge scoping ──────────────────────────────

    ctx = {'geometry_id': spec.get('geometry_id'), 'normals': None}
    use_edge_scoping = False
    edges = DesignEdge.query.filter_by(graph_id=graph_id).order_by(DesignEdge.created_at, DesignEdge.id).all()

    # Check if any CONSTRAINS_BC or APPLIED_TO edges exist (Phase 2+ indicator)
    if any(e.edge_type in ('CONSTRAINS_BC', 'APPLIED_TO') for e in edges):
        use_edge_scoping = True

    if use_edge_scoping and geometry_nodes:
        # Phase 2-3: Edge-aware scoping
        for geom in geometry_nodes:
            geom_id = str(geom.id)

            # Get BCs for this geometry via CONSTRAINS_BC edge
            bc_edges = DesignEdge.query.filter_by(
                graph_id=graph_id,
                target_id=geom.id,
                edge_type='CONSTRAINS_BC'
            ).order_by(DesignEdge.created_at, DesignEdge.id).all()
            for bc_edge in bc_edges:
                bc_node = node_map.get(str(bc_edge.source_id))
                if bc_node and bc_node.node_type == 'BC':
                    bc_entry = _bc_node_to_entry(ctx, bc_node, geom_id)
                    spec['bcs'].append(bc_entry)

            # Get LOADs for this geometry via APPLIED_TO edge
            load_edges = DesignEdge.query.filter_by(
                graph_id=graph_id,
                target_id=geom.id,
                edge_type='APPLIED_TO'
            ).order_by(DesignEdge.created_at, DesignEdge.id).all()
            for load_edge in load_edges:
                load_node = node_map.get(str(load_edge.source_id))
                if load_node and load_node.node_type == 'LOAD':
                    load_entry = _load_node_to_entry(ctx, load_node, geom_id)
                    spec['loads'].append(load_entry)
    else:
        # Phase 1 fallback: all BCs/LOADs to all GEOMETRIEs
        for bc_node in bc_nodes:
            bc_entry = _bc_node_to_entry(ctx, bc_node)
            spec['bcs'].append(bc_entry)

        for load_node in load_nodes:
            load_entry = _load_node_to_entry(ctx, load_node)
            spec['loads'].append(load_entry)

    _set_physics(spec, material_nodes[0] if material_nodes else None)
    _finalize_physics(spec)
    return spec


PIEZO_TYPES = ('piezoelectric', 'thermopiezoelectric')


def _magnetic_saturation(spec: dict, node) -> None:
    """MATERIAL ``saturation``: none (linear μr) | tanh (μr = initial, ``Js`` saturation polarisation [T]) |
    table (``bh_points`` [[H A/m, B T], …]). Absent / none → linear (hashes unchanged)."""
    from app.design.services.fem.magnetic import BHCurve
    p = node.properties or {}
    mode = p.get('saturation') or 'none'
    if mode == 'none':
        return
    if mode == 'tanh':
        curve = {'model': 'tanh', 'mu_r': spec['material']['mu_r'], 'Js': p.get('Js')}
    elif mode == 'table':
        curve = {'model': 'table', 'points': p.get('bh_points') or []}
    else:
        raise GraphSpecError(f'"{node.label}": saturación desconocida {mode!r} (none | tanh | table).')
    try:
        c = BHCurve(curve)
    except (TypeError, ValueError) as e:
        raise GraphSpecError(f'"{node.label}": {e}')
    if any(spec['material']['Br']):
        raise GraphSpecError(f'"{node.label}": saturación e imán permanente (Br) a la vez no están soportados.')
    spec['material']['bh_curve'] = c.spec
    spec['material']['mu_r'] = c.mu_r_initial


RATE_UNITS = {'1/s': 1.0, '1/h': 1 / 3600.0, '1/d': 1 / 86400.0}
TIME_UNITS = {'s': 1.0, 'min': 60.0, 'h': 3600.0, 'd': 86400.0}
TRANSPORT_LOAD_TYPES = ('species_flux', 'exchange', 'species_source', 'point_source')


def _num(props: dict, key: str, label: str, what: str, default=None, positive=False, nonneg=False) -> float:
    v = props.get(key)
    if v in (None, ''):
        if default is None:
            raise GraphSpecError(f'"{label}": falta {what}.')
        return float(default)
    try:
        x = float(v)
    except (TypeError, ValueError):
        raise GraphSpecError(f'"{label}": {what} debe ser numérico.')
    if (positive and not x > 0) or (nonneg and x < 0):
        raise GraphSpecError(f'"{label}": {what} debe ser {"> 0" if positive else "≥ 0"}.')
    return x


def _decay_rate(sp_props: dict, label: str) -> float:
    """Species decay λ [1/s] from ``decay`` + ``decay_unit`` (1/s | 1/h | 1/d | T90_h: λ = ln 10 / T90)."""
    v = sp_props.get('decay')
    if v in (None, '', 0, '0'):
        return 0.0
    unit = sp_props.get('decay_unit') or '1/s'
    x = _num(sp_props, 'decay', label, 'el decaimiento', positive=True)
    if unit == 'T90_h':
        return math.log(10.0) / (x * 3600.0)
    if unit not in RATE_UNITS:
        raise GraphSpecError(f'"{label}": unidad de decaimiento «{unit}» no reconocida (1/s, 1/h, 1/d, T90_h).')
    return x * RATE_UNITS[unit]


def _history(props: dict, label: str):
    """Time series [[t, factor], …] (t in the study time unit, scaled to s in ``_finalize_physics``) or ``t_off``:
    on until t_off, then off."""
    if props.get('history'):
        try:
            h = [[float(t), float(f)] for t, f in props['history']]
        except (TypeError, ValueError):
            raise GraphSpecError(f'"{label}": serie temporal inválida ([[t, factor], …]).')
        if any(b[0] < a[0] for a, b in zip(h, h[1:])):
            raise GraphSpecError(f'"{label}": la serie temporal necesita tiempos crecientes.')
        return h
    if props.get('t_off') not in (None, ''):
        t = _num(props, 't_off', label, 'el tiempo de corte', positive=True)
        return [[0.0, 1.0], [t, 1.0], [t * (1 + 1e-9), 0.0]]
    return None


def _transport_material(spec: dict, node) -> None:
    """MATERIAL ``scalar_transport`` (FASE 10.1): ``species`` [{name, D [m²/s], decay + decay_unit, unit, threshold,
    c0, pulse_center_mm, pulse_sigma_mm, pulse_peak}], ``reaction_model`` none | streeter_phelps (kd, ka in
    ``rate_unit``, do_sat), ``velocity_source`` uniform (vx, vy, vz m/s) | run (``velocity_run_id``, a finished fluid
    run on the same mesh), ``stabilization`` supg | none, ``transient`` + t_end / time_steps / scheme / n_output in
    ``time_unit``, ``probes`` [{label, x, y, z mm}]."""
    p = node.properties or {}
    label = node.label
    species_p = p.get('species') or [{'name': 'Contaminante', 'D': 1e-6}]
    if not isinstance(species_p, list) or not species_p:
        raise GraphSpecError(f'"{label}": defina al menos una especie.')
    rx_model = p.get('reaction_model') or 'none'
    if rx_model == 'streeter_phelps' and len(species_p) != 2:
        raise GraphSpecError(f'"{label}": Streeter–Phelps usa dos especies (DBO y déficit de oxígeno).')
    species, initial = [], []
    for i, sp_ in enumerate(species_p):
        name = str(sp_.get('name') or f'Especie {i + 1}')
        lab = f'{label} · {name}'
        d = {'name': name, 'D': _num(sp_, 'D', lab, 'la difusividad D (m²/s)', default=0.0, nonneg=True),
             'decay': _decay_rate(sp_, lab), 'unit': sp_.get('unit') or 'mg/L'}
        if sp_.get('threshold') not in (None, ''):
            d['threshold'] = _num(sp_, 'threshold', lab, 'el umbral')
        species.append(d)
        if sp_.get('pulse_sigma_mm') not in (None, ''):
            c = sp_.get('pulse_center_mm') or [0, 0, 0]
            try:
                center = [float(v) / 1000.0 for v in c]
            except (TypeError, ValueError):
                raise GraphSpecError(f'"{lab}": centro del pulso inválido (x, y, z en mm).')
            initial.append({'gaussian': {'center': center,
                                         'sigma': _num(sp_, 'pulse_sigma_mm', lab, 'σ del pulso', positive=True) / 1000.0,
                                         'peak': _num(sp_, 'pulse_peak', lab, 'el pico del pulso', default=1.0)}})
        else:
            initial.append({'value': _num(sp_, 'c0', lab, 'la concentración inicial', default=0.0)})
    m = {'type': 'scalar_transport', 'species': species}
    if rx_model == 'streeter_phelps':
        f = RATE_UNITS.get(p.get('rate_unit') or '1/d')
        if f is None:
            raise GraphSpecError(f'"{label}": unidad de tasa «{p.get("rate_unit")}» no reconocida (1/s, 1/h, 1/d).')
        m['reaction'] = {'model': 'streeter_phelps',
                         'kd': _num(p, 'kd', label, 'la tasa de desoxigenación kd', positive=True) * f,
                         'ka': _num(p, 'ka', label, 'la tasa de reaireación ka', positive=True) * f,
                         'do_sat': _num(p, 'do_sat', label, 'el oxígeno de saturación', default=0.0, nonneg=True)}
    elif rx_model != 'none':
        raise GraphSpecError(f'"{label}": modelo de reacción desconocido «{rx_model}» (none | streeter_phelps).')
    src = p.get('velocity_source') or 'uniform'
    if src == 'run':
        if not p.get('velocity_run_id'):
            raise GraphSpecError(f'"{label}": elija el run de fluido que da la velocidad.')
        m['velocity'] = {'run_id': str(p['velocity_run_id'])}
    elif src == 'uniform':
        m['velocity'] = [_num(p, k, label, k, default=0.0) for k in ('vx', 'vy', 'vz')]
    else:
        raise GraphSpecError(f'"{label}": origen de velocidad desconocido «{src}» (uniform | run).')
    if p.get('stabilization') == 'none':
        m['stabilization'] = 'none'
    if any(ic.get('value') or 'gaussian' in ic for ic in initial):
        m['initial'] = initial
    spec['material'] = m
    t_scale = TIME_UNITS.get(p.get('time_unit') or 's')
    if t_scale is None:
        raise GraphSpecError(f'"{label}": unidad de tiempo «{p.get("time_unit")}» no reconocida (s, min, h, d).')
    spec['transport_time_scale'] = t_scale              # popped in _finalize_physics (BC/LOAD series → s)
    if p.get('transient'):
        spec['time'] = {'t_end': _num(p, 't_end', label, 'el tiempo final', positive=True) * t_scale,
                        'n_steps': int(_num(p, 'time_steps', label, 'el número de pasos', default=50, positive=True)),
                        'scheme': p.get('scheme') or 'bdf2'}
        if p.get('n_output') not in (None, ''):
            spec['time']['n_output'] = int(_num(p, 'n_output', label, 'las salidas', positive=True))
    probes = []
    for i, pr in enumerate(p.get('probes') or []):
        try:
            probes.append({'label': pr.get('label') or f'P{i + 1}',
                           'point': [float(pr.get(k)) / 1000.0 for k in ('x', 'y', 'z')]})
        except (TypeError, ValueError):
            raise GraphSpecError(f'"{label}": punto de control {i + 1} con coordenadas inválidas (mm).')
    if probes:
        spec['probes'] = probes


def _finalize_physics(spec: dict) -> None:
    """Physics of the special material models (piezo, thermo-piezo, magnetic, fluid) and the checks that the
    conditions match the material."""
    if spec['material'].get('type') == 'piezoelectric':
        if 'thermal' in spec['physics']:
            raise GraphSpecError('Hay condiciones térmicas con un material piezoeléctrico: elija el modelo '
                                 '«Termo-piezoeléctrico» (α y coeficiente piroeléctrico p3).')
        spec['physics'] = ['piezoelectric']
    elif spec['material'].get('type') == 'thermopiezoelectric':
        if 'thermal' in spec['physics']:
            spec['physics'] = ['thermal', 'piezoelectric']
        else:                                     # no temperature field: ΔT = 0 → plain piezoelectric
            spec['material'] = {k: v for k, v in spec['material'].items()
                                if k not in ('p3', 'alpha', 'k', 'T_ref')}
            spec['material']['type'] = 'piezoelectric'
            spec['physics'] = ['piezoelectric']
    t_scale = spec.pop('transport_time_scale', 1.0)
    is_tr_bc = lambda b: 'concentration' in b                                         # noqa: E731
    is_tr_ld = lambda ld: any(k in ld for k in TRANSPORT_LOAD_TYPES)                  # noqa: E731
    if spec['material'].get('type') == 'scalar_transport':
        n_other = sum(not is_tr_bc(b) for b in spec['bcs']) + sum(not is_tr_ld(ld) for ld in spec['loads'])
        if n_other:
            raise GraphSpecError('El estudio de transporte solo admite BC «Concentración» y cargas de especie (flujo, '
                                 f'intercambio, fuente, vertido puntual): hay {n_other} condiciones de otro tipo.')
        n_sp = len(spec['material']['species'])
        for e in spec['bcs'] + spec['loads']:
            sp_ = e.get('species', 0)
            if not (isinstance(sp_, int) and 0 <= sp_ < n_sp):
                raise GraphSpecError(f'"{e.get("label")}": especie {sp_!r} inexistente (hay {n_sp}).')
            if t_scale != 1.0 and e.get('history'):
                e['history'] = [[t * t_scale, f] for t, f in e['history']]
        spec['physics'] = ['transport']
        return
    if any(is_tr_bc(b) for b in spec['bcs']) or any(is_tr_ld(ld) for ld in spec['loads']):
        raise GraphSpecError('Hay condiciones de transporte (concentración, vertidos) pero el material no es '
                             '«Transporte de contaminantes».')
    if spec['material'].get('type') != 'linear_magnetic' and (
            any('magnetic_potential' in b for b in spec['bcs']) or any('magnetic_flux' in ld for ld in spec['loads'])):
        raise GraphSpecError('Hay condiciones magnéticas pero el material no es magnético (μr, Br).')
    if spec['material'].get('type') == 'linear_magnetic':
        n_mech = (sum('magnetic_potential' not in b for b in spec['bcs'])
                  + sum('magnetic_flux' not in ld for ld in spec['loads']))
        if n_mech:
            raise GraphSpecError('El material magnético solo admite BC de potencial magnético y cargas de flujo '
                                 f'magnético ({n_mech} condiciones mecánicas o térmicas en el estudio).')
        if any('coil' in b for b in spec['bcs']) and all('coil' in b for b in spec['bcs']):
            raise GraphSpecError('La bobina necesita una cara de referencia: añada una BC «Potencial magnético» '
                                 '(ψ = 0) en la otra cara del corte del núcleo.')
        spec['physics'] = ['magnetic']
    elif spec['material'].get('type') == 'newtonian_fluid':
        if 'thermal' in spec['physics']:
            raise GraphSpecError('El fluido newtoniano no admite condiciones térmicas todavía.')
        if any('voltage' in b for b in spec['bcs']) or any('surface_charge' in ld for ld in spec['loads']):
            raise GraphSpecError('Hay electrodos o cargas eléctricas pero el material es un fluido.')
        spec['physics'] = ['fluid']               # T10 required: the kernel raises a clear error for T4
    elif spec['material'].get('type') not in PIEZO_TYPES and (
            any('voltage' in b for b in spec['bcs']) or any('surface_charge' in ld for ld in spec['loads'])):
        raise GraphSpecError('Hay electrodos o cargas eléctricas pero el material no es piezoeléctrico.')


ORTHO_KEYS = ('E1', 'E2', 'E3', 'G12', 'G13', 'G23', 'nu12', 'nu13', 'nu23')


def _axis(props: dict, key: str):
    v = props.get(key)
    if v in (None, '', []):
        return None
    try:
        out = [float(x) for x in v]
    except (TypeError, ValueError):
        out = []
    if len(out) != 3:
        raise GraphSpecError(f'{key} debe ser un vector de 3 componentes')
    return out


def _orthotropic_material(spec: dict, node) -> None:
    """Orthotropic elasticity: E1..E3, G12/G13/G23 [Pa], ν12/ν13/ν23 along the material axes
    ``axis_1``/``axis_2`` (global/CAD frame; omitted = global axes). Replaces the isotropic E/ν."""
    from app.design.services.fem.constitutive import LinearElasticOrthotropic
    p = node.properties or {}
    missing = [k for k in ORTHO_KEYS if p.get(k) in (None, '')]
    if missing:
        raise GraphSpecError(f'"{node.label}": material ortótropo sin {", ".join(missing)}.')
    m = {'type': 'linear_elastic_orthotropic', **{k: float(p[k]) for k in ORTHO_KEYS},
         'rho': spec['material']['rho']}
    for key in ('axis_1', 'axis_2'):
        a = _axis(p, key)
        if a is not None:
            m[key] = a
    try:
        LinearElasticOrthotropic.from_dict(m)
    except ValueError as e:
        raise GraphSpecError(f'"{node.label}": {e}')
    spec['material'] = m


def _piezo_material(spec: dict, node) -> None:
    """Piezoelectric (6mm, poling = material axis 3): c11 c12 c13 c33 c44 c66 [Pa], e31 e33 e15 [C/m²],
    eps11 eps33 (relative, constant strain), optional axis_1/axis_2. Replaces the isotropic E/ν."""
    from app.design.services.fem.piezo import KEYS, PiezoMaterial
    p = node.properties or {}
    missing = [k for k in KEYS if p.get(k) in (None, '')]
    if missing:
        raise GraphSpecError(f'"{node.label}": material piezoeléctrico sin {", ".join(missing)}.')
    m = {'type': spec['material']['type'], **{k: float(p[k]) for k in KEYS}, 'rho': spec['material']['rho']}
    for key in ('axis_1', 'axis_2'):
        a = _axis(p, key)
        if a is not None:
            m[key] = a
    if m['type'] == 'thermopiezoelectric':        # pyroelectric p3 [C/(m²·K)]; α, k, T_ref in _set_physics
        if p.get('p3') in (None, ''):
            raise GraphSpecError(f'"{node.label}": el material termo-piezoeléctrico necesita el coeficiente '
                                 'piroeléctrico p3 (C/m²·K).')
        m['p3'] = float(p['p3'])
    try:
        PiezoMaterial(m)
    except ValueError as e:
        raise GraphSpecError(f'"{node.label}": {e}')
    spec['material'] = m


def _viscoelastic_material(spec: dict, node) -> None:
    """Generalized Maxwell: E = instantaneous modulus E₀, ``prony_terms`` [{g, tau [s]}], time settings
    ``t_end`` [s], ``time_steps`` and ``load_history``: creep (load applied at t = 0 and held; with prescribed
    displacements: relaxation), ramp (linear to full load at ``t_ramp`` then held), recovery (load removed at
    ``t_unload``)."""
    from app.design.services.fem.viscoelastic import PronySeries
    p = node.properties or {}
    terms = []
    for t in p.get('prony_terms') or []:
        try:
            g, tau = float(t.get('g')), float(t.get('tau'))
        except (TypeError, ValueError, AttributeError):
            continue
        terms.append({'g': g, 'tau': tau})
    try:
        pr = PronySeries(spec['material']['E'], spec['material']['nu'], terms)
    except ValueError as e:
        raise GraphSpecError(f'"{node.label}": {e}')
    spec['material']['prony'] = terms
    t_end = float(p.get('t_end') or 10 * float(pr.tau.max()))
    kind = p.get('load_history') or 'creep'
    if kind == 'ramp':
        tr = float(p.get('t_ramp') or 0.1 * t_end)
        history = [[0.0, 0.0], [min(tr, t_end), 1.0], [t_end, 1.0]]
    elif kind == 'recovery':
        tu = float(p.get('t_unload') or 0.5 * t_end)
        if not 0 < tu < t_end:
            raise GraphSpecError(f'"{node.label}": t_unload debe estar entre 0 y t_end.')
        history = [[0.0, 1.0], [tu, 1.0], [tu, 0.0], [t_end, 0.0]]
    else:
        history = [[0.0, 1.0], [t_end, 1.0]]
    spec['time'] = {'t_end': t_end, 'n_steps': int(p.get('time_steps') or 40), 'history': history,
                    'load_history': kind}


def _anisotropic_thermal(props: dict, base: str, label: str):
    """[v1, v2, v3] when the node gives ``<base>1..3`` (orthotropic materials), else None."""
    vals = [props.get(f'{base}{i}') for i in (1, 2, 3)]
    if all(v in (None, '') for v in vals):
        return None
    if any(v in (None, '') for v in vals):
        raise GraphSpecError(f'"{label}": da {base}1, {base}2 y {base}3 (o ninguno).')
    return [float(v) for v in vals]


def _plastic_material(spec: dict, node) -> None:
    """J2 plasticity (FASE 2.5): σy and the hardening law from the MATERIAL node. ``hardening_type``
    perfect | linear (H) | voce (hardening_Q, hardening_b, H) | fit (``hardening_table`` written by the
    tensile-test fit of the material library); default: fit if a table exists, else linear/perfect."""
    p = node.properties or {}
    sy = p.get('yield_strength')
    if sy in (None, '') or float(sy) <= 0:
        raise GraphSpecError(f'"{node.label}": el modelo elastoplástico necesita el límite elástico σy.')
    kind = p.get('hardening_type') or ('fit' if p.get('hardening_table') else 'linear' if p.get('H') else 'perfect')
    if kind == 'fit':
        t = p.get('hardening_table')
        if not t:
            raise GraphSpecError(f'"{node.label}": no hay curva de endurecimiento ajustada; ajusta un ensayo '
                                 'de tracción en la biblioteca o elige endurecimiento lineal/Voce.')
        hard = {'type': 'table', 'ep': t['ep'], 'sy': t['sy']}
    elif kind == 'linear':
        hard = {'type': 'linear', 'H': float(p.get('H') or 0.0)}
    elif kind == 'voce':
        hard = {'type': 'voce', 'Q': float(p.get('hardening_Q') or 0.0), 'b': float(p.get('hardening_b') or 0.0),
                'H': float(p.get('H') or 0.0)}
    elif kind == 'perfect':
        hard = {'type': 'perfect'}
    else:
        raise GraphSpecError(f'"{node.label}": endurecimiento "{kind}" no reconocido.')
    spec['material']['sigma_y'] = float(sy) if kind != 'fit' else float(hard['sy'][0])
    spec['material']['hardening'] = hard
    spec['n_load_steps'] = int(p.get('load_steps') or 10)
    if p.get('unload'):
        spec['load_path'] = [1.0, 0.0]


def _set_physics(spec: dict, mat_node) -> None:
    """Physics inferred from the conditions (FASE 2 multiphysics): temperature BCs / heat loads →
    thermal; supports / mechanical loads → structural; both → one-way thermo-mechanical.
    Thermal material keys are only added when thermal is active (structural hashes unchanged)."""
    from app.design.services.fem.thermal import is_thermal_bc, is_thermal_load
    thermal = any(is_thermal_bc(b) for b in spec['bcs']) or any(is_thermal_load(ld) for ld in spec['loads'])
    structural = (any(not is_thermal_bc(b) for b in spec['bcs'])
                  or any(not is_thermal_load(ld) for ld in spec['loads']))
    if not thermal:
        return
    spec['physics'] = ['structural', 'thermal'] if structural else ['thermal']
    props = (mat_node.properties or {}) if mat_node is not None else {}
    label = mat_node.label if mat_node is not None else 'MATERIAL'
    ortho = spec['material'].get('type') in ('linear_elastic_orthotropic', 'thermopiezoelectric')
    if ortho and not structural:                 # thermal only: elastic constants are not needed
        for key in ('axis_1', 'axis_2'):
            a = _axis(props, key)
            if a is not None:
                spec['material'][key] = a
    k3 = _anisotropic_thermal(props, 'k', label) if ortho else None
    if k3 is not None:
        if min(k3) <= 0:
            raise GraphSpecError(f'"{label}": las conductividades k1, k2, k3 deben ser positivas.')
        spec['material']['k'] = k3
    else:
        k = props.get('k')
        if k in (None, '') or float(k) <= 0:
            raise GraphSpecError(f'"{label}": el análisis térmico necesita la conductividad k (W/m·K).')
        spec['material']['k'] = float(k)
    if structural:
        a3 = _anisotropic_thermal(props, 'alpha', label) if ortho else None
        a = props.get('alpha')
        if a3 is None and a in (None, ''):
            raise GraphSpecError(f'"{label}": el análisis termo-mecánico necesita el coeficiente de '
                                 'dilatación α (1/K).')
        spec['material']['alpha'] = a3 if a3 is not None else float(a)
        spec['material']['T_ref'] = float(props.get('T_ref') if props.get('T_ref') not in (None, '') else 20.0)


def _faces(ctx: dict, node: DesignNode) -> list | None:
    """face_set names for a node's ``entity_ids`` on the study geometry, or None."""
    ids = (node.properties or {}).get('entity_ids') or []
    if not ids:
        return None
    if not ctx.get('geometry_id'):
        raise GraphSpecError(f'"{node.label}" tiene caras seleccionadas pero el nodo GEOMETRY no '
                             'tiene una geometría CAD asignada.')
    from app.geometry.resolve import resolve_faces
    res = resolve_faces(ctx['geometry_id'], ids)
    bad = [i for i, r in res.items() if r['index'] is None]
    if bad:
        raise GraphSpecError(f'"{node.label}": {len(bad)} de {len(ids)} caras no existen en la versión '
                             'actual de la geometría. Vuelve a seleccionarlas.')
    return [f"F_{r['index']}" for r in res.values()]


def _symmetry_dofs(ctx: dict, node: DesignNode) -> list:
    """Normal DOF of planar, axis-aligned faces (symmetry BC without MPCs)."""
    from app.extensions import db
    from app.geometry.models import GeometryEntity
    from app.geometry.resolve import resolve_faces
    ids = (node.properties or {}).get('entity_ids') or []
    if not ids or not ctx.get('geometry_id'):
        raise GraphSpecError(f'"{node.label}": la simetría necesita caras planas seleccionadas.')
    axes = set()
    for r in resolve_faces(ctx['geometry_id'], ids).values():
        e = db.session.get(GeometryEntity, r['entity_id']) if r['entity_id'] else None
        n = (e.normal if e is not None else None) or []
        if e is None or e.surface_type != 'plane' or len(n) != 3:
            raise GraphSpecError(f'"{node.label}": la simetría solo admite caras planas.')
        k = max(range(3), key=lambda i: abs(n[i]))
        if abs(abs(n[k]) - 1.0) > 1e-6:
            raise GraphSpecError(f'"{node.label}": la cara de simetría debe ser normal a X, Y o Z '
                                 '(planos inclinados requieren restricciones MPC, aún no soportadas).')
        axes.add(k)
    return sorted(axes)


def _bc_node_to_entry(ctx: dict, node: DesignNode, geometry_id: str = None) -> dict:
    """Convert BC node to solver BC entry."""
    props = node.properties or {}
    faces = _faces(ctx, node)
    bc_type = props.get('bc_type', 'fixed')
    if bc_type == 'voltage':                      # electrode (piezoelectric)
        v = props.get('voltage', props.get('value'))
        if v in (None, ''):
            raise GraphSpecError(f'"{node.label}": falta el potencial del electrodo (V).')
        entry = {'voltage': float(v), 'label': node.label}
        _target(entry, faces, props, 'z0', face=True)
        if geometry_id:
            entry['geometry_id'] = geometry_id
        return entry
    if bc_type == 'temperature':
        t = props.get('temperature', props.get('value'))
        if t in (None, ''):
            raise GraphSpecError(f'"{node.label}": falta la temperatura impuesta (°C).')
        entry = {'temperature': float(t), 'label': node.label}
        _target(entry, faces, props, 'fixed')
        if geometry_id:
            entry['geometry_id'] = geometry_id
        return entry
    if bc_type == 'coil':                         # coil MMF: ψ = N·I on its pole faces (vs the reference poles)
        try:
            turns, current = float(props.get('turns')), float(props.get('current'))
        except (TypeError, ValueError):
            raise GraphSpecError(f'"{node.label}": la bobina necesita número de vueltas N y corriente I (A).')
        if turns <= 0:
            raise GraphSpecError(f'"{node.label}": el número de vueltas debe ser > 0.')
        coil = {'turns': turns, 'current': current}
        if props.get('current_steps') not in (None, ''):
            coil['steps'] = max(1, min(int(props['current_steps']), 50))
        entry = {'magnetic_potential': turns * current, 'coil': coil, 'label': node.label}
        _target(entry, faces, props, 'tip', face=True)
        if geometry_id:
            entry['geometry_id'] = geometry_id
        return entry
    if bc_type == 'magnetic_potential':           # equipotential pole face (ideal iron), ψ in A·turn
        v = props.get('magnetic_potential', props.get('value'))
        if v in (None, ''):
            raise GraphSpecError(f'"{node.label}": falta el potencial magnético (A).')
        entry = {'magnetic_potential': float(v), 'label': node.label}
        _target(entry, faces, props, 'fixed', face=True)
        if geometry_id:
            entry['geometry_id'] = geometry_id
        return entry
    if bc_type == 'concentration':                # species transport: fixed concentration (inlet, source face)
        entry = {'concentration': _num(props, 'concentration', node.label, 'la concentración impuesta'),
                 'species': int(props.get('species') or 0), 'label': node.label}
        hist = _history(props, node.label)
        if hist:
            entry['history'] = hist
        _target(entry, faces, props, 'fixed', face=True)
        if geometry_id:
            entry['geometry_id'] = geometry_id
        return entry
    if bc_type == 'velocity':                     # fluid inlet / moving wall [m/s or mm/s]
        f = {'m/s': 1.0, 'mm/s': 1e-3}.get(props.get('unit') or 'm/s', 1.0)
        values = [float(props.get(k) or 0) * f for k in ('vx', 'vy', 'vz')]
        entry = {'dofs': [0, 1, 2], 'values': values, 'label': node.label}
        _target(entry, faces, props, 'fixed')
        if geometry_id:
            entry['geometry_id'] = geometry_id
        return entry
    if props.get('dofs'):
        dofs = sorted({int(d) for d in props['dofs'] if int(d) in (0, 1, 2)})
        if not dofs:
            raise GraphSpecError(f'"{node.label}": los sólidos solo tienen grados de libertad de '
                                 'traslación (UX, UY, UZ); RX/RY/RZ no aplican.')
    elif bc_type == 'symmetry':
        dofs = _symmetry_dofs(ctx, node)
    else:
        dofs = BC_TYPE_DOFS.get(bc_type, [0, 1, 2])
    values = [float(props.get('value', 0) or 0)] * len(dofs)

    entry = {'dofs': dofs, 'values': values, 'label': node.label}
    # topology optimization keeps support regions solid, but not symmetry/plane constraints
    if bc_type == 'symmetry':
        entry['symmetry'] = True
    elif props.get('keep_solid') is False:
        entry['keep_solid'] = False
    _target(entry, faces, props, 'fixed')       # CAD faces > face_set > node_set (default 'fixed')
    if geometry_id:
        entry['geometry_id'] = geometry_id
    return entry


def _target(entry: dict, faces, props: dict, default: str, face: bool = False) -> None:
    """Selected CAD faces, else the node's ``face_set`` / ``node_set`` (parametric beam:
    'fixed', 'tip', '@free' = rest of the surface)."""
    if faces:
        entry['face_set'] = faces
    elif face or props.get('face_set'):
        entry['face_set'] = props.get('face_set') or default
    else:
        entry['node_set'] = props.get('node_set', default)


def _unit(table: dict, unit: str, node: DesignNode, default: str) -> float:
    u = (unit or default).strip()
    if u not in table:
        raise GraphSpecError(f'"{node.label}": unidad "{u}" no reconocida '
                             f'(usa {", ".join(table)}).')
    return table[u]


def _load_node_to_entry(ctx: dict, node: DesignNode, geometry_id: str = None) -> dict:
    """Convert LOAD node to solver LOAD entry (SI units)."""
    props = node.properties or {}
    load_type = props.get('load_type', 'force')
    mag = float(props.get('magnitude', 0) or 0)
    # defaults match NodePanel (Dz = -1)
    dx = float(props.get('dir_x', 0) or 0)
    dy = float(props.get('dir_y', 0) or 0)
    dz = float(props.get('dir_z', -1) if props.get('dir_z') is not None else -1)
    norm = math.sqrt(dx * dx + dy * dy + dz * dz)
    if norm > 1e-12:
        dx, dy, dz = dx / norm, dy / norm, dz / norm

    entry = {'label': node.label}
    if load_type in THERMAL_LOAD_TYPES:
        faces = _faces(ctx, node)
        if load_type == 'heat_source':
            entry['heat_source'] = mag * _unit(SOURCE_UNITS, props.get('unit'), node, 'W/m³')
            return entry
        if load_type == 'heat_flux':
            entry['heat_flux'] = mag * _unit(FLUX_UNITS, props.get('unit'), node, 'W/m²')
            _target(entry, faces, props, 'tip', face=True)
        else:   # convection
            h = props.get('h')
            if h in (None, '') or float(h) <= 0:
                raise GraphSpecError(f'"{node.label}": la convección necesita h > 0 (W/m²·K).')
            entry['convection'] = {'h': float(h), 'T_inf': float(props.get('T_inf') or 0.0)}
            _target(entry, faces, props, '@free', face=True)
        if geometry_id:
            entry['geometry_id'] = geometry_id
        return entry
    if load_type == 'surface_charge':             # free charge density on a face (piezoelectric)
        entry['surface_charge'] = mag * {'C/m²': 1.0, 'mC/m²': 1e-3, 'µC/m²': 1e-6}.get(props.get('unit') or 'C/m²', 1.0)
        _target(entry, _faces(ctx, node), props, 'z1', face=True)
        if geometry_id:
            entry['geometry_id'] = geometry_id
        return entry
    if load_type in TRANSPORT_LOAD_TYPES:         # species transport (units: concentration c, m, s)
        entry['species'] = int(props.get('species') or 0)
        hist = _history(props, node.label)
        if hist:
            entry['history'] = hist
        if load_type == 'species_source':         # uniform volumetric source [c/s]
            entry['species_source'] = mag
            return entry
        if load_type == 'point_source':           # discharge [c·m³/s] (mg/L → g/s) at a point given in mm
            try:
                pt = [float(props.get(k)) / 1000.0 for k in ('x', 'y', 'z')]
            except (TypeError, ValueError):
                raise GraphSpecError(f'"{node.label}": el vertido puntual necesita el punto x, y, z (mm).')
            entry['point_source'] = {'point': pt, 'rate': mag}
            return entry
        faces = _faces(ctx, node)
        if load_type == 'species_flux':           # [c·m/s] into the body
            entry['species_flux'] = mag
            _target(entry, faces, props, 'tip', face=True)
        else:                                      # exchange k (c_ext − c) with the atmosphere / bed
            entry['exchange'] = {'k': _num(props, 'k', node.label, 'el coeficiente de intercambio k (m/s)',
                                           nonneg=True),
                                 'c_ext': _num(props, 'c_ext', node.label, 'la concentración exterior', default=0.0)}
            _target(entry, faces, props, '@free', face=True)
        if geometry_id:
            entry['geometry_id'] = geometry_id
        return entry
    if load_type == 'magnetic_flux':              # normal flux density entering the face [T]
        entry['magnetic_flux'] = mag * {'T': 1.0, 'mT': 1e-3}.get(props.get('unit') or 'T', 1.0)
        _target(entry, _faces(ctx, node), props, 'tip', face=True)
        if geometry_id:
            entry['geometry_id'] = geometry_id
        return entry
    if load_type == 'gravity':
        g = mag * _unit(ACCEL_UNITS, props.get('unit'), node, 'm/s²') if mag else 9.80665
        entry['gravity'] = [g * dx, g * dy, g * dz]
        return entry
    if load_type not in ('force', 'pressure'):
        raise GraphSpecError(f'"{node.label}": el tipo de carga "{load_type}" aún no está soportado '
                             '(disponibles: force, pressure, gravity, heat_flux, convection, heat_source, '
                             'species_flux, exchange, species_source, point_source).')

    faces = _faces(ctx, node)
    if load_type == 'pressure':
        if not faces and not props.get('face_set'):
            raise GraphSpecError(f'"{node.label}": la presión necesita caras seleccionadas.')
        entry['face_set'] = faces or props['face_set']      # parametric beam: named face set
        entry['pressure'] = mag * _unit(PRESSURE_UNITS, props.get('unit'), node, 'Pa')
    else:
        f = mag * _unit(FORCE_UNITS, props.get('unit'), node, 'N')
        entry['force'] = [f * dx, f * dy, f * dz]
        if faces:
            entry['face_set'] = faces
        else:
            entry['node_set'] = props.get('node_set', 'tip')
    if geometry_id:
        entry['geometry_id'] = geometry_id
    return entry
