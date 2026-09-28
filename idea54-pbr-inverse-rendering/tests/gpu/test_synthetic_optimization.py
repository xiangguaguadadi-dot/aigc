import pytest

pytest.importorskip("torch")
pytestmark = pytest.mark.gpu

from idea54.experiment import render_synthetic_observation
from idea54.optimizer import run_method
from idea54.renderer import renderer_available
from idea54.schema import load_bundle
from idea54.synthetic import make_synthetic_bundle


@pytest.mark.skipif(not renderer_available()[0], reason=renderer_available()[1])
def test_bounded_smoke_preserves_geometry(tmp_path):
    root = make_synthetic_bundle(tmp_path / "bundle", "cube", 64, 42)
    render_synthetic_observation(root)
    bundle = load_bundle(root)
    config = {
        "seed": 42,
        "optimization": {
            "steps": 2, "learning_rate": 0.02, "log_every": 1,
            "epsilon_base_color": 0.15, "epsilon_metallic": 0.2, "epsilon_roughness": 0.2,
            "weights": {"rgb": 1.0, "prior": 0.08, "tv": 0.02, "light_energy": 0.01, "white_balance": 0.01},
        },
    }
    result = run_method(bundle, "bounded_pbr_light", config, tmp_path / "run")
    assert result["geometry_unchanged"] is True
