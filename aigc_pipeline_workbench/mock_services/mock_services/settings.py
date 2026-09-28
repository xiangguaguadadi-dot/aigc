from pydantic_settings import BaseSettings


class MockSettings(BaseSettings):
    control_plane_base_url: str = "http://127.0.0.1:8000"
