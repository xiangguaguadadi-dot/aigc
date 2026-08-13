from __future__ import annotations

import numpy as np


def vertex_normals(vertices: np.ndarray, faces: np.ndarray) -> np.ndarray:
    normals = np.zeros_like(vertices, dtype=np.float64)
    triangles = vertices[faces]
    face_normals = np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0])
    for corner in range(3):
        np.add.at(normals, faces[:, corner], face_normals)
    lengths = np.linalg.norm(normals, axis=1, keepdims=True)
    return (normals / np.maximum(lengths, 1e-12)).astype(np.float32)


def cube_mesh() -> tuple[np.ndarray, np.ndarray]:
    vertices = np.array(
        [
            [-0.5, -0.5, -0.5], [0.5, -0.5, -0.5], [0.5, 0.5, -0.5], [-0.5, 0.5, -0.5],
            [-0.5, -0.5, 0.5], [0.5, -0.5, 0.5], [0.5, 0.5, 0.5], [-0.5, 0.5, 0.5],
        ],
        dtype=np.float32,
    )
    faces = np.array(
        [
            [0, 2, 1], [0, 3, 2], [4, 5, 6], [4, 6, 7], [0, 1, 5], [0, 5, 4],
            [2, 3, 7], [2, 7, 6], [1, 2, 6], [1, 6, 5], [3, 0, 4], [3, 4, 7],
        ],
        dtype=np.int32,
    )
    return vertices, faces


def uv_sphere(segments: int = 24, rings: int = 12) -> tuple[np.ndarray, np.ndarray]:
    vertices = []
    for ring in range(rings + 1):
        theta = np.pi * ring / rings
        for segment in range(segments):
            phi = 2 * np.pi * segment / segments
            vertices.append([0.5 * np.sin(theta) * np.cos(phi), 0.5 * np.cos(theta), 0.5 * np.sin(theta) * np.sin(phi)])
    faces = []
    for ring in range(rings):
        for segment in range(segments):
            nxt = (segment + 1) % segments
            a = ring * segments + segment
            b = ring * segments + nxt
            c = (ring + 1) * segments + segment
            d = (ring + 1) * segments + nxt
            if ring > 0:
                faces.append([a, c, b])
            if ring < rings - 1:
                faces.append([b, c, d])
    return np.asarray(vertices, np.float32), np.asarray(faces, np.int32)


def primitive_mesh(name: str) -> tuple[np.ndarray, np.ndarray]:
    if name == "cube":
        return cube_mesh()
    if name in {"icosphere", "rounded_box", "capsule"}:
        vertices, faces = uv_sphere(32, 16)
        if name == "rounded_box":
            vertices = np.sign(vertices) * np.minimum(np.abs(vertices) * 1.35, 0.5)
        elif name == "capsule":
            vertices[:, 1] += np.sign(vertices[:, 1]) * 0.25
        return vertices.astype(np.float32), faces
    if name in {"cylinder", "cone"}:
        segments = 32
        vertices = [[0, -0.5, 0], [0, 0.5, 0]]
        top_radius = 0.0 if name == "cone" else 0.4
        for y, radius in ((-0.5, 0.4), (0.5, top_radius)):
            for i in range(segments):
                angle = 2 * np.pi * i / segments
                vertices.append([radius * np.cos(angle), y, radius * np.sin(angle)])
        faces = []
        for i in range(segments):
            nxt = (i + 1) % segments
            faces.append([0, 2 + nxt, 2 + i])
            if top_radius > 0:
                faces.append([1, 2 + segments + i, 2 + segments + nxt])
            else:
                faces.append([1, 2 + i, 2 + nxt])
            if top_radius > 0:
                faces.extend([[2 + i, 2 + nxt, 2 + segments + i], [2 + nxt, 2 + segments + nxt, 2 + segments + i]])
        return np.asarray(vertices, np.float32), np.asarray(faces, np.int32)
    if name == "torus":
        major, minor = 32, 12
        vertices = []
        for i in range(major):
            u = 2 * np.pi * i / major
            for j in range(minor):
                v = 2 * np.pi * j / minor
                vertices.append([(0.35 + 0.14 * np.cos(v)) * np.cos(u), 0.14 * np.sin(v), (0.35 + 0.14 * np.cos(v)) * np.sin(u)])
        faces = []
        for i in range(major):
            for j in range(minor):
                a = i * minor + j
                b = ((i + 1) % major) * minor + j
                c = i * minor + (j + 1) % minor
                d = ((i + 1) % major) * minor + (j + 1) % minor
                faces.extend([[a, b, c], [c, b, d]])
        return np.asarray(vertices, np.float32), np.asarray(faces, np.int32)
    if name == "composite":
        a_v, a_f = cube_mesh()
        b_v, b_f = uv_sphere(24, 12)
        b_v = b_v * 0.55 + np.array([0.0, 0.55, 0.0], np.float32)
        return np.concatenate([a_v, b_v]), np.concatenate([a_f, b_f + len(a_v)])
    raise ValueError(f"unknown primitive: {name}")


def unique_edges(faces):
    import torch

    edges = torch.cat([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]], dim=0)
    edges = torch.sort(edges, dim=1).values
    return torch.unique(edges, dim=0)
