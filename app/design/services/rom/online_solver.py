"""ROM online solver — evaluate a built ROM in real time (FASE 5, target < 100 ms).

ROMs are loaded once per process into an LRU cache (``rom_id`` = SimulationRun id); each
evaluation is an r×r solve plus reconstructions (whole-volume max von Mises from the element
strain modes, max displacement, residual of the full equations as error indicator).
"""
from __future__ import annotations

import json
import logging
import threading
import time
from collections import OrderedDict

import numpy as np

from app.design.services.rom.pod import evaluate_arrays

logger = logging.getLogger(__name__)

CACHE_SIZE = 4


class ROMOnlineSolver:
    """Process-wide cache of loaded ROMs."""

    def __init__(self, capacity: int = CACHE_SIZE):
        self._rom_cache: OrderedDict = OrderedDict()
        self._lock = threading.Lock()
        self.capacity = capacity

    def load_rom(self, rom_id: str, rom_path: str) -> dict:
        with self._lock:
            if rom_id in self._rom_cache:
                self._rom_cache.move_to_end(rom_id)
                return self._rom_cache[rom_id]
        t0 = time.perf_counter()
        with np.load(rom_path, allow_pickle=False) as z:
            rom = {k: z[k] for k in z.files}
        rom['params'] = json.loads(str(rom['params_json']))
        rom['space'] = json.loads(str(rom['space_json']))
        rom['meta'] = json.loads(str(rom['meta_json'])) if 'meta_json' in rom else {}
        logger.info('ROM %s loaded in %.2fs (r=%s)', rom_id, time.perf_counter() - t0, int(rom['r']))
        with self._lock:
            self._rom_cache[rom_id] = rom
            while len(self._rom_cache) > self.capacity:
                self._rom_cache.popitem(last=False)
        return rom

    def get(self, rom_id: str):
        with self._lock:
            return self._rom_cache.get(rom_id)

    def get_parameter_ranges(self, rom_id: str) -> dict:
        rom = self.get(rom_id)
        return dict(rom['space']) if rom else {}

    def evaluate(self, rom_id: str, params: dict) -> dict:
        t0 = time.perf_counter()
        rom = self.get(rom_id)
        if rom is None:
            raise KeyError(rom_id)
        q = {p['key']: float(params.get(p['key'], p['nominal'])) for p in rom['params']}
        within = all(lo - 1e-9 * abs(hi - lo) <= q[k] <= hi + 1e-9 * abs(hi - lo)
                     for k, (lo, hi) in rom['space'].items())
        ev = evaluate_arrays(rom, q)
        ms = (time.perf_counter() - t0) * 1000
        return {
            'coefficients': ev['ur'].tolist(),
            'lambda': ev['lambda'], 'mu': ev['mu'],
            'max_displacement_mm': ev['max_displacement_m'] * 1000,
            'max_von_mises_mpa': ev['max_von_mises_pa'] / 1e6,
            'residual': ev['residual'],
            'within_range': within,
            'error_estimate': rom['meta'].get('validation_max_error_u'),
            'params': q,
            'response_ms': round(ms, 3),
        }

    def unload_rom(self, rom_id: str):
        with self._lock:
            self._rom_cache.pop(rom_id, None)


_SOLVER = ROMOnlineSolver()


def online_solver() -> ROMOnlineSolver:
    return _SOLVER
