"""Document storage abstraction.

The app writes uploaded files through `DocumentStore.put` and reads via `.open`. The
current `LocalDiskStore` impl puts files at `<root>/<tenant_id>/<file_key>` where
`file_key` is derived from the content hash. A future S3 impl will match the same
interface — swapping is a config change.
"""

from __future__ import annotations

import hashlib
import uuid
from abc import ABC, abstractmethod
from pathlib import Path
from typing import BinaryIO


class DocumentStore(ABC):
    @abstractmethod
    async def put(
        self, *, tenant_id: uuid.UUID, data: bytes
    ) -> tuple[str, str]:
        """Persist bytes; return (file_key, sha256_hex)."""

    @abstractmethod
    def open(self, *, tenant_id: uuid.UUID, file_key: str) -> BinaryIO:
        """Open the stored file for reading."""

    @abstractmethod
    def size(self, *, tenant_id: uuid.UUID, file_key: str) -> int:
        """Return the file size in bytes."""

    @abstractmethod
    def delete(self, *, tenant_id: uuid.UUID, file_key: str) -> None:
        """Remove the stored file. No-op if the file does not exist."""


class LocalDiskStore(DocumentStore):
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, tenant_id: uuid.UUID, file_key: str) -> Path:
        safe_key = Path(file_key).name  # no traversal
        return self.root / str(tenant_id) / safe_key

    async def put(
        self, *, tenant_id: uuid.UUID, data: bytes
    ) -> tuple[str, str]:
        sha = hashlib.sha256(data).hexdigest()
        file_key = sha  # content-addressable
        path = self._path(tenant_id, file_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_bytes(data)
        return file_key, sha

    def open(self, *, tenant_id: uuid.UUID, file_key: str) -> BinaryIO:
        return self._path(tenant_id, file_key).open("rb")

    def size(self, *, tenant_id: uuid.UUID, file_key: str) -> int:
        return self._path(tenant_id, file_key).stat().st_size

    def delete(self, *, tenant_id: uuid.UUID, file_key: str) -> None:
        path = self._path(tenant_id, file_key)
        path.unlink(missing_ok=True)


def get_document_store() -> DocumentStore:
    from app.config import get_settings

    settings = get_settings()
    if settings.document_store == "local":
        return LocalDiskStore(settings.local_store_path)
    raise ValueError(f"unsupported document_store: {settings.document_store}")
