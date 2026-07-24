"""
Physical Property Inference — VLM-powered material/size/mass estimation.

Uses Qwen2-VL to analyze the original photo and output structured JSON
with material, size, weight estimates for each detected object.

Fallback: CLIP + category prior (when VLM unavailable).
"""

import json
import numpy as np
from typing import List, Dict, Optional, Tuple


# ---- Density lookup table (fallback) ----
MATERIAL_DENSITY = {
    "wood": 700, "metal": 7800, "ceramic": 2600, "plastic": 1200,
    "fabric": 300, "glass": 2500, "leather": 860, "stone": 2700,
    "rubber": 1100, "paper": 800, "organic": 1000,
}

MATERIAL_FRICTION = {
    "wood": 0.55, "metal": 0.40, "ceramic": 0.35, "plastic": 0.30,
    "fabric": 0.65, "glass": 0.25, "leather": 0.50, "stone": 0.60,
    "rubber": 0.80, "paper": 0.45, "organic": 0.45,
}

MATERIAL_RESTITUTION = {
    "wood": 0.30, "metal": 0.15, "ceramic": 0.05, "plastic": 0.40,
    "fabric": 0.05, "glass": 0.10, "leather": 0.20, "stone": 0.05,
    "rubber": 0.70, "paper": 0.02, "organic": 0.10,
}


class VLMPhysicsAnalyzer:
    """
    Use Qwen2-VL to analyze a photo and estimate physical properties.

    Input:  photo + list of object labels
    Output: [{name, material, diameter_cm, mass_kg, rigid, density_kg_m3, friction, restitution}, ...]
    """

    def __init__(self, device: str = "cuda"):
        self.device = device
        self._model = None
        self._processor = None

    def _load(self):
        if self._model is not None:
            return
        import os, torch
        from transformers import Qwen2VLForConditionalGeneration, AutoProcessor

        # Try ModelScope local cache first, then HF mirror
        model_id = "Qwen/Qwen2-VL-2B-Instruct"
        local_paths = [
            "/root/.cache/modelscope/models/Qwen--Qwen2-VL-2B-Instruct/snapshots/master",
            "/root/.cache/modelscope/hub/Qwen/Qwen2-VL-2B-Instruct",
        ]
        model_path = model_id
        for lp in local_paths:
            if os.path.isdir(lp):
                model_path = lp
                print(f"    Using local: {model_path}")
                break

        self._model = Qwen2VLForConditionalGeneration.from_pretrained(
            model_path,
            torch_dtype=torch.bfloat16,
            device_map="auto",
        )
        self._processor = AutoProcessor.from_pretrained(model_path)

    def analyze(
        self,
        image,  # PIL Image or np.ndarray
        object_labels: List[str],
    ) -> List[Dict]:
        """
        Analyze photo with VLM, return structured physical properties.
        """
        self._load()

        labels_str = ", ".join(object_labels)
        prompt = (
            f"You are a physics expert. Look at this photo carefully. "
            f"I can see these objects in the scene: [{labels_str}]. "
            f"For EACH object, estimate its real-world physical properties based on what you see:\n"
            f"- material: choose from [wood, metal, ceramic, plastic, fabric, glass, leather, stone, rubber, organic]\n"
            f"- diameter_cm: approximate bounding sphere diameter in centimeters\n"
            f"- mass_kg: approximate weight in kilograms\n"
            f"- rigid: true if the object is rigid/solid, false if soft/deformable\n\n"
            f"Reply with ONLY a valid JSON array. No other text. Format:\n"
            f'[{{"name": "object1", "material": "wood", "diameter_cm": 50, "mass_kg": 5.0, "rigid": true}}, ...]\n'
        )

        from PIL import Image
        if isinstance(image, np.ndarray):
            image = Image.fromarray(image.astype(np.uint8))

        # Build conversation
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "image", "image": image},
                    {"type": "text", "text": prompt},
                ],
            }
        ]

        text = self._processor.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
        inputs = self._processor(
            text=[text], images=[image], padding=True, return_tensors="pt"
        ).to(self.device)

        import torch
        with torch.no_grad():
            output_ids = self._model.generate(**inputs, max_new_tokens=512)
        generated = output_ids[0][inputs.input_ids.shape[1]:]
        response = self._processor.decode(generated, skip_special_tokens=True)

        # Parse JSON from response
        return self._parse_response(response, object_labels)

    def _parse_response(self, response: str, labels: List[str]) -> List[Dict]:
        """Extract JSON array from VLM response, with fallback defaults."""
        # Try to extract JSON array
        try:
            # Find first [ and last ]
            start = response.find("[")
            end = response.rfind("]") + 1
            if start >= 0 and end > start:
                json_str = response[start:end]
                results = json.loads(json_str)
                if isinstance(results, list) and len(results) > 0:
                    return self._normalize_results(results, labels)
        except (json.JSONDecodeError, Exception):
            pass

        # Fallback: common-sense defaults per label
        return [_default_properties(lbl) for lbl in labels]

    def _normalize_results(self, results: List[Dict], labels: List[str]) -> List[Dict]:
        """Fill in missing fields with defaults, normalize material names."""
        out = []
        for item in results:
            name = item.get("name", "object")
            mat = item.get("material", "plastic").lower().strip()
            if mat not in MATERIAL_DENSITY:
                mat = "plastic"
            diam = float(item.get("diameter_cm", 30))
            mass = float(item.get("mass_kg", 1.0))
            rigid = bool(item.get("rigid", True))
            density = MATERIAL_DENSITY[mat]

            out.append({
                "name": name,
                "material": mat,
                "diameter_cm": diam,
                "mass_kg": mass,
                "rigid": rigid,
                "density_kg_m3": density,
                "friction": MATERIAL_FRICTION[mat],
                "restitution": MATERIAL_RESTITUTION[mat],
            })
        return out


