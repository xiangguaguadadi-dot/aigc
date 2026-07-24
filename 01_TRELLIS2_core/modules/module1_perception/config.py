"""Configuration for Module 1: Perception & Segmentation."""

from dataclasses import dataclass, field
from typing import List, Optional

@dataclass
class SegmentationConfig:
    """Pipeline configuration."""

    # ---- 2D Detection (Grounding DINO) ----
    gdino_config: str = "GroundingDINO/groundingdino_swint_ogc.py"
    gdino_checkpoint: str = "GroundingDINO/groundingdino_swint_ogc.pth"
    gdino_box_threshold: float = 0.35
    gdino_text_threshold: float = 0.25

    # ---- SAM ----
    sam_model_type: str = "vit_h"          # vit_h / vit_l / vit_b
    sam_checkpoint: str = "/root/module1/model_weights/sam_vit_h_4b8939.pth"

    # ---- Text prompt (open-vocabulary) ----
    text_prompt: str = "chair . table . sofa . cup . book . laptop . bottle . plant . pillow . lamp"

    # ---- 3D Lifting ----
    depth_scale: float = 1.0               # depth unit multiplier
    min_depth: float = 0.1                 # minimum valid depth (m)
    max_depth: float = 10.0                # maximum valid depth (m)

    # ---- Output ----
    output_dir: str = "./output_module1"
    save_individual_ply: bool = True       # save per-object PLY
    save_visualization: bool = True        # save annotated images

    # ---- Device ----
    device: str = "cuda"
