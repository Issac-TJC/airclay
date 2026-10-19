"""Convert Elena FF's licensed GLB into the portable AirClay skinning asset.

Usage: .venv/bin/python scripts/prepare_hand_asset.py
Reads the vendored source; no network or Blender operators at runtime.
"""
import hashlib
import json
from pathlib import Path
import struct
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'assets/realistic_hand/source.glb'
OUTPUT = ROOT / 'blender_addon/airclay_blender/assets'


def prepare():
    raw = SOURCE.read_bytes()
    assert raw[:4] == b'glTF'
    length = struct.unpack_from('<I', raw, 12)[0]
    gltf = json.loads(raw[20:20 + length])
    binary = raw[28 + length:]

    def accessor(index):
        a = gltf['accessors'][index]
        view = gltf['bufferViews'][a['bufferView']]
        assert 'sparse' not in a
        columns = {'VEC2': 2, 'VEC3': 3, 'VEC4': 4, 'MAT4': 16, 'SCALAR': 1}[a['type']]
        dtype = {5126: '<f4', 5123: '<u2', 5125: '<u4', 5121: 'u1'}[a['componentType']]
        itemsize = np.dtype(dtype).itemsize
        return np.ndarray((a['count'], columns), dtype=dtype, buffer=binary,
                          offset=view.get('byteOffset', 0) + a.get('byteOffset', 0),
                          strides=(view.get('byteStride', columns * itemsize), itemsize)).copy()

    skin = gltf['skins'][0]
    primitive = gltf['meshes'][0]['primitives'][0]
    assert primitive['mode'] == 4
    attributes = primitive['attributes']
    bind = np.linalg.inv(accessor(skin['inverseBindMatrices']).reshape(-1, 4, 4).transpose(0, 2, 1))
    names = [gltf['nodes'][i]['name'] for i in skin['joints']]

    def bone(prefix):
        return next(i for i, name in enumerate(names) if name.startswith(prefix + '_'))

    wrist = bind[bone('hand.R'), :3, 3]
    points = [wrist]
    segments = [(-1, -1)]  # Palm transform, shared by wrist/hand weights.
    starts = [wrist]
    mapping = {bone('pulse.R'): 0, bone('hand.R'): 0}
    for finger in ('thumb', 'index', 'middle', 'ring', 'pinky'):
        first = len(points)
        ids = [bone(finger + '_0' + str(i) + '.R') for i in (1, 2, 3)]
        points.extend(bind[i, :3, 3] for i in ids)
        # Exporter end-marker inverse binds are identity; use its actual local
        # translation with the last deform bone's bind matrix, not that marker.
        last_node = gltf['nodes'][skin['joints'][ids[-1]]]
        end = gltf['nodes'][last_node['children'][0]]['translation']
        points.append((bind[ids[-1]] @ np.array([*end, 1]))[:3])
        mapping[bone(finger + '_base.R')] = len(segments)
        segments.append((0, first))
        starts.append(bind[bone(finger + '_base.R'), :3, 3])
        for offset, i in enumerate(ids):
            mapping[i] = len(segments)
            segments.append((first + offset, first + offset + 1))
            starts.append(bind[i, :3, 3])
    weights = accessor(attributes['WEIGHTS_0'])
    joints = accessor(attributes['JOINTS_0'])
    assert all(int(i) in mapping for i in joints[weights > 0])
    ids = np.array([[mapping.get(int(i), 0) for i in row] for row in joints], dtype=np.uint8)
    weights /= weights.sum(axis=1, keepdims=True)
    uv = accessor(attributes['TEXCOORD_0'])
    uv[:, 1] = 1 - uv[:, 1]  # glTF top-left to Blender bottom-left image origin.
    OUTPUT.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(OUTPUT / 'hand_mesh.npz', vertices=accessor(attributes['POSITION']),
                        triangles=accessor(primitive['indices']).reshape(-1, 3), uv=uv,
                        joints=ids, weights=weights, rest_points=np.asarray(points, dtype=np.float32),
                        rest_starts=np.asarray(starts, dtype=np.float32),
                        segments=np.asarray(segments, dtype=np.int16))
    for index, name in ((0, 'hand_basecolor.jpg'), (1, 'hand_roughness.png')):
        view = gltf['bufferViews'][gltf['images'][index]['bufferView']]
        offset = view.get('byteOffset', 0)
        (OUTPUT / name).write_bytes(binary[offset:offset + view['byteLength']])
    manifest = dict(gltf['asset']['extras'])
    manifest.update(download_url='https://raw.githubusercontent.com/bizzkoot/Hand-Math/main/assets/models/hand_right.glb',
                    source_sha256=hashlib.sha256(raw).hexdigest(),
                    changes='Extracted bind-space mesh, UV and textures; mapped deform weights to 21 tracked joints; mirrored left hand at runtime.',
                    asset_license='CC-BY-SA-4.0', vertices=len(ids), triangles=len(accessor(primitive['indices'])) // 3)
    manifest['files_sha256'] = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(OUTPUT.iterdir()) if p.name != 'hand_manifest.json'}
    (OUTPUT / 'hand_manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps(manifest, indent=2))


if __name__ == '__main__':
    prepare()
