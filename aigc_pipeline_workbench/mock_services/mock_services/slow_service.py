from .base import MockGPUService


app = MockGPUService(
    module_key="mock_slow",
    service_name="Mock Slow GPU Service",
    version="0.1.0",
    parameter_schema=[
        {
            "key": "duration_seconds",
            "label": "Duration Seconds",
            "value_type": "integer",
            "required": False,
            "default": 45,
            "minimum": 1,
            "maximum": 300,
        },
        {
            "key": "failure_rate",
            "label": "Random Failure Rate",
            "value_type": "number",
            "required": False,
            "default": 0,
            "minimum": 0,
            "maximum": 1,
        },
        {
            "key": "force_failure",
            "label": "Force Failure",
            "value_type": "boolean",
            "required": False,
            "default": False,
        },
    ],
    default_duration=45,
)
