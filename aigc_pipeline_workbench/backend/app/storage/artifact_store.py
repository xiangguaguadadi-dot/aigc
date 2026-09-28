from abc import ABC, abstractmethod
from typing import IO, Optional


class ArtifactStore(ABC):
    @abstractmethod
    def save(self, storage_key: str, content: IO[bytes], mime_type: Optional[str] = None) -> int:
        raise NotImplementedError

    @abstractmethod
    def open(self, storage_key: str):
        raise NotImplementedError

    @abstractmethod
    def exists(self, storage_key: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    def delete(self, storage_key: str) -> bool:
        raise NotImplementedError
