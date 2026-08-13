# PBRAssetBundle v1

Required files:

```text
manifest.json
geometry.npz
material_prior.npz
camera.json
observation.png
observation_mask.png
```

`geometry.npz` contains `float32 vertices[V,3]`, `int32 faces[F,3]`, and
`float32 vertex_normals[V,3]`. `material_prior.npz` contains per-vertex
`base_color[V,3]`, `metallic[V,1]`, `roughness[V,1]`, and `opacity[V,1]`.

The camera file contains `width`, `height`, `K[3,3]`,
`world_to_camera[4,4]`, `near`, and `far`. Manifest paths must be relative and
each required file has a SHA-256 digest. Unknown layouts fail closed.

Synthetic bundles additionally contain `evaluation/material_gt.npz` and
held-out camera declarations. Evaluation files are deliberately outside the
optimization input contract.
