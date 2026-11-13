"""Sensor data of structural tests and their simulated counterparts (FASE 8).

A structural test is a list of sensors on the part, each with a position [mm, CAD frame], a
quantity and the measured value at the test load:

  ux | uy | uz       displacement component [mm]            (LVDT, dial gauge, DIC point)
  umag               displacement magnitude [mm]
  strain             strain along the gauge direction (dx, dy, dz) [µε]   (strain gauge)

``MeshProbe`` locates each sensor in the tetrahedral mesh of a run (KD-tree over element
centroids, barycentric test on the vertex tet; outside points are projected on the closest
element and their distance reported) and interpolates the simulated field with the element
shape functions (T4/T10), so the comparison is at the sensor, not at the nearest node.
"""
from __future__ import annotations

import csv
import io
import re

import numpy as np
from scipy.spatial import cKDTree

from app.design.services.fem import tet_batch as tb

QUANTITIES = {
    'ux': ('Desplazamiento X', 'mm'), 'uy': ('Desplazamiento Y', 'mm'), 'uz': ('Desplazamiento Z', 'mm'),
    'umag': ('Desplazamiento |u|', 'mm'), 'strain': ('Deformación (galga)', 'µε'),
}
_ALIASES = {
    'ux': 'ux', 'dx': 'ux', 'u_x': 'ux', 'x': 'ux', 'uy': 'uy', 'u_y': 'uy', 'y': 'uy', 'uz': 'uz', 'u_z': 'uz',
    'z': 'uz', 'umag': 'umag', '|u|': 'umag', 'u': 'umag', 'mag': 'umag', 'magnitude': 'umag',
    'strain': 'strain', 'galga': 'strain', 'gauge': 'strain', 'sg': 'strain', 'eps': 'strain',
    'deformacion': 'strain', 'deformación': 'strain', 'ε': 'strain',
}


class SensorError(ValueError):
    """User-facing problem with the sensor file."""


def parse_sensor_csv(text: str) -> list[dict]:
    """CSV with a header. Columns (English/Spanish, case-insensitive):
    label|sensor|nombre, x, y, z [mm], quantity|tipo|magnitud (ux, uy, uz, umag, strain),
    value|medido|measured, optional std|incertidumbre, optional dx, dy, dz (gauge direction).
    Displacements in mm (header "[m]" → m), strains in µε (header "mm/mm" or "[-]" → absolute)."""
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if len(lines) < 2:
        raise SensorError('El archivo de sensores necesita encabezado y al menos una fila.')
    try:
        delim = csv.Sniffer().sniff('\n'.join(lines[:20]), delimiters=',;\t').delimiter
    except csv.Error:
        delim = ';' if lines[0].count(';') > lines[0].count(',') else ','
    comma = delim != ',' and bool(re.search(r'\d,\d', '\n'.join(lines[1:20])))
    rows = list(csv.reader(lines, delimiter=delim))
    head = [h.strip().lower() for h in rows[0]]

    def col(*keys, required=True):
        for i, h in enumerate(head):
            name = re.split(r'[\s\[(]', h)[0]
            if name in keys:
                return i
        if required:
            raise SensorError(f"Falta la columna {keys[0]} (encabezados: {', '.join(rows[0])})")
        return None

    ix, iy, iz = col('x'), col('y'), col('z')
    iq = col('quantity', 'tipo', 'magnitud', 'component', 'componente', 'type')
    iv = col('value', 'medido', 'measured', 'valor', 'medida')
    il = col('label', 'sensor', 'nombre', 'name', 'id', required=False)
    isd = col('std', 'incertidumbre', 'sigma', 'uncertainty', required=False)
    idir = [col(k, required=False) for k in ('dx', 'dy', 'dz')]
    v_head = head[iv]
    disp_scale = 1000.0 if re.search(r'\[\s*m\s*\]|\(\s*m\s*\)', v_head) else 1.0      # → mm
    strain_scale = 1e6 if re.search(r'mm/mm|\[-\]|\(-\)|m/m', v_head) else 1.0       # → µε

    def num(s):
        s = s.strip()
        return float(s.replace(',', '.') if comma else s)

    sensors = []
    for k, r in enumerate(rows[1:], start=1):
        if not any(c.strip() for c in r):
            continue
        try:
            q_raw = r[iq].strip().lower()
            q = _ALIASES.get(q_raw)
            if q is None:
                raise SensorError(f"Fila {k}: magnitud '{r[iq]}' desconocida (usa ux, uy, uz, umag o strain)")
            s = {'label': (r[il].strip() if il is not None else '') or f'S{k}',
                 'x': num(r[ix]), 'y': num(r[iy]), 'z': num(r[iz]), 'quantity': q,
                 'value': num(r[iv]) * (strain_scale if q == 'strain' else disp_scale)}
            if isd is not None and r[isd].strip():
                s['std'] = abs(num(r[isd])) * (strain_scale if q == 'strain' else disp_scale)
            if q == 'strain':
                if any(i is None for i in idir):
                    raise SensorError(f'Fila {k}: una galga necesita su dirección dx, dy, dz.')
                d = np.array([num(r[i]) for i in idir])
                if np.linalg.norm(d) == 0:
                    raise SensorError(f'Fila {k}: dirección de galga nula.')
                s['direction'] = (d / np.linalg.norm(d)).tolist()
        except (IndexError, ValueError) as e:
            if isinstance(e, SensorError):
                raise
            raise SensorError(f'Fila {k} inválida: {e}') from None
        sensors.append(s)
    if not sensors:
        raise SensorError('Sin sensores.')
    return sensors