# ---- Fallback: common-sense defaults per object category ----
_CATEGORY_DEFAULTS = {
    "apple":  {"material": "organic", "diameter_cm": 8,  "mass_kg": 0.20, "rigid": True},
    "orange": {"material": "organic", "diameter_cm": 8,  "mass_kg": 0.20, "rigid": True},
    "banana": {"material": "organic", "diameter_cm": 18, "mass_kg": 0.12, "rigid": False},
    "cup":    {"material": "ceramic", "diameter_cm": 8,  "mass_kg": 0.30, "rigid": True},
    "mug":    {"material": "ceramic", "diameter_cm": 9,  "mass_kg": 0.35, "rigid": True},
    "bottle": {"material": "plastic", "diameter_cm": 7,  "mass_kg": 0.05, "rigid": True},
    "chair":  {"material": "wood",    "diameter_cm": 50, "mass_kg": 5.0,  "rigid": True},
    "table":  {"material": "wood",    "diameter_cm": 80, "mass_kg": 20.0, "rigid": True},
    "desk":   {"material": "wood",    "diameter_cm": 80, "mass_kg": 25.0, "rigid": True},
    "sofa":   {"material": "fabric",  "diameter_cm": 200,"mass_kg": 40.0, "rigid": False},
    "laptop": {"material": "metal",   "diameter_cm": 35, "mass_kg": 1.5,  "rigid": True},
    "book":   {"material": "paper",   "diameter_cm": 20, "mass_kg": 0.5,  "rigid": True},
    "phone":  {"material": "metal",   "diameter_cm": 7,  "mass_kg": 0.20, "rigid": True},
    "vase":   {"material": "ceramic", "diameter_cm": 15, "mass_kg": 1.0,  "rigid": True},
    "lamp":   {"material": "metal",   "diameter_cm": 30, "mass_kg": 2.0,  "rigid": True},
    "plant":  {"material": "organic", "diameter_cm": 40, "mass_kg": 3.0,  "rigid": False},
    "pillow": {"material": "fabric",  "diameter_cm": 40, "mass_kg": 0.5,  "rigid": False},
    "tv":     {"material": "plastic", "diameter_cm": 100,"mass_kg": 10.0, "rigid": True},
    "curtain":{"material": "fabric",  "diameter_cm": 150,"mass_kg": 2.0,  "rigid": False},
    "default":{"material": "plastic", "diameter_cm": 30, "mass_kg": 1.0,  "rigid": True},
}


def _default_properties(label: str) -> Dict:
    """Common-sense physical defaults for a given object label."""
    label_lower = label.lower().strip()
    defaults = _CATEGORY_DEFAULTS.get(label_lower, _CATEGORY_DEFAULTS["default"])
    mat = defaults["material"]
    return {
        "name": label,
        "material": mat,
        "diameter_cm": defaults["diameter_cm"],
        "mass_kg": defaults["mass_kg"],
        "rigid": defaults["rigid"],
        "density_kg_m3": MATERIAL_DENSITY.get(mat, 1000),
        "friction": MATERIAL_FRICTION.get(mat, 0.4),
        "restitution": MATERIAL_RESTITUTION.get(mat, 0.1),
    }


def get_physics_params(material: str, volume_m3: Optional[float] = None,
                       mass_kg: Optional[float] = None) -> Dict:
    """Get physical parameters dict for a material and optional volume/mass."""
    mat = material.lower().strip()
    density = MATERIAL_DENSITY.get(mat, 1000)
    friction = MATERIAL_FRICTION.get(mat, 0.4)
    restitution = MATERIAL_RESTITUTION.get(mat, 0.1)
    params = {"material": mat, "density_kg_m3": density,
              "friction": friction, "restitution": restitution}
    if volume_m3 is not None:
        params["volume_m3"] = volume_m3
        params["mass_kg"] = mass_kg if mass_kg is not None else volume_m3 * density
    elif mass_kg is not None:
        params["mass_kg"] = mass_kg
    return params
