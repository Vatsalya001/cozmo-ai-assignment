"""Tier detection: the brief requires one command per capture, so the pipeline works out
which of the three tiers it was handed rather than asking the user to say.
"""
from __future__ import annotations

from pathlib import Path

VIDEO_SUFFIXES = {".mov", ".mp4", ".m4v"}
PHOTO_SUFFIXES = {".heic", ".heif", ".jpg", ".jpeg", ".png"}
STRAY_MARKERS = ("odometry.csv", "camera_matrix.csv")


class CaptureError(ValueError):
    """The input is not a capture this pipeline can read."""


def _holds_photos(directory: Path) -> bool:
    """True if the directory directly contains stills. Unreadable directories are simply not
    photo folders: a permission error somewhere under the input must never surface as a
    traceback, because the walk-in test is a live cold run."""
    try:
        return any(f.suffix.lower() in PHOTO_SUFFIXES for f in directory.iterdir())
    except OSError:
        return False


def _safe_iterdir(path: Path) -> list[Path]:
    try:
        return sorted(path.iterdir())
    except OSError as e:
        raise CaptureError(f"{path}: cannot be read ({e.strerror})") from e


def detect_tier(path) -> str:
    path = Path(path)
    if not path.exists():
        raise CaptureError(f"{path} does not exist")

    if path.is_file():
        if path.suffix.lower() in VIDEO_SUFFIXES:
            return "video"
        raise CaptureError(f"{path}: not a video; expected one of {sorted(VIDEO_SUFFIXES)}")

    if all((path / marker).is_file() for marker in STRAY_MARKERS):
        return "lidar"

    # A folder of per-room folders, each holding stills.
    entries = _safe_iterdir(path)
    if [d for d in entries if d.is_dir() and _holds_photos(d)]:
        return "photo"

    if any(f.suffix.lower() in PHOTO_SUFFIXES for f in entries):
        raise CaptureError(
            f"{path} holds photos directly. The photo tier expects one folder per room, "
            f"e.g. {path.name}/kitchen/*.heic -- see docs/capture_protocol.md")

    raise CaptureError(f"{path}: not a Stray Scanner export, a video, or a folder of room photo folders")


def room_folders(path) -> list[Path]:
    """The per-room folders of a photo-tier capture, in a stable order."""
    return [d for d in _safe_iterdir(Path(path)) if d.is_dir() and _holds_photos(d)]