class MeshProbe:
    """Locate points in a tet mesh (nodes [m]) and interpolate nodal fields there."""

    def __init__(self, nodes: np.ndarray, elements: np.ndarray):
        self.nodes = np.asarray(nodes, float)
        self.elements = np.asarray(elements, np.int64)
        self.etype = tb.etype_of(self.elements)
        V = self.nodes[self.elements[:, :4]]                        # vertex tets
        self.V0 = V[:, 0]
        T = np.transpose(V[:, 1:] - V[:, :1], (0, 2, 1))           # (m, 3, 3) columns = edges
        self.Tinv = np.linalg.inv(T)
        self.tree = cKDTree(V.mean(axis=1))
        edges = np.linalg.norm(V[:, 1] - V[:, 0], axis=1)
        self.h = float(np.mean(edges))

    def locate(self, pts_m: np.ndarray, k: int = 24):
        """→ element (n,), natural coords (n, 3), distance to the mesh [m] (n,)."""
        pts = np.atleast_2d(np.asarray(pts_m, float))
        k = min(k, len(self.elements))
        _, cand = self.tree.query(pts, k=k)
        cand = np.atleast_2d(cand)
        el = np.empty(len(pts), np.int64)
        nat = np.empty((len(pts), 3))
        dist = np.empty(len(pts))
        for i, p in enumerate(pts):
            c = cand[i]
            xi = np.einsum('kij,kj->ki', self.Tinv[c], p - self.V0[c])       # (k, 3)
            L = np.column_stack([1 - xi.sum(1), xi])
            j = int(np.argmax(L.min(1)))
            if L[j].min() >= -1e-9:
                el[i], nat[i], dist[i] = c[j], xi[j], 0.0
                continue
            # outside every candidate: project on each candidate tet (clip + renormalize barycentrics,
            # an approximation of the closest point → the distance is an upper bound) → closest
            Lc = np.clip(L, 0, None)
            Lc /= Lc.sum(1, keepdims=True)
            V = self.nodes[self.elements[c, :4]]
            proj = np.einsum('kv,kvd->kd', Lc, V)
            d = np.linalg.norm(proj - p, axis=1)
            j = int(np.argmin(d))
            el[i], nat[i], dist[i] = c[j], Lc[j, 1:], d[j]
        return el, nat, dist

    def displacement(self, u_nodal: np.ndarray, el, nat) -> np.ndarray:
        """u (n_nodes, 3) → interpolated (n, 3)."""
        out = np.empty((len(el), 3))
        for i, (e, p) in enumerate(zip(el, nat)):
            N = tb.shape(self.etype, p)
            out[i] = N @ u_nodal[self.elements[e]]
        return out

    def strain(self, u_flat: np.ndarray, el, nat) -> np.ndarray:
        """Engineering strain (n, 6) [εxx εyy εzz γxy γyz γxz] at the points."""
        out = np.empty((len(el), 6))
        for i, (e, p) in enumerate(zip(el, nat)):
            out[i] = tb.strain_at(self.nodes, self.elements[[e]], u_flat, p)[0]
        return out


def gauge_strain(eps6: np.ndarray, d: np.ndarray) -> float:
    """Normal strain along unit direction d from engineering strain (γ = 2ε_ij)."""
    exx, eyy, ezz, gxy, gyz, gxz = eps6
    E = np.array([[exx, gxy / 2, gxz / 2], [gxy / 2, eyy, gyz / 2], [gxz / 2, gyz / 2, ezz]])
    return float(d @ E @ d)


def simulate_sensors(probe: MeshProbe, u_nodal: np.ndarray, sensors: list[dict], load_factor: float = 1.0) -> dict:
    """Simulated value of every sensor (same units as the measurement) + location diagnostics."""
    pts = np.array([[s['x'], s['y'], s['z']] for s in sensors]) / 1000.0
    el, nat, dist = probe.locate(pts)
    U = probe.displacement(u_nodal, el, nat) * 1000.0 * load_factor           # mm
    need_strain = [i for i, s in enumerate(sensors) if s['quantity'] == 'strain']
    eps = {}
    if need_strain:
        e6 = probe.strain(u_nodal.ravel(), el[need_strain], nat[need_strain])
        eps = dict(zip(need_strain, e6))
    sim = np.empty(len(sensors))
    for i, s in enumerate(sensors):
        q = s['quantity']
        if q == 'ux':
            sim[i] = U[i, 0]
        elif q == 'uy':
            sim[i] = U[i, 1]
        elif q == 'uz':
            sim[i] = U[i, 2]
        elif q == 'umag':
            sim[i] = np.linalg.norm(U[i])
        else:
            sim[i] = gauge_strain(eps[i], np.asarray(s['direction'])) * 1e6 * load_factor
    return {'simulated': sim, 'element': el, 'distance_mm': dist * 1000.0,
            'outside': (dist > 0.5 * probe.h), 'mesh_h_mm': probe.h * 1000.0}
