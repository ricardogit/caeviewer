"""Minimal glTF 2.0 binary (GLB) writer for a single triangle mesh with a face-ID attribute.

No OCC / trimesh dependency. The mesh carries the custom vertex attribute
``_FACE_ID`` (FLOAT, SCALAR): the 1-based CAD face index (TopExp order) each
vertex belongs to. Vertices are never shared between CAD faces, so a picked
triangle's vertex gives its face unambiguously.

Why not Draco: Draco re-orders triangles/vertices on encode; keeping the file
uncompressed guarantees the attribute is read exactly as written. (Three.js
GLTFLoader exposes it as ``geometry.attributes._face_id`` — lower-cased.)
FLOAT is used because glTF forbids UNSIGNED_INT for vertex attributes; float32
represents integers exactly up to 2**24 faces.
"""
import json
import struct

import numpy as np

_FLOAT, _UINT = 5126, 5125
_ARRAY_BUFFER, _ELEMENT_ARRAY_BUFFER = 34962, 34963


def _pad4(b: bytes, fill: bytes = b'\x00') -> bytes:
    return b + fill * ((4 - len(b) % 4) % 4)


def write_glb(path, positions, normals, face_ids, indices, *, extras=None, color=(0.62, 0.66, 0.72)) -> dict:
    """Write the mesh to ``path``. Arrays: positions/normals (N,3) float, face_ids (N,), indices (M,3).

    Returns {'n_vertices', 'n_triangles', 'bytes'}.
    """
    pos = np.ascontiguousarray(positions, dtype='<f4').reshape(-1, 3)
    nrm = np.ascontiguousarray(normals, dtype='<f4').reshape(-1, 3)
    fid = np.ascontiguousarray(face_ids, dtype='<f4').reshape(-1)
    idx = np.ascontiguousarray(indices, dtype='<u4').reshape(-1)
    n = len(pos)
    if not (len(nrm) == len(fid) == n):
        raise ValueError('positions, normals and face_ids must have the same length')
    if n == 0 or len(idx) == 0:
        raise ValueError('empty mesh')
    if idx.max() >= n:
        raise ValueError('index out of range')

    views, accessors, blob = [], [], b''

    def add(data: np.ndarray, target, comp, typ, count, minmax=False):
        nonlocal blob
        offset = len(blob)
        raw = data.tobytes()
        blob += _pad4(raw)
        views.append({'buffer': 0, 'byteOffset': offset, 'byteLength': len(raw), 'target': target})
        acc = {'bufferView': len(views) - 1, 'componentType': comp, 'count': count, 'type': typ}
        if minmax:
            acc['min'] = data.reshape(count, -1).min(axis=0).tolist()
            acc['max'] = data.reshape(count, -1).max(axis=0).tolist()
        accessors.append(acc)
        return len(accessors) - 1

    a_pos = add(pos, _ARRAY_BUFFER, _FLOAT, 'VEC3', n, minmax=True)
    a_nrm = add(nrm, _ARRAY_BUFFER, _FLOAT, 'VEC3', n)
    a_fid = add(fid, _ARRAY_BUFFER, _FLOAT, 'SCALAR', n, minmax=True)
    a_idx = add(idx, _ELEMENT_ARRAY_BUFFER, _UINT, 'SCALAR', len(idx))

    gltf = {
        'asset': {'version': '2.0', 'generator': 'cae-viewer app.geometry.glb'},
        'scene': 0,
        'scenes': [{'nodes': [0]}],
        'nodes': [{'mesh': 0, 'name': 'geometry'}],
        'meshes': [{
            'name': 'geometry',
            'primitives': [{
                'attributes': {'POSITION': a_pos, 'NORMAL': a_nrm, '_FACE_ID': a_fid},
                'indices': a_idx, 'material': 0, 'mode': 4,
            }],
            'extras': extras or {},
        }],
        'materials': [{
            'name': 'cad',
            'doubleSided': True,
            'pbrMetallicRoughness': {'baseColorFactor': [*color, 1.0], 'metallicFactor': 0.1,
                                     'roughnessFactor': 0.6},
        }],
        'buffers': [{'byteLength': len(blob)}],
        'bufferViews': views,
        'accessors': accessors,
    }
    js = _pad4(json.dumps(gltf, separators=(',', ':')).encode(), b' ')
    total = 12 + 8 + len(js) + 8 + len(blob)
    with open(path, 'wb') as f:
        f.write(struct.pack('<4sII', b'glTF', 2, total))
        f.write(struct.pack('<I4s', len(js), b'JSON'))
        f.write(js)
        f.write(struct.pack('<I4s', len(blob), b'BIN\x00'))
        f.write(blob)
    return {'n_vertices': n, 'n_triangles': len(idx) // 3, 'bytes': total}


def read_glb(path) -> tuple[dict, bytes]:
    """(json, bin) — for tests and debugging."""
    with open(path, 'rb') as f:
        data = f.read()
    magic, version, length = struct.unpack_from('<4sII', data, 0)
    assert magic == b'glTF' and version == 2 and length == len(data)
    jlen, jtype = struct.unpack_from('<I4s', data, 12)
    js = json.loads(data[20:20 + jlen])
    blen, btype = struct.unpack_from('<I4s', data, 20 + jlen)
    return js, data[28 + jlen:28 + jlen + blen]


def accessor_array(gltf: dict, binary: bytes, accessor: int) -> np.ndarray:
    acc = gltf['accessors'][accessor]
    view = gltf['bufferViews'][acc['bufferView']]
    dtype = {'5126': '<f4', '5125': '<u4'}[str(acc['componentType'])]
    width = {'SCALAR': 1, 'VEC3': 3}[acc['type']]
    arr = np.frombuffer(binary, dtype=dtype, count=acc['count'] * width, offset=view['byteOffset'])
    return arr.reshape(acc['count'], width) if width > 1 else arr
