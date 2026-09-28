from .base import MockGPUService


app = MockGPUService(
    module_key="mock_fast",
    service_name="Mock Fast GPU Service",
    version="0.1.0",
    parameter_schema=[
        {
            "key": "message",
            "label": "Result Message",
            "value_type": "string",
            "required": False,
            "default": "mock fast succeeded",
        }
    ],
    default_duration=3,
    max_duration=10,
)
