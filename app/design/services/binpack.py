"""Binary array pack shared by the ROM (FASE 5) and uncertainty (FASE 6) surface endpoints.

Layout: uint32 header length, UTF-8 JSON header, zero padding to 4 bytes, then the arrays listed
in header['arrays'] ({name, dtype, shape, offset}) relative to the data start. Parsed in the
browser by frontend/src/utils/romPack.js (parsePack).
"""
import json
import struct

import numpy as np


def pack_arrays(header: dict, arrays: list) -> bytes:
    meta, blobs, off = [], [], 0
    for name, a in arrays:
        a = np.ascontiguousarray(a)
        meta.append({'name': name, 'dtype': str(a.dtype), 'shape': list(a.shape), 'offset': off})
        blobs.append(a.tobytes())
        off += a.nbytes
    head = json.dumps({**header, 'arrays': meta}).encode()
    pad = (-(4 + len(head))) % 4
    return struct.pack('<I', len(head)) + head + b'\0' * pad + b''.join(blobs)
