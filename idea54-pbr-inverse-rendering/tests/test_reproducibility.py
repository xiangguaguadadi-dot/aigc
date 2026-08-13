from idea54.hashing import sha256_file
from idea54.synthetic import make_synthetic_bundle


def test_same_seed_produces_same_core_arrays(tmp_path):
    one = make_synthetic_bundle(tmp_path / "one", "torus", 32, 17)
    two = make_synthetic_bundle(tmp_path / "two", "torus", 32, 17)
    for name in ("geometry.npz", "material_prior.npz", "camera.json", "observation.png", "observation_mask.png"):
        assert sha256_file(one / name) == sha256_file(two / name)
