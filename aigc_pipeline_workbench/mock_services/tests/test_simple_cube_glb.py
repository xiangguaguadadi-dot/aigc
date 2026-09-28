import json
import struct
from importlib import resources

data = resources.files("mock_services.fixtures").joinpath("simple_cube.glb").read_bytes()
assert data[:4] == b'glTF'
version, length = struct.unpack_from('<II', data, 4)
assert version == 2 and length == len(data)
json_length, json_type = struct.unpack_from('<II', data, 12)
assert json_type == 0x4E4F534A
gltf = json.loads(data[20:20 + json_length])
offset = 20 + json_length
bin_length, bin_type = struct.unpack_from('<II', data, offset)
assert bin_type == 0x004E4942
assert bin_length == len(data) - offset - 8
print({'size': len(data), 'gltf_version': gltf['asset']['version'], 'nodes': len(gltf['nodes']), 'accessors': len(gltf['accessors']), 'bin_chunk': bin_length})
