from pathlib import Path

from app.core.config import settings


def ensure_storage_dirs() -> None:
    Path(settings.upload_dir).mkdir(parents=True, exist_ok=True)
    Path(settings.library_dir).mkdir(parents=True, exist_ok=True)
