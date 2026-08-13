import numpy as np

from idea54.geometry import primitive_mesh, vertex_normals
from idea54.hashing import geometry_sha256


def test_all_primitives_have_valid_faces_and_normals():
    names = ["cube", "icosphere", "cylinder", "cone", "torus", "capsule", "rounded_box", "composite"]
    for name in names:
        vertices, faces = primitive_mesh(name)
        normals = vertex_normals(vertices, faces)
        assert vertices.shape[1] == faces.shape[1] == normals.shape[1] == 3
        assert faces.min() >= 0 and faces.max() < len(vertices)
        assert np.isfinite(normals).all()


def test_geometry_hash_is_dtype_canonical():
    vertices, faces = primitive_mesh("cube")
    normals = vertex_normals(vertices, faces)
    assert geometry_sha256(vertices, faces, normals) == geometry_sha256(vertices.astype(np.float64), faces.astype(np.int64), normals.astype(np.float64))
