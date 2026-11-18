"""Forcings: tidal synthesis from harmonic constants and interpolation of time series (tide gauge, wind, river).

η(t) = Z0 + Σ_k A_k cos(ω_k t − g_k), ω in degrees per hour (Doodson / IHO speeds), t in seconds from the reference
time. Nodal corrections (f, u) are not applied: a few % in amplitude over the 18.6-year cycle; enough for scenario
studies, not for tide prediction tables.
"""
from __future__ import annotations

import numpy as np

# angular speeds [deg/h]
CONSTITUENTS = {
    'M2': 28.9841042, 'S2': 30.0000000, 'N2': 28.4397295, 'K2': 30.0821373,
    'K1': 15.0410686, 'O1': 13.9430356, 'P1': 14.9589314, 'Q1': 13.3986609,
    'M4': 57.9682084, 'MS4': 58.9841042, 'MN4': 57.4238337, 'M6': 86.9523127,
    'Mf': 1.0980331, 'Mm': 0.5443747, 'Ssa': 0.0821373, 'Sa': 0.0410686,
}


def period_s(name: str) -> float:
    return 360.0 / CONSTITUENTS[name] * 3600.0


def tide(t, constituents: list[dict], z0: float = 0.0) -> np.ndarray:
    """Free-surface elevation [m] at times t [s] from [{name, amplitude [m], phase [deg]}]."""
    t = np.asarray(t, float)
    eta = np.full(t.shape, float(z0))
    for c in constituents:
        w = np.radians(CONSTITUENTS[c['name']]) / 3600.0              # rad/s
        eta += float(c['amplitude']) * np.cos(w * t - np.radians(float(c['phase'])))
    return eta


def series_at(t, ts: np.ndarray, values: np.ndarray) -> np.ndarray:
    """Piecewise-linear interpolation of a series, constant outside its range."""
    return np.interp(np.asarray(t, float), np.asarray(ts, float), np.asarray(values, float))


def summary(d: dict) -> dict:
    """Small description for the dataset list (no arrays)."""
    if d['kind'] == 'harmonics':
        big = max(d['constituents'], key=lambda c: c['amplitude'])
        return {'kind': 'harmonics', 'n_constituents': len(d['constituents']), 'z0': d['z0'],
                'constituents': [c['name'] for c in d['constituents']], 'dominant': big['name'],
                'range_m': 2 * sum(c['amplitude'] for c in d['constituents'])}
    return {'kind': 'series', 'n': int(len(d['t'])), 'duration_s': float(d['t'][-1] - d['t'][0]), 't0': d.get('t0'),
            'columns': {k: {'min': float(np.nanmin(v)), 'max': float(np.nanmax(v))} for k, v in d['columns'].items()}}
