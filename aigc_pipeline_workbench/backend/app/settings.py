from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_version: str = "0.1.0"
    contract_version: str = "v1"
    database_path: Path = Path("data/workbench.sqlite3")
    artifact_store_root: Path = Path("data/artifacts")
    max_artifact_size_bytes: int = 1024 * 1024 * 1024
    control_plane_base_url: str = "http://127.0.0.1:8000"
    submit_timeout_seconds: float = 10.0
    poll_timeout_seconds: float = 10.0
    execution_timeout_seconds: int = 1800
    poll_interval_seconds: float = 2.0
    start_background_polling: bool = True
