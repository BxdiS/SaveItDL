from __future__ import annotations

import asyncio
import logging
import tempfile
import uuid
from pathlib import Path
from typing import Callable

import yt_dlp

from core.metadata import embed_audio_metadata, extract_metadata_from_info
from core.models import DownloadResult, DownloadStatus, FormatOption, MediaFormat, MediaInfo

logger = logging.getLogger(__name__)

MAX_FILESIZE = 2 * 1024 * 1024 * 1024  # 2 GB hard limit


class Downloader:
    def __init__(self, temp_dir: str | None = None):
        self._temp_dir = temp_dir or tempfile.mkdtemp(prefix="alldl_")
        Path(self._temp_dir).mkdir(parents=True, exist_ok=True)

    def _base_opts(self) -> dict:
        return {
            "quiet": True,
            "no_warnings": True,
            "http_headers": {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/131.0.0.0 Safari/537.36"
                ),
            },
            "age_limit": None,
        }

    async def get_info(self, url: str) -> MediaInfo:
        opts = {
            **self._base_opts(),
            "skip_download": True,
        }
        loop = asyncio.get_event_loop()
        data = await loop.run_in_executor(None, self._extract_info, url, opts)

        formats = []
        for f in data.get("formats") or []:
            if not f.get("url"):
                continue
            is_audio = f.get("vcodec") in (None, "none")
            quality = f.get("format_note") or f.get("height") or f.get("abr") or "?"
            formats.append(FormatOption(
                format_id=f["format_id"],
                ext=f.get("ext", "mp4"),
                quality=str(quality),
                filesize=f.get("filesize") or f.get("filesize_approx"),
                is_audio_only=is_audio,
            ))

        return MediaInfo(
            url=url,
            title=data.get("title", "Untitled"),
            duration=data.get("duration"),
            thumbnail=data.get("thumbnail"),
            uploader=data.get("uploader"),
            platform=data.get("extractor_key"),
            formats=formats,
        )

    async def download(
        self,
        url: str,
        media_format: MediaFormat = MediaFormat.VIDEO,
        on_progress: Callable[[DownloadStatus, float], None] | None = None,
        format_id: str | None = None,
        download_range: tuple[int, int] | None = None,
    ) -> DownloadResult:
        file_id = uuid.uuid4().hex[:12]
        output_template = str(Path(self._temp_dir) / f"{file_id}.%(ext)s")

        opts: dict = {
            **self._base_opts(),
            "outtmpl": output_template,
            "noplaylist": True,
            "max_filesize": MAX_FILESIZE,
            "socket_timeout": 30,
            "retries": 3,
        }

        if format_id:
            opts["format"] = format_id
            if media_format == MediaFormat.AUDIO:
                opts["postprocessors"] = [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }]
            else:
                opts["merge_output_format"] = "mp4"
        elif media_format == MediaFormat.AUDIO:
            opts.update({
                "format": "bestaudio/best",
                "postprocessors": [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }],
            })
        else:
            opts["format"] = "bestvideo+bestaudio/best"
            opts["merge_output_format"] = "mp4"

        if download_range:
            start, end = download_range
            opts["download_ranges"] = lambda info, ydl: [(start, end)]

        if on_progress:
            opts["progress_hooks"] = [
                lambda d: self._handle_progress(d, on_progress)
            ]

        try:
            if on_progress:
                on_progress(DownloadStatus.DOWNLOADING, 0.0)

            loop = asyncio.get_event_loop()
            data = await loop.run_in_executor(None, self._run_download, url, opts)

            result_path = self._find_output(file_id)
            if not result_path:
                return DownloadResult(success=False, error="Downloaded file not found")

            if media_format == MediaFormat.AUDIO:
                meta = extract_metadata_from_info(data)
                embed_audio_metadata(result_path, url=url, **meta)

            if on_progress:
                on_progress(DownloadStatus.DONE, 100.0)

            return DownloadResult(
                success=True,
                file_path=result_path,
                title=data.get("title", "Untitled"),
                duration=data.get("duration"),
                filesize=result_path.stat().st_size,
                thumbnail=data.get("thumbnail"),
            )

        except yt_dlp.utils.DownloadError as e:
            msg = str(e)
            if "is not a valid URL" in msg:
                msg = "Invalid URL"
            elif "Unsupported URL" in msg:
                msg = "This site is not supported"
            logger.warning("Download failed for %s: %s", url, msg)
            return DownloadResult(success=False, error=msg)
        except Exception as e:
            logger.exception("Unexpected error downloading %s", url)
            return DownloadResult(success=False, error=str(e))

    def cleanup(self, result: DownloadResult) -> None:
        if result.file_path and result.file_path.exists():
            result.file_path.unlink(missing_ok=True)

    def _extract_info(self, url: str, opts: dict) -> dict:
        with yt_dlp.YoutubeDL(opts) as ydl:
            return ydl.extract_info(url, download=False) or {}

    def _run_download(self, url: str, opts: dict) -> dict:
        with yt_dlp.YoutubeDL(opts) as ydl:
            return ydl.extract_info(url, download=True) or {}

    def _find_output(self, file_id: str) -> Path | None:
        for f in Path(self._temp_dir).iterdir():
            if f.name.startswith(file_id) and f.is_file():
                return f
        return None

    @staticmethod
    def _handle_progress(d: dict, callback: Callable[[DownloadStatus, float], None]) -> None:
        if d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            downloaded = d.get("downloaded_bytes", 0)
            pct = (downloaded / total * 100) if total else 0.0
            callback(DownloadStatus.DOWNLOADING, pct)
        elif d.get("status") == "finished":
            callback(DownloadStatus.PROCESSING, 99.0)
