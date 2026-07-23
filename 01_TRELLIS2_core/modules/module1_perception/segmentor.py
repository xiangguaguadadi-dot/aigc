"""
SAM (Segment Anything Model) — Fine Mask Generation.

Takes bounding boxes from Grounding DINO and produces
pixel-precise binary masks for each detected object.
"""

from __future__ import annotations

from typing import List, Tuple, Optional
import warnings

import numpy as np
import torch
from PIL import Image


class SAMSegmentor:
    """
    Wrapper around SAM for box-guided instance segmentation.

    Usage:
        segmentor = SAMSegmentor(model_type="vit_h", checkpoint="sam_vit_h.pth", device="cuda")
        masks = segmentor.segment_with_boxes(image, boxes)
    """

    def __init__(
        self,
        model_type: str = "vit_h",
        checkpoint: str = "sam_vit_h_4b8939.pth",
        device: str = "cuda",
    ):
        self.device = device
        self.model_type = model_type
        self.model = self._load_model(checkpoint)

    def _load_model(self, checkpoint: str):
        """Load SAM model, auto-downloading if needed."""
        import os
        import sys

        try:
            from segment_anything import sam_model_registry, SamPredictor
        except ImportError:
            print("  Installing segment-anything...")
            import subprocess
            subprocess.run(
                [sys.executable, "-m", "pip", "install", "-q", "segment-anything"],
                check=False, timeout=120,
            )
            from segment_anything import sam_model_registry, SamPredictor

        if not os.path.exists(checkpoint):
            from huggingface_hub import hf_hub_download
            checkpoint = hf_hub_download(
                repo_id="facebook/sam-vit-huge",
                filename="sam_vit_h_4b8939.pth",
            )

        sam = sam_model_registry[self.model_type](checkpoint=checkpoint)
        sam.to(self.device)
        sam.eval()

        self.predictor = SamPredictor(sam)
        return sam

    def segment_with_boxes(
        self,
        image: np.ndarray,
        boxes: np.ndarray,
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """
        Generate masks from bounding box prompts.

        Parameters
        ----------
        image : np.ndarray  shape (H, W, 3), uint8 RGB
        boxes : np.ndarray  shape (N, 4) in (x1, y1, x2, y2)

        Returns
        -------
        masks : np.ndarray  shape (N, H, W) bool
        scores : np.ndarray  shape (N,) IoU prediction scores
        logits : np.ndarray  shape (N, H, W) raw logits
        """
        self.predictor.set_image(image)

        if len(boxes) == 0:
            return (
                np.zeros((0, image.shape[0], image.shape[1]), dtype=bool),
                np.zeros((0,), dtype=np.float32),
                np.zeros((0, image.shape[0], image.shape[1]), dtype=np.float32),
            )

        # SAM expects (N, 4) float box prompts
        input_boxes = torch.tensor(boxes, dtype=torch.float32, device=self.device)

        transformed_boxes = self.predictor.transform.apply_boxes_torch(
            input_boxes, image.shape[:2]
        )

        masks_list, scores_list, logits_list = [], [], []
        for i in range(len(transformed_boxes)):
            # Convert torch box to numpy for SAM predictor
            box_np = transformed_boxes[i].cpu().numpy().reshape(1, 4)
            mask, score, logit = self.predictor.predict(
                point_coords=None,
                point_labels=None,
                box=box_np,
                multimask_output=False,
            )
            masks_list.append(mask[0])     # (H, W)
            scores_list.append(score[0])
            logits_list.append(logit[0])   # (H, W)

        masks = np.stack(masks_list, axis=0) if masks_list else np.zeros((0, image.shape[0], image.shape[1]), dtype=bool)
        scores = np.array(scores_list, dtype=np.float32)
        logits = np.stack(logits_list, axis=0) if logits_list else np.zeros((0, image.shape[0], image.shape[1]), dtype=np.float32)

        return masks, scores, logits

    def segment_with_text(
        self,
        image: np.ndarray,
        text_prompts: List[str],
        boxes: np.ndarray,
        labels: List[str],
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        Assign each box-mask a label by matching detected label to text prompt.
        Returns masks and their object_ids.
        """
        masks, scores, _ = self.segment_with_boxes(image, boxes)

        # Build label → id mapping
        unique_labels = sorted(set(labels))
        label_to_id = {lbl: i for i, lbl in enumerate(unique_labels)}

        object_ids = np.array([label_to_id.get(lbl, -1) for lbl in labels], dtype=np.int32)

        return masks, object_ids
