"""Read only explicitly allowed, size-limited JSON fixtures."""

import json
from pathlib import Path
from typing import Any

from app.schemas.profile import ProfileData
from app.tools.errors import ToolFailure

MAX_LOCAL_BYTES = 64 * 1024
ALLOWED_FILES = frozenset({"profile.json", "job_samples.json"})


def read_allowed_json(data_dir: Path, filename: str) -> Any:
    if filename not in ALLOWED_FILES:
        raise ToolFailure("FILE_NOT_ALLOWED", "Only the configured demo data files can be read.")
    root = data_dir.resolve()
    target = root / filename
    if target.resolve() != target:
        raise ToolFailure("FILE_NOT_ALLOWED", "Linked data files are not allowed.")
    try:
        with target.open("rb") as stream:
            content = stream.read(MAX_LOCAL_BYTES + 1)
    except FileNotFoundError:
        raise ToolFailure("DATA_NOT_FOUND", "The configured demo data file is missing.") from None
    except OSError:
        raise ToolFailure("DATA_UNREADABLE", "The configured demo data file could not be read.") from None
    if len(content) > MAX_LOCAL_BYTES:
        raise ToolFailure("DATA_TOO_LARGE", "The demo data file exceeds the size limit.")
    try:
        return json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ToolFailure("DATA_INVALID", "The demo data file is not valid UTF-8 JSON.") from None


def read_profile(data_dir: Path) -> ProfileData:
    return ProfileData.model_validate(read_allowed_json(data_dir, "profile.json"))
