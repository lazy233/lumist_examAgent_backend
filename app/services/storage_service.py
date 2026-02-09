import asyncio
import hashlib
import shutil
from pathlib import Path
from typing import BinaryIO, Tuple

from app.core.config import settings
from app.models.doc import Doc
from app.core.storage import ensure_storage_dirs


def _file_hash_and_size(file_obj: BinaryIO) -> Tuple[str, int]:
    hasher = hashlib.sha256()
    size = 0
    for chunk in iter(lambda: file_obj.read(1024 * 1024), b""):
        hasher.update(chunk)
        size += len(chunk)
    return hasher.hexdigest(), size


def save_upload(file_obj: BinaryIO, filename: str, doc_id: str) -> Tuple[str, str, int]:
    ensure_storage_dirs()
    target_path = Path(settings.upload_dir) / f"{doc_id}_{filename}"
    file_obj.seek(0)
    with target_path.open("wb") as f:
        shutil.copyfileobj(file_obj, f)
    file_obj.seek(0)
    file_hash, file_size = _file_hash_and_size(file_obj)
    return str(target_path), file_hash, file_size


def save_to_library(source_path: str, doc_id: str, filename: str) -> str:
    ensure_storage_dirs()
    target_path = Path(settings.library_dir) / f"{doc_id}_{filename}"
    shutil.copy2(source_path, target_path)
    return str(target_path)


def delete_doc_files(doc: Doc) -> None:
    """Delete physical files for a doc (upload + library copy if any)."""
    if doc.file_path:
        p = Path(doc.file_path)
        if p.exists():
            try:
                p.unlink()
            except OSError:
                pass
    if doc.save_to_library:
        lib_path = Path(settings.library_dir) / f"{doc.id}_{doc.file_name}"
        if lib_path.exists():
            try:
                lib_path.unlink()
            except OSError:
                pass


def _save_upload_sync(file_obj: BinaryIO, filename: str, doc_id: str) -> Tuple[str, str, int]:
    return save_upload(file_obj, filename, doc_id)


def _save_to_library_sync(source_path: str, doc_id: str, filename: str) -> str:
    return save_to_library(source_path, doc_id, filename)


def _delete_doc_files_sync(doc: Doc) -> None:
    return delete_doc_files(doc)


async def save_upload_async(file_obj: BinaryIO, filename: str, doc_id: str) -> Tuple[str, str, int]:
    return await asyncio.to_thread(_save_upload_sync, file_obj, filename, doc_id)


async def save_to_library_async(source_path: str, doc_id: str, filename: str) -> str:
    return await asyncio.to_thread(_save_to_library_sync, source_path, doc_id, filename)


async def delete_doc_files_async(doc: Doc) -> None:
    await asyncio.to_thread(_delete_doc_files_sync, doc)
