import json

import pytest

from idea54.errors import Idea54Error
from idea54.schema import load_bundle, validate_bundle
from idea54.synthetic import make_synthetic_bundle


def test_programmatic_bundle_validates(tmp_path):
    root = make_synthetic_bundle(tmp_path / "bundle", "cube", 32, 42)
    result = validate_bundle(root)
    assert result["status"] == "valid"
    assert result["vertices"] == 8
    assert len(result["geometry_sha256"]) == 64


def test_hash_mismatch_fails_closed(tmp_path):
    root = make_synthetic_bundle(tmp_path / "bundle", "cube", 32, 42)
    camera = json.loads((root / "camera.json").read_text())
    camera["near"] = 0.2
    (root / "camera.json").write_text(json.dumps(camera))
    with pytest.raises(Idea54Error, match="HASH_MISMATCH"):
        load_bundle(root)


def test_unsafe_manifest_path_is_rejected(tmp_path):
    root = make_synthetic_bundle(tmp_path / "bundle", "cube", 32, 42)
    manifest = json.loads((root / "manifest.json").read_text())
    manifest["files"]["camera"]["path"] = "../camera.json"
    (root / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(Idea54Error, match="UNSAFE_PATH"):
        load_bundle(root, verify_hashes=False)
