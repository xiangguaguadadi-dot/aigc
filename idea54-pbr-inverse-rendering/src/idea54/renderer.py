from __future__ import annotations

from dataclasses import dataclass

import torch

from .cameras import projection_from_intrinsics
from .errors import Idea54Error
from .schema import Camera


@dataclass(frozen=True)
class RenderOutput:
    rgb: torch.Tensor
    mask: torch.Tensor


def renderer_available() -> tuple[bool, str]:
    if not torch.cuda.is_available():
        return False, "CUDA is unavailable"
    try:
        import nvdiffrast.torch  # noqa: F401
    except Exception as exc:
        return False, f"nvdiffrast import failed: {exc}"
    return True, "CUDA and nvdiffrast are available"


def _safe_normalize(value: torch.Tensor) -> torch.Tensor:
    return value / value.norm(dim=-1, keepdim=True).clamp_min(1e-7)


def _ggx_shade(
    position: torch.Tensor,
    normal: torch.Tensor,
    base_color: torch.Tensor,
    metallic: torch.Tensor,
    roughness: torch.Tensor,
    camera_position: torch.Tensor,
    light: dict[str, torch.Tensor],
) -> torch.Tensor:
    normal = _safe_normalize(normal)
    view = _safe_normalize(camera_position.view(1, 1, 3) - position)
    color = base_color * light["ambient"].view(1, 1, 3) * 0.35
    alpha = roughness.square().clamp_min(0.001)
    f0 = 0.04 * (1.0 - metallic) + base_color * metallic
    for direction, intensity in zip(light["directions"], light["intensity"], strict=True):
        incoming = direction.view(1, 1, 3).expand_as(position)
        half_vector = _safe_normalize(view + incoming)
        n_dot_l = (normal * incoming).sum(-1, keepdim=True).clamp_min(0.0)
        n_dot_v = (normal * view).sum(-1, keepdim=True).clamp_min(1e-5)
        n_dot_h = (normal * half_vector).sum(-1, keepdim=True).clamp_min(0.0)
        v_dot_h = (view * half_vector).sum(-1, keepdim=True).clamp(0.0, 1.0)
        denom = n_dot_h.square() * (alpha.square() - 1.0) + 1.0
        distribution = alpha.square() / (torch.pi * denom.square().clamp_min(1e-7))
        k = (roughness + 1.0).square() / 8.0
        g_v = n_dot_v / (n_dot_v * (1.0 - k) + k)
        g_l = n_dot_l / (n_dot_l * (1.0 - k) + k)
        geometry = g_v * g_l
        fresnel = f0 + (1.0 - f0) * (1.0 - v_dot_h).pow(5)
        specular = distribution * geometry * fresnel / (4.0 * n_dot_v * n_dot_l + 1e-6)
        diffuse = (1.0 - metallic) * base_color / torch.pi
        color = color + (diffuse + specular) * intensity.view(1, 1, 3) * n_dot_l
    return color * light["exposure"] * light["white_balance"].view(1, 1, 3)


class NvdiffrastPBRRenderer:
    def __init__(self) -> None:
        available, reason = renderer_available()
        if not available:
            raise Idea54Error("CUDA_RENDERER_UNAVAILABLE", reason)
        import nvdiffrast.torch as dr

        self.dr = dr
        self.context = dr.RasterizeCudaContext()

    def render(
        self,
        vertices: torch.Tensor,
        faces: torch.Tensor,
        normals: torch.Tensor,
        material: dict[str, torch.Tensor],
        camera: Camera,
        light: dict[str, torch.Tensor],
    ) -> RenderOutput:
        device = vertices.device
        k = torch.as_tensor(camera.k, device=device)
        world_to_camera = torch.as_tensor(camera.world_to_camera, device=device)
        projection = projection_from_intrinsics(k, camera.width, camera.height, camera.near, camera.far)
        ones = torch.ones((vertices.shape[0], 1), dtype=vertices.dtype, device=device)
        homogeneous = torch.cat([vertices, ones], dim=1)
        camera_vertices = homogeneous @ world_to_camera.T
        clip = camera_vertices @ projection.T
        raster, _ = self.dr.rasterize(self.context, clip.unsqueeze(0), faces, resolution=[camera.height, camera.width])
        position, _ = self.dr.interpolate(vertices.unsqueeze(0), raster, faces)
        normal, _ = self.dr.interpolate(normals.unsqueeze(0), raster, faces)
        attrs = torch.cat([material["base_color"], material["metallic"], material["roughness"], material["opacity"]], dim=1)
        interpolated, _ = self.dr.interpolate(attrs.unsqueeze(0), raster, faces)
        base_color = interpolated[..., :3]
        metallic = interpolated[..., 3:4]
        roughness = interpolated[..., 4:5]
        opacity = interpolated[..., 5:6]
        inverse = torch.linalg.inv(world_to_camera)
        camera_position = inverse[:3, 3]
        shaded = _ggx_shade(position[0], normal[0], base_color[0], metallic[0], roughness[0], camera_position, light)
        hard_mask = (raster[0, ..., 3:4] > 0).to(shaded.dtype)
        rgba = torch.cat([shaded * opacity[0], hard_mask], dim=-1).unsqueeze(0)
        antialiased = self.dr.antialias(rgba, raster, clip.unsqueeze(0), faces)[0]
        return RenderOutput(antialiased[..., :3] * antialiased[..., 3:4], antialiased[..., 3])


def linear_to_srgb(value: torch.Tensor) -> torch.Tensor:
    value = value.clamp(0.0, 1.0)
    return torch.where(value <= 0.0031308, 12.92 * value, 1.055 * value.pow(1.0 / 2.4) - 0.055)


def srgb_to_linear(value: torch.Tensor) -> torch.Tensor:
    value = value.clamp(0.0, 1.0)
    return torch.where(value <= 0.04045, value / 12.92, ((value + 0.055) / 1.055).pow(2.4))
