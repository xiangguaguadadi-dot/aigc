# Third-Party Dependencies

The repository does not vendor third-party source trees or model checkpoints. Reproduce
the cloud environment by cloning the upstream projects and checking out these commits:

| Project | Repository | Commit |
|---|---|---|
| Hierarchical Localization | https://github.com/cvg/Hierarchical-Localization | `c13273bd0ecc2917a35910fd843712a1c6243193` |
| MASt3R-SLAM | https://github.com/rmurai0610/MASt3R-SLAM | `e6f4e3d474fad0e11f561482012be864ba8c3f17` |
| PlanarGS | https://github.com/SJTU-ViSYS-team/PlanarGS | `a68f22043e95146c4f1c52cc0e471a6a90e86f73` |
| lietorch | https://github.com/princeton-vl/lietorch | `e7df86554156b36846008d8ddbcc4d8521a16554` |

COLMAP, Open3D, Blender, GroundingDINO and SAM are also required by individual stages.
Consult each upstream repository and checkpoint page for its license and model terms.

The cloud checkout contained no source changes in HLoc, MASt3R-SLAM or lietorch.
PlanarGS only contained rebuilt native `.so` files and untracked checkpoint/model
directories; those generated binaries and weights are not redistributed.
