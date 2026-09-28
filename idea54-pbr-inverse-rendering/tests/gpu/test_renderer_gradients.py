import pytest

torch = pytest.importorskip("torch")
pytestmark = pytest.mark.gpu

from idea54.lighting import LowDimensionalLight
from idea54.renderer import NvdiffrastPBRRenderer, renderer_available
from idea54.schema import load_bundle
from idea54.synthetic import make_synthetic_bundle


@pytest.mark.skipif(not renderer_available()[0], reason=renderer_available()[1])
def test_material_gradients_exist_and_geometry_gradients_do_not(tmp_path):
    root = make_synthetic_bundle(tmp_path / "bundle", "cube", 64, 42)
    bundle = load_bundle(root)
    renderer = NvdiffrastPBRRenderer()
    vertices = torch.tensor(bundle.geometry.vertices, device="cuda")
    faces = torch.tensor(bundle.geometry.faces, dtype=torch.int32, device="cuda")
    normals = torch.tensor(bundle.geometry.vertex_normals, device="cuda")
    material = {name: torch.tensor(getattr(bundle.material, name), device="cuda", requires_grad=name != "opacity") for name in ("base_color", "metallic", "roughness", "opacity")}
    light = LowDimensionalLight(device="cuda")
    output = renderer.render(vertices, faces, normals, material, bundle.camera, light.values())
    output.rgb.sum().backward()
    assert material["base_color"].grad is not None
    assert light.log_intensity.grad is not None
    assert vertices.grad is None and normals.grad is None
