import pytest

torch = pytest.importorskip("torch")

from idea54.lighting import LowDimensionalLight, fibonacci_directions
from idea54.losses import masked_charbonnier
from idea54.materials import PBRParameters


def prior():
    return {
        "base_color": torch.full((4, 3), 0.5),
        "metallic": torch.full((4, 1), 0.3),
        "roughness": torch.full((4, 1), 0.4),
        "opacity": torch.ones((4, 1)),
    }


def test_bounded_material_cannot_exceed_epsilon():
    params = PBRParameters(prior(), "bounded_pbr_light", {"base_color": 0.15, "metallic": 0.2, "roughness": 0.2})
    with torch.no_grad():
        params.delta_base_color.fill_(100)
        params.delta_metallic.fill_(-100)
        params.delta_roughness.fill_(100)
    material = params.material()
    assert torch.all(material["base_color"] <= 0.65 + 1e-6)
    assert torch.all(material["metallic"] >= 0.1 - 1e-6)
    assert torch.all(material["roughness"] <= 0.6 + 1e-6)


def test_lighting_is_nonnegative_and_white_balance_is_normalized():
    light = LowDimensionalLight()
    values = light.values()
    assert torch.all(values["intensity"] >= 0)
    assert torch.all(values["ambient"] >= 0)
    assert torch.isclose(torch.log(values["white_balance"]).mean(), torch.tensor(0.0), atol=1e-6)
    assert torch.allclose(fibonacci_directions(12).norm(dim=1), torch.ones(12), atol=1e-5)


def test_masked_charbonnier_has_gradient():
    prediction = torch.zeros((4, 4, 3), requires_grad=True)
    target = torch.ones_like(prediction)
    mask = torch.ones((4, 4))
    loss = masked_charbonnier(prediction, target, mask)
    loss.backward()
    assert prediction.grad is not None
    assert torch.isfinite(prediction.grad).all()
