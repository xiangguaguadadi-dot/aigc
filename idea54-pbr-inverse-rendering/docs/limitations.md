# Limitations

- Single-image material and illumination separation is non-identifiable.
- Synthetic ground truth validates controlled recovery, not real material truth.
- The compact directional-light renderer is not the lost TRELLIS.2/nvdiffrec
  split-sum runtime; numerical results will differ.
- The first release uses per-vertex material attributes. Fine texture recovery
  requires a later texture-space representation.
- Camera calibration is fixed. Pose error can therefore appear as residual
  image error, but cannot be absorbed by geometry in this implementation.
- Held-out camera declarations are generated, while v0.1.0 reporting focuses on
  condition fit and material ground truth; complete held-out relighting remains
  a CUDA validation item before claiming the full research gate.
