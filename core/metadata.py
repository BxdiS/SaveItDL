from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def embed_audio_metadata(
    file_path: Path,
    title: str | None = None,
    artist: str | None = None,
    album: str | None = None,
    date: str | None = None,
    track_number: str | None = None,
    genre: str | None = None,
    url: str | None = None,
) -> bool:
    try:
        from mutagen.mp3 import MP3
        from mutagen.id3 import ID3, TIT2, TPE1, TALB, TDRC, TRCK, TCON, WXXX, ID3NoHeaderError
        from mutagen.oggvorbis import OggVorbis
        from mutagen.mp4 import MP4
        from mutagen.flac import FLAC
    except ImportError:
        logger.warning("mutagen not installed, skipping metadata")
        return False

    ext = file_path.suffix.lower()

    try:
        if ext == ".mp3":
            return _tag_mp3(file_path, title, artist, album, date, track_number, genre, url)
        elif ext == ".m4a":
            return _tag_m4a(file_path, title, artist, album, date)
        elif ext == ".ogg" or ext == ".opus":
            return _tag_ogg(file_path, title, artist, album, date)
        elif ext == ".flac":
            return _tag_flac(file_path, title, artist, album, date)
    except Exception:
        logger.exception("Failed to embed metadata in %s", file_path)
    return False


def _tag_mp3(path, title, artist, album, date, track_number, genre, url) -> bool:
    from mutagen.mp3 import MP3
    from mutagen.id3 import ID3, TIT2, TPE1, TALB, TDRC, TRCK, TCON, WXXX, ID3NoHeaderError

    try:
        audio = MP3(path)
    except Exception:
        return False

    if audio.tags is None:
        audio.add_tags()

    tags = audio.tags
    if title:
        tags.add(TIT2(encoding=3, text=title))
    if artist:
        tags.add(TPE1(encoding=3, text=artist))
    if album:
        tags.add(TALB(encoding=3, text=album))
    if date:
        tags.add(TDRC(encoding=3, text=date))
    if track_number:
        tags.add(TRCK(encoding=3, text=track_number))
    if genre:
        tags.add(TCON(encoding=3, text=genre))
    if url:
        tags.add(WXXX(encoding=3, desc="Source", url=url))

    audio.save()
    return True


def _tag_m4a(path, title, artist, album, date) -> bool:
    from mutagen.mp4 import MP4

    audio = MP4(path)
    if title:
        audio["\xa9nam"] = [title]
    if artist:
        audio["\xa9ART"] = [artist]
    if album:
        audio["\xa9alb"] = [album]
    if date:
        audio["\xa9day"] = [date]
    audio.save()
    return True


def _tag_ogg(path, title, artist, album, date) -> bool:
    from mutagen.oggvorbis import OggVorbis
    from mutagen.oggopus import OggOpus

    ext = Path(path).suffix.lower()
    audio = OggOpus(path) if ext == ".opus" else OggVorbis(path)
    if title:
        audio["title"] = [title]
    if artist:
        audio["artist"] = [artist]
    if album:
        audio["album"] = [album]
    if date:
        audio["date"] = [date]
    audio.save()
    return True


def _tag_flac(path, title, artist, album, date) -> bool:
    from mutagen.flac import FLAC

    audio = FLAC(path)
    if title:
        audio["title"] = [title]
    if artist:
        audio["artist"] = [artist]
    if album:
        audio["album"] = [album]
    if date:
        audio["date"] = [date]
    audio.save()
    return True


def extract_metadata_from_info(info: dict) -> dict:
    return {
        "title": info.get("track") or info.get("title"),
        "artist": info.get("artist") or info.get("creator") or info.get("uploader"),
        "album": info.get("album"),
        "date": info.get("release_date") or info.get("upload_date"),
        "track_number": str(info.get("track_number")) if info.get("track_number") else None,
        "genre": info.get("genre"),
    }
