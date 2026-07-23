# Results and Limitations

## What Improved

- Camera coverage increased from the earlier 57-camera reconstruction to a 211-camera main
  model.
- All 265 selected frames received raw neural depth predictions; the 211 registered frames
  were aligned to the reconstruction.
- A failure that assigned zero weight to every neural depth map was corrected with
  scale-invariant confidence values.
- The final TSDF has 16 connected components, with 98.40% of triangles in the largest
  component.
- Metric PLY and GLB files share a right-handed, Z-up, meter-based coordinate system.
- Blender and Open3D import checks passed after replacing an invalid Open3D GLB writer path
  with Blender glTF export.

## What Is Not Solved

- Occluded and weak-texture regions still contain holes and noisy boundaries.
- Walls, ceiling and furniture surfaces contain high-frequency TSDF noise.
- Furniture is fused into one static mesh and is not yet an independently editable asset.
- The GLB has geometry/vertex-color data but no completed multi-view UV texture bake.
- The collision mesh is a provisional simplified proxy and still inherits reconstruction
  holes and noise.
- The sofa width is the calibration constraint; its zero reported residual is not an
  independent scale validation.

## Recommended Next Work

1. Re-optimize local camera poses and reject frames that cause double surfaces.
2. Re-fuse depth with confidence, visibility and depth-gradient filtering.
3. Regularize walls, floor and ceiling with explicit planar constraints.
4. Separate the visual representation from a lower-complexity collision representation.
5. Clean/remesh the visual surface before multi-view UV texture baking.
