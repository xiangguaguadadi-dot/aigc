import numpy as np

from idea54.metrics import masked_mae, paired_bootstrap_ci, psnr


def test_masked_metrics_ignore_background():
    target = np.zeros((2, 2, 3), dtype=np.float32)
    prediction = target.copy()
    prediction[0, 0] = 1
    mask = np.array([[0, 0], [0, 1]], dtype=np.float32)
    assert masked_mae(prediction, target, mask) == 0
    assert psnr(prediction, target, mask) == float("inf")


def test_bootstrap_is_reproducible():
    values = np.array([0.1, 0.2, 0.3])
    assert paired_bootstrap_ci(values, seed=7, samples=100) == paired_bootstrap_ci(values, seed=7, samples=100)
