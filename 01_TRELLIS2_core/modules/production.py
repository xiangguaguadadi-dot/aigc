"""
Production Pipeline — follows engineering manual exactly.

Manual mapping:
  §2.3 Object Separation  → M1 (detection + 2D masks)
  §3.1 Watertight         → make_watertight()
  §3.2 Scale Alignment    → calibrate_scale() + apply_scale()
  §3.3 Collision          → generate_compound_collision()
  §3.4 Physics Auto-Assign → auto_assign()
  §4.2 Scene Assembly     → place objects with poses
  §5.1-5.2 Interaction    → ray cast → constraint → drag → release
"""

import os, sys, json, time, base64
import numpy as np
import trimesh

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipeline.engineering import (
    calibrate_scale, make_watertight,
    generate_compound_collision, auto_assign_physics,
)
from pipeline.colmap_io import (
    load_colmap_poses, load_transforms_json, calibrate_from_reference,
)


class ProductionPipeline:
    """
    End-to-end production pipeline following the engineering manual.
    """

    def __init__(self, reference_object: str = "chair",
                 reference_size_m: float = 0.50,
                 colmap_dir: str = None,
                 transforms_json: str = None):
        """
        Parameters
        ----------
        reference_object : str  object with known real size for scale calibration
        reference_size_m : float  real-world size in meters
        colmap_dir : str  path to COLMAP sparse/0/ directory
        transforms_json : str  path to NeRFStudio transforms.json
        """
        self.ref_object = reference_object
        self.ref_size_m = reference_size_m
        self.scale_factor = None
        self.objects = {}
        self.output_dir = None

        # Load camera poses from COLMAP or NeRFStudio
        self.camera_poses = None
        if colmap_dir and os.path.isdir(colmap_dir):
            print(f"Loading COLMAP poses from {colmap_dir}...")
            try:
                self.camera_poses = load_colmap_poses(colmap_dir)
                print(f"  Loaded {len(self.camera_poses)} camera poses")
            except Exception as e:
                print(f"  COLMAP load failed: {e}")
        elif transforms_json and os.path.exists(transforms_json):
            print(f"Loading NeRFStudio poses from {transforms_json}...")
            try:
                self.camera_poses = load_transforms_json(transforms_json)
                print(f"  Loaded {len(self.camera_poses)} camera poses")
            except Exception as e:
                print(f"  Transform load failed: {e}")

        if self.camera_poses is None:
            print("  No camera poses provided — using default layout")

    # ================================================================
    # §2.3 Object Separation — initialize objects from GLB files
    # ================================================================
    def load_objects(self, glb_paths: dict):
        """
        Load pre-separated object GLBs (from TRELLIS.2 or COLMAP+MVS+OpenMask3D).

        glb_paths: {"chair": "/path/chair.glb", "table": "/path/table.glb", ...}
        """
        print("=" * 60)
        print("§2.3 Object Separation — Loading pre-separated meshes")
        print("=" * 60)

        for label, path in glb_paths.items():
            if not os.path.exists(path):
                print(f"  SKIP {label}: {path} not found")
                continue

            mesh = trimesh.load(path)
            if isinstance(mesh, trimesh.Scene):
                mesh = mesh.to_geometry()

            self.objects[label] = {
                "label": label,
                "vertices": mesh.vertices.astype(np.float64),
                "faces": mesh.faces.astype(np.int32),
                "vertex_colors": (mesh.visual.vertex_colors[:, :3].astype(np.uint8)
                                  if hasattr(mesh.visual, 'vertex_colors') and
                                  mesh.visual.vertex_colors is not None
                                  else None),
            }
            print(f"  {label}: {len(mesh.vertices):,}v, {len(mesh.faces):,}f")

        return self

    # ================================================================
    # §3.1 Watertight + §3.2 Scale + §3.3 Collision + §3.4 Physics
    # ================================================================
    def preprocess_physics(self):
        """
        Run all physics preprocessing steps on each object.

        §3.1 Watertight repair
        §3.2 Scale alignment (using reference object)
        §3.3 Collision body generation
        §3.4 Physics auto-assignment
        """
        # First pass: compute scale factor from reference object
        if self.ref_object in self.objects:
            ref = self.objects[self.ref_object]
            bbox_diag = np.linalg.norm(
                ref["vertices"].max(axis=0) - ref["vertices"].min(axis=0)
            )
            self.scale_factor = calibrate_scale(
                self.ref_object, bbox_diag, self.ref_size_m
            )
            print(f"\n§3.2 Scale: ref='{self.ref_object}' "
                  f"bbox={bbox_diag:.3f} → scale={self.scale_factor:.4f}")
        else:
            self.scale_factor = 1.0
            print(f"\n§3.2 Scale: no reference object, using 1.0")

        print("=" * 60)
        print("§3.1-3.4 Physics Preprocessing")
        print("=" * 60)

        for label, obj in self.objects.items():
            print(f"\n  [{label}]")
            verts = obj["vertices"]
            faces = obj["faces"]

            # §3.2 Apply per-object scale (each object has its own real-world size)
            obj_scale = calibrate_scale(label, np.linalg.norm(verts.max(axis=0) - verts.min(axis=0)))
            scaled_verts = verts * obj_scale
            print(f"    §3.2 Scale: {obj_scale:.4f}×")

            # §3.1 Watertight
            wt_verts, wt_faces = make_watertight(scaled_verts, faces)
            is_wt = trimesh.Trimesh(wt_verts, wt_faces).is_watertight
            print(f"    §3.1 Watertight: {is_wt} ({len(wt_verts):,}v, {len(wt_faces):,}f)")

            # §3.3 Collision
            hulls = generate_compound_collision(wt_verts, wt_faces)
            print(f"    §3.3 Collision: {len(hulls)} convex hull(s)")

            # §3.4 Physics
            phys = auto_assign_physics(
                label, verts, faces,
                scale_m=obj_scale,
            )
            print(f"    §3.4 Physics: {phys['material']}, {phys['mass_kg']:.3f}kg, "
                  f"vol={phys['volume_m3']*1e6:.0f}cm³")

            obj.update({
                "watertight_verts": wt_verts,
                "watertight_faces": wt_faces,
                "collision_hulls": hulls,
                "physics": phys,
            })

        return self

    # ================================================================
    # §4.2 Scene Assembly
    # ================================================================
    def assemble_scene(self, object_poses: dict = None):
        """
        Place objects in the scene with real-world poses.

        object_poses: {"chair": (x,y,z, qx,qy,qz,qw), ...}
        If None, auto-layout in a row.
        """
        print("\n" + "=" * 60)
        print("§4.2 Scene Assembly")
        print("=" * 60)

        if object_poses is None:
            # Auto-layout: spread objects in a row
            n = len(self.objects)
            object_poses = {}
            for i, label in enumerate(self.objects):
                x = (i - n/2) * 1.5
                object_poses[label] = (x, 0.5, 0, 0, 0, 0, 1)  # x,y,z,qx,qy,qz,qw

        self._poses = {}
        for label, pose in object_poses.items():
            if label in self.objects:
                pos = np.array(pose[:3]) * self.scale_factor
                quat = pose[3:] if len(pose) > 3 else (0, 0, 0, 1)
                self._poses[label] = (pos, quat)
                print(f"  {label}: pos=[{pos[0]:.2f},{pos[1]:.2f},{pos[2]:.2f}]")

        return self

    # ================================================================
    # §5.1-5.2 Interaction Simulation (PyBullet)
    # ================================================================
    def run_interaction_demo(self, output_dir: str = None):
        """
        Full physics simulation + interaction demo per manual §5.1-5.2.
        """
        self.output_dir = output_dir or "./production_output"
        os.makedirs(self.output_dir, exist_ok=True)

        import pybullet as p
        import pybullet_data

        print("\n" + "=" * 60)
        print("§5 Physics Simulation + Interaction")
        print("=" * 60)

        p.connect(p.DIRECT)
        p.setGravity(0, -9.81, 0)
        p.setTimeStep(1.0 / 240.0)
        p.setAdditionalSearchPath(pybullet_data.getDataPath())

        # Load ground plane (STATIC, mass=0) — §4.2
        ground_id = p.loadURDF("plane.urdf")
        print("  §4.2 Ground: STATIC (mass=0)")

        # Load each object with physics properties
        body_ids = {}
        body_map = {}

        for label, obj in self.objects.items():
            phys = obj["physics"]
            pose = self._poses.get(label, (np.zeros(3), (0, 0, 0, 1)))

            # §3.3 Collision: use bounding box (PyBullet limit)
            bmin = obj["watertight_verts"].min(axis=0)
            bmax = obj["watertight_verts"].max(axis=0)
            half_ext = ((bmax - bmin) / 2).astype(np.float64).tolist()
            pos_offset = ((bmin + bmax) / 2).tolist()
            col_shape = p.createCollisionShape(p.GEOM_BOX, halfExtents=half_ext)

            # Adjust position by bbox center offset
            body_pos = (np.array(pose[0]) + np.array(pos_offset)).tolist()
            body_id = p.createMultiBody(
                baseMass=phys.get("mass_kg", 1.0),
                baseCollisionShapeIndex=col_shape,
                basePosition=body_pos,
                baseOrientation=list(pose[1]),
            )

            # §3.4 Physics properties
            p.changeDynamics(
                body_id, -1,
                lateralFriction=phys.get("friction", 0.5),
                restitution=phys.get("restitution", 0.1),
                linearDamping=0.04,
                angularDamping=0.04,
            )

            body_ids[label] = body_id
            body_map[body_id] = label

            print(f"  [{label}] mass={phys.get('mass_kg',0):.3f}kg, "
                  f"friction={phys.get('friction',0):.2f}, "
                  f"pos=[{pose[0][0]:.2f},{pose[0][1]:.2f},{pose[0][2]:.2f}]")

        # §5.1-5.2 Interaction: ray → grasp → drag → release for each object
        interaction_log = []

        for label, body_id in body_ids.items():
            pos, orn = p.getBasePositionAndOrientation(body_id)

            # §5.1 Ray Casting
            ray_from = [pos[0] + 2, pos[1] + 3, pos[2] + 2]
            ray_to = list(pos)
            hit = p.rayTest(ray_from, ray_to)

            hit_obj = None
            for h in hit:
                if h[0] == body_id and h[2] >= 0:
                    hit_obj = {"body": h[0], "link": h[1],
                               "fraction": h[2], "position": h[3], "normal": h[4]}
                    break

            if hit_obj is None:
                interaction_log.append({label: "ray miss"})
                continue

            # §5.1 Create constraint (Point2Point)
            cid = p.createConstraint(
                parentBodyUniqueId=body_id,
                parentLinkIndex=-1,
                childBodyUniqueId=-1,  # world
                childLinkIndex=-1,
                jointType=p.JOINT_POINT2POINT,
                jointAxis=[0, 0, 0],
                parentFramePosition=hit_obj["position"],
                childFramePosition=hit_obj["position"],
            )
            p.changeConstraint(cid, maxForce=500)

            # §5.1 Drag: move constraint target upward
            for step in range(30):
                target = [pos[0], pos[1] + 2.0 * (step/30), pos[2]]
                p.changeConstraint(cid, jointChildPivot=target, maxForce=500)
                p.stepSimulation()

            # §5.1 Release
            vel, ang = p.getBaseVelocity(body_id)
            p.removeConstraint(cid)
            p.resetBaseVelocity(body_id,
                                linearVelocity=vel,
                                angularVelocity=ang)

            # Let object fall and settle
            for _ in range(120):
                p.stepSimulation()

            final_pos, _ = p.getBasePositionAndOrientation(body_id)
            interaction_log.append({
                "object": label,
                "ray_hit": f"[{hit_obj['position'][0]:.2f},{hit_obj['position'][1]:.2f},{hit_obj['position'][2]:.2f}]",
                "initial": f"[{pos[0]:.2f},{pos[1]:.2f},{pos[2]:.2f}]",
                "dragged_to": f"[{pos[0]:.2f},{pos[1]+2.0:.2f},{pos[2]:.2f}]",
                "final": f"[{final_pos[0]:.2f},{final_pos[1]:.2f},{final_pos[2]:.2f}]",
            })
            print(f"  [{label}] ray→grasp→lift→release ✓  "
                  f"final=[{final_pos[0]:.2f},{final_pos[1]:.2f},{final_pos[2]:.2f}]")

        # Save results
        with open(f"{self.output_dir}/interaction_log.json", "w") as f:
            json.dump(interaction_log, f, indent=2)

        # Export each object's watertight mesh + physics JSON
        for label, obj in self.objects.items():
            out_dir = f"{self.output_dir}/{label}"
            os.makedirs(out_dir, exist_ok=True)

            # Watertight visual mesh
            wt_v = obj.get("watertight_verts", obj["vertices"])
            wt_f = obj.get("watertight_faces", obj["faces"])
            trimesh.Trimesh(wt_v, wt_f).export(f"{out_dir}/{label}.glb")

            # Collision hulls
            for i, (hv, hf) in enumerate(obj.get("collision_hulls", [])):
                trimesh.Trimesh(hv, hf).export(f"{out_dir}/{label}_collision_{i}.glb")

            # Physics JSON
            serializable = {}
            for k, v in obj["physics"].items():
                try:
                    if isinstance(v, np.ndarray): continue
                    if hasattr(v, 'tolist'): v = v.tolist()
                    if isinstance(v, (np.floating,)): v = float(v)
                    if isinstance(v, (np.integer,)): v = int(v)
                    json.dumps({k: v})  # test serialization
                    serializable[k] = v
                except (TypeError, ValueError):
                    serializable[k] = str(v)
            with open(f"{out_dir}/{label}_physics.json", "w") as f:
                json.dump(serializable, f, indent=2)

        p.disconnect()
        print(f"\n  Output: {os.path.abspath(self.output_dir)}")
        return self


def demo():
    """Run full production pipeline on available GLBs."""
    pipeline = ProductionPipeline(
        reference_object="chair",
        reference_size_m=0.50,  # Standard chair seat height
    )

    # §2.3: Load pre-separated objects
    pipeline.load_objects({
        "chair": "/root/trellis2-pipeline/output_chair.glb",
        "apple": "/root/trellis2-pipeline/output_apple.glb",
        "cup":   "/root/trellis2-pipeline/output_3.glb",
    })

    # §3.1-3.4: Physics preprocessing
    pipeline.preprocess_physics()

    # §4.2: Scene assembly
    pipeline.assemble_scene()

    # §5: Interaction
    pipeline.run_interaction_demo(output_dir="/root/trellis2-pipeline/production_output")

    # Summary
    print("\n" + "=" * 60)
    print("Production Pipeline Complete")
    print("=" * 60)
    for label, obj in pipeline.objects.items():
        p = obj["physics"]
        print(f"  {label:10s} {p['material']:8s} {p['mass_kg']:8.3f}kg  "
              f"scale={pipeline.scale_factor:.4f}")


if __name__ == "__main__":
    demo()
