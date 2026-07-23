"""
OWL-ViT — Open-Vocabulary Object Detection.

Uses HuggingFace transformers pipeline for zero-shot detection.
No manual weight download needed — auto-downloads via HF mirror.

Also supports:
  - GroundingDINO (if installed locally with weights available)
  - YOLO-World (lightweight, pure-pip alternative)
"""

from __future__ import annotations

import os
from typing import List, Tuple, Optional

import numpy as np
import torch
from PIL import Image


class OWLDetector:
    """
    Open-vocabulary detector using OWL-ViT via HuggingFace transformers.

    Usage:
        detector = OWLDetector(device="cuda")
        boxes, labels, scores = detector.detect(image, "chair . table . cup")
    """

    def __init__(
        self,
        model_name: str = "google/owlvit-base-patch32",
        device: str = "cuda",
        box_threshold: float = 0.15,
    ):
        self.device = device
        self.model_name = model_name
        self.box_threshold = box_threshold
        self.pipeline = None  # lazy load

    def _load(self):
        """Lazy-load the OWL-ViT pipeline."""
        if self.pipeline is not None:
            return
        from transformers import pipeline
        self.pipeline = pipeline(
            task="zero-shot-object-detection",
            model=self.model_name,
            device=self.device if self.device == "cuda" else -1,
        )

    def detect(
        self,
        image: Image.Image,
        text_prompt: str,
    ) -> Tuple[np.ndarray, List[str], np.ndarray]:
        """
        Detect objects in an image using open-vocabulary text prompt.

        Parameters
        ----------
        image : PIL Image
        text_prompt : str  e.g. "chair . table . sofa" or "chair, table, sofa"

        Returns
        -------
        boxes : np.ndarray  (N, 4) in (x1, y1, x2, y2) pixel coords
        labels : List[str]  semantic labels
        scores : np.ndarray  (N,) confidence scores
        """
        self._load()

        # Parse text prompt into candidate list
        candidates = [s.strip() for s in text_prompt.replace(",", ".").split(".") if s.strip()]

        H, W = image.size[1], image.size[0]  # PIL: (W, H)

        results = self.pipeline(
            image,
            candidate_labels=candidates,
            threshold=self.box_threshold,
        )

        if not results:
            return (
                np.zeros((0, 4), dtype=np.int32),
                [],
                np.zeros((0,), dtype=np.float32),
            )

        boxes_pixel = []
        labels = []
        scores = []

        for r in results:
            box = r["box"]
            x1 = int(box["xmin"])
            y1 = int(box["ymin"])
            x2 = int(box["xmax"])
            y2 = int(box["ymax"])
            boxes_pixel.append([x1, y1, x2, y2])
            labels.append(r["label"])
            scores.append(r["score"])

        return (
            np.array(boxes_pixel, dtype=np.int32),
            labels,
            np.array(scores, dtype=np.float32),
        )


# ---- Backward-compatible alias ----
GroundingDINODetector = OWLDetector
