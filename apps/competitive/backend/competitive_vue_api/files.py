import os
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4


CHUNK_SIZE = 1024 * 1024
DEFAULT_MAX_UPLOAD_BYTES = 200 * 1024 * 1024
ALLOWED_FILE_TYPES: dict[str, frozenset[str]] = {
    "image/jpeg": frozenset({".jpg", ".jpeg"}),
    "image/png": frozenset({".png"}),
    "image/webp": frozenset({".webp"}),
    "image/heic": frozenset({".heic", ".heif"}),
    "image/heif": frozenset({".heic", ".heif"}),
    "video/mp4": frozenset({".mp4"}),
    "video/quicktime": frozenset({".mov"}),
    "application/pdf": frozenset({".pdf"}),
    "application/msword": frozenset({".doc"}),
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": frozenset(
        {".docx"}
    ),
    "application/vnd.ms-excel": frozenset({".xls"}),
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": frozenset(
        {".xlsx"}
    ),
    "application/vnd.ms-powerpoint": frozenset({".ppt"}),
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": frozenset(
        {".pptx"}
    ),
}
ALLOWED_SUFFIXES = frozenset(
    suffix for suffixes in ALLOWED_FILE_TYPES.values() for suffix in suffixes
)


class InvalidFileError(ValueError):
    pass


class UnsupportedFileTypeError(InvalidFileError):
    pass


class FileTooLargeError(InvalidFileError):
    def __init__(self, max_bytes: int):
        self.max_bytes = max_bytes
        limit = (
            f"{max_bytes // (1024 * 1024)}MB"
            if max_bytes % (1024 * 1024) == 0
            else f"{max_bytes}字节"
        )
        super().__init__(f"单个附件不能超过{limit}")


@dataclass(frozen=True, slots=True)
class StoredFile:
    storage_key: str
    original_name: str
    content_type: str
    size: int
    path: Path


def upload_directory() -> Path:
    return Path(os.getenv("UPLOAD_DIR", "/app/uploads")).resolve()


def safe_storage_path(storage_key: str) -> Path:
    storage_path = Path(storage_key)
    try:
        identifier = UUID(storage_path.stem)
    except (AttributeError, ValueError):
        raise InvalidFileError("Invalid storage key") from None
    if (
        not storage_key
        or "/" in storage_key
        or "\\" in storage_key
        or identifier.hex != storage_path.stem
        or storage_path.suffix.lower() not in ALLOWED_SUFFIXES
    ):
        raise InvalidFileError("Invalid storage key")
    target = (upload_directory() / storage_key).resolve()
    if upload_directory() not in target.parents:
        raise InvalidFileError("Invalid storage key")
    return target


def save_upload(upload, max_bytes: int | None = None) -> StoredFile:
    original_name = Path((upload.name or "").replace("\\", "/")).name
    if not original_name or original_name in {".", ".."}:
        raise InvalidFileError("A valid filename is required")
    content_type = str(upload.content_type or "").lower().strip()
    suffix = Path(original_name).suffix.lower()
    if suffix not in ALLOWED_FILE_TYPES.get(content_type, frozenset()):
        raise UnsupportedFileTypeError(
            f"Unsupported file type: {content_type or 'missing content type'} ({suffix or 'no suffix'})"
        )
    size_limit = max_bytes if max_bytes is not None else int(
        os.getenv("MAX_UPLOAD_BYTES", str(DEFAULT_MAX_UPLOAD_BYTES))
    )
    destination = upload_directory()
    destination.mkdir(parents=True, exist_ok=True)
    identifier = uuid4().hex
    storage_key = f"{identifier}{suffix}"
    final_path = destination / storage_key
    temporary_path = destination / f".{identifier}.tmp"
    total_size = 0
    try:
        with temporary_path.open("xb") as target:
            for chunk in upload.chunks(CHUNK_SIZE):
                total_size += len(chunk)
                if total_size > size_limit:
                    raise FileTooLargeError(size_limit)
                target.write(chunk)
            target.flush()
            os.fsync(target.fileno())
        os.replace(temporary_path, final_path)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise
    return StoredFile(storage_key, original_name, content_type, total_size, final_path)


def delete_stored_file(storage_key: str) -> bool:
    target = safe_storage_path(storage_key)
    try:
        target.unlink()
    except FileNotFoundError:
        return False
    return True
