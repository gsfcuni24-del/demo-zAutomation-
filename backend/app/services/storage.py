"""Local filesystem storage for uploads (temporary until S3/MinIO is introduced)."""

import re
import uuid
from dataclasses import dataclass
from pathlib import Path

import anyio
from fastapi import UploadFile

from app.core.config import settings

CHUNK_SIZE = 1024 * 1024
_UNSAFE_CHARS = re.compile(r"[^A-Za-z0-9._-]+")


class StorageError(Exception):
    """Base class for upload validation/storage failures."""


class UnsupportedFileTypeError(StorageError):
    pass


class FileTooLargeError(StorageError):
    pass


class EmptyFileError(StorageError):
    pass


@dataclass(frozen=True, slots=True)
class StoredFile:
    filename: str
    path: Path
    size_bytes: int


def sanitize_filename(filename: str) -> str:
    name = Path(filename.replace("\\", "/")).name
    cleaned = _UNSAFE_CHARS.sub("_", name).strip("._")
    return cleaned[:200] or "upload"


class LocalFileStorage:
    def __init__(self, root: Path, max_bytes: int, allowed_extensions: list[str]) -> None:
        self.root = root
        self.max_bytes = max_bytes
        self.allowed_extensions = {ext.lower() for ext in allowed_extensions}

    async def save(self, upload: UploadFile, project_id: uuid.UUID) -> StoredFile:
        original = sanitize_filename(upload.filename or "")
        suffix = Path(original).suffix.lower()
        if suffix not in self.allowed_extensions:
            allowed = ", ".join(sorted(self.allowed_extensions))
            raise UnsupportedFileTypeError(f"Unsupported file type {suffix!r}. Allowed: {allowed}")

        directory = anyio.Path(self.root) / str(project_id)
        await directory.mkdir(parents=True, exist_ok=True)
        target = directory / f"{uuid.uuid4().hex}_{original}"

        size = 0
        try:
            async with await anyio.open_file(target, "wb") as out:
                while chunk := await upload.read(CHUNK_SIZE):
                    size += len(chunk)
                    if size > self.max_bytes:
                        raise FileTooLargeError(
                            f"File exceeds the {self.max_bytes // (1024 * 1024)} MB upload limit"
                        )
                    await out.write(chunk)
            if size == 0:
                raise EmptyFileError("Uploaded file is empty")
        except BaseException:
            await target.unlink(missing_ok=True)
            raise
        return StoredFile(filename=original, path=Path(target), size_bytes=size)

    async def delete(self, path: Path) -> None:
        await anyio.Path(path).unlink(missing_ok=True)


def get_storage() -> LocalFileStorage:
    return LocalFileStorage(
        root=settings.UPLOAD_DIR,
        max_bytes=settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024,
        allowed_extensions=settings.ALLOWED_UPLOAD_EXTENSIONS,
    )
