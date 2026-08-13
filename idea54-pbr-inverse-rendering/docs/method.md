# Method

The initial material is `P0 = (base color, metallic, roughness, opacity)`. The
mesh and camera are fixed. For the bounded method, each optimized channel is

```text
P = clamp(P0 + epsilon * tanh(delta), valid_min, valid_max).
```

The light is represented by twelve fixed Fibonacci-sphere directions with
non-negative RGB intensities, an ambient RGB term, exposure, and mean-normalized
white balance. Shading uses Lambert diffuse and Cook–Torrance GGX specular in
linear RGB. sRGB conversion occurs only at image I/O.

The loss combines masked Charbonnier reconstruction, distance to the PBR prior,
mesh-edge total variation of material residuals, light-energy regularization,
and white-balance regularization.

Four paired variants are required. `lighting_only` identifies improvements that
can be explained without changing material. `unbounded_pbr_light` provides an
overfitting control. `bounded_pbr_light` is Idea 5.4.
