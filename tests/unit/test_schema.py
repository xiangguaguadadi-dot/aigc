import unittest

from physical_agent.domain.task.physical_model_card import (
    CardValidationError,
    validate_physical_model_card,
)


def valid_card():
    return {
        "task": {
            "question": "球从斜面上释放后如何运动？",
            "target_quantity": "trajectory",
        },
        "observed": {
            "object_count": 1,
            "object_type": "sphere",
            "support_surface": "inclined_plane",
            "approximate_color": "red",
        },
        "assumed": {
            "material_class": "rubber",
            "scale_source": "user_input",
            "joint_type": "none",
        },
        "unknown": ["mass", "friction", "restitution"],
        "model": {
            "family": "rigid_body",
            "geometry": "sphere",
            "radius": 0.1,
        },
        "parameter_hypotheses": [
            {
                "name": "rubber_ball",
                "mass": 0.3,
                "friction": 0.8,
                "restitution": 0.75,
                "confidence": 0.55,
            }
        ],
        "follow_up_question": "球的真实直径是多少？",
    }


class SchemaTest(unittest.TestCase):
    def test_valid_card_passes(self):
        card = valid_card()

        self.assertEqual(validate_physical_model_card(card), card)

    def test_rejects_unsupported_model_family(self):
        card = valid_card()
        card["model"]["family"] = "fluid"

        with self.assertRaises(CardValidationError):
            validate_physical_model_card(card)

    def test_rejects_bad_parameter_range(self):
        card = valid_card()
        card["parameter_hypotheses"][0]["restitution"] = 1.4

        with self.assertRaises(CardValidationError):
            validate_physical_model_card(card)


if __name__ == "__main__":
    unittest.main()
