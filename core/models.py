from __future__ import annotations

import enum
from dataclasses import dataclass, field
from pathlib import Path


class MediaFormat(enum.Enum):
    VIDEO = "video"
    AUDIO = "audio"


class DownloadStatus(enum.Enum):
    PENDING = "pending"
    DOWNLOADING = "downloading"
    PROCESSING = "processing"
    DONE = "done"
    FAILED = "failed"


@dataclass
class MediaInfo:
    url: str
    title: str
    duration: int | None = None
    thumbnail: str | None = None
    uploader: str | None = None
    platform: str | None = None
    formats: list[FormatOption] = field(default_factory=list)


@dataclass
class FormatOption:
    format_id: str
    ext: str
    quality: str
    filesize: int | None = None
    is_audio_only: bool = False


@dataclass
class DownloadResult:
    success: bool
    file_path: Path | None = None
    title: str | None = None
    duration: int | None = None
    filesize: int | None = None
    error: str | None = None
    thumbnail: str | None = None
