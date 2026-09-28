import shutil
from pathlib import Path
from typing import IO, Optional

from app.errors import AppError
from app.domain.enums import ErrorCode
from app.storage.artifact_store import ArtifactStore


class LocalArtifactStore(ArtifactStore):
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _resolve(self, storage_key: str) -> Path:
        relative_path = Path(storage_key)
        if relative_path.is_absolute() or ".." in relative_path.parts:
            raise AppError(ErrorCode.INVALID_REQUEST, "invalid storage key")
        resolved = (self.root / relative_path).resolve()
        try:
            resolved.relative_to(self.root)
        except ValueError as exc:
            raise AppError(ErrorCode.INVALID_REQUEST, "invalid storage key") from exc
        return resolved

    def save(self, storage_key: str, content: IO[bytes], mime_type: Optional[str] = None) -> int:
        path = self._resolve(storage_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("wb") as target:
            shutil.copyfileobj(content, target)
            return target.tell()

    def open(self, storage_key: str):
        path = self._resolve(storage_key)
        if not path.is_file():
            raise FileNotFoundError(storage_key)
        return path.open("rb")

    def exists(self, storage_key: str) -> bool:
        try:
            return self._resolve(storage_key).is_file()
        except AppError:
            return False

    def delete(self, storage_key: str) -> bool:
        path = self._resolve(storage_key)
        if not path.exists():
            return False
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
        return True
