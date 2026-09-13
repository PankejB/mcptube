"""YouTube video ingestion via yt-dlp."""

import json
import logging
import re
import time
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse
from urllib.request import urlopen

import yt_dlp

from mcptube.models import Chapter, TranscriptSegment, Video

logger = logging.getLogger(__name__)


class ExtractionError(Exception):
    """Raised when video extraction fails."""


class TranscriptThrottledError(ExtractionError):
    """Raised when YouTube rate-limits a caption download (HTTP 429/503).

    Distinct from a video that simply has no caption track: the transcript
    exists but could not be fetched right now. Callers should retry rather
    than persist an empty transcript, which would be indistinguishable from
    "no captions available".
    """


class YouTubeExtractor:
    """Extracts metadata and transcripts from YouTube videos via yt-dlp.

    Single responsibility: given a YouTube URL, return a populated Video model.
    All yt-dlp interaction is encapsulated here.
    """

    _URL_PATTERNS = [
        re.compile(r"(?:youtube\.com/watch\?.*v=)([\w-]{11})"),
        re.compile(r"(?:youtu\.be/)([\w-]{11})"),
        re.compile(r"(?:youtube\.com/embed/)([\w-]{11})"),
        re.compile(r"(?:youtube\.com/v/)([\w-]{11})"),
    ]

    _LANG_PREFERENCE = ("en", "en-orig", "en-US", "en-GB")

    # Backoff schedule (seconds) for rate-limited caption downloads.
    # Deliberately short — a sustained block needs minutes-to-hours, which
    # belongs to the caller, not to a blocking in-process sleep.
    _RETRY_DELAYS = (2, 5, 15)

    def extract(self, url: str) -> Video:
        """Extract metadata and transcript from a YouTube video URL.

        Args:
            url: YouTube video URL in any standard format.

        Returns:
            Populated Video model.

        Raises:
            ExtractionError: If extraction fails.
        """
        video_id = self.parse_video_id(url)
        info = self._fetch_info(url)
        transcript = self._extract_transcript(info)
        chapters = self._extract_chapters(info)

        return Video(
            video_id=video_id,
            title=info.get("title", ""),
            description=info.get("description", ""),
            channel=info.get("channel", "") or info.get("uploader", ""),
            duration=float(info.get("duration", 0) or 0),
            thumbnail_url=info.get("thumbnail", ""),
            chapters=chapters,
            transcript=transcript,
        )

    @classmethod
    def parse_video_id(cls, url: str) -> str:
        """Extract the 11-character video ID from a YouTube URL.

        Supports youtube.com/watch, youtu.be, /embed/, and /v/ formats.

        Raises:
            ExtractionError: If the URL cannot be parsed.
        """
        for pattern in cls._URL_PATTERNS:
            match = pattern.search(url)
            if match:
                return match.group(1)

        # Fallback: query parameter parsing
        parsed = urlparse(url)
        video_id = parse_qs(parsed.query).get("v", [None])[0]
        if video_id and len(video_id) == 11:
            return video_id

        raise ExtractionError(f"Could not extract video ID from URL: {url}")

    def _fetch_info(self, url: str) -> dict:
        """Fetch video info dict from yt-dlp without downloading media."""
        ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            "writesubtitles": True,
            "writeautomaticsub": True,
            "subtitleslangs": list(self._LANG_PREFERENCE),
            "subtitlesformat": "json3",
            "skip_download": True,
        }
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                if info is None:
                    raise ExtractionError(f"yt-dlp returned no info for: {url}")
                return info
        except yt_dlp.utils.DownloadError as e:
            raise ExtractionError(f"Failed to extract video info: {e}") from e

    def _extract_transcript(self, info: dict) -> list[TranscriptSegment]:
        """Extract transcript segments, preferring manual over auto-generated."""
        subtitles = info.get("subtitles") or {}
        auto_captions = info.get("automatic_captions") or {}

        sub_data = self._find_json3(subtitles) or self._find_json3(auto_captions)
        if not sub_data:
            logger.warning("No English transcript available for: %s", info.get("id"))
            return []

        return self._parse_json3(sub_data)

    def _find_json3(self, subs: dict) -> dict | None:
        """Find and download json3 subtitle data for the best English variant."""
        # Try preferred language codes first
        for lang in self._LANG_PREFERENCE:
            data = self._get_json3_for_lang(subs, lang)
            if data:
                return data

        # Fallback: any en-* variant
        for lang in subs:
            if lang.startswith("en"):
                data = self._get_json3_for_lang(subs, lang)
                if data:
                    return data

        return None

    def _get_json3_for_lang(self, subs: dict, lang: str) -> dict | None:
        """Download json3 data for a specific language code if available."""
        formats = subs.get(lang)
        if not formats:
            return None
        for fmt in formats:
            if fmt.get("ext") == "json3":
                return self._download_json(fmt["url"])
        return None

    def _download_json(self, url: str) -> dict | None:
        """Download and parse JSON from a URL.

        Retries with backoff on rate-limiting, then raises so the caller can
        tell "throttled" apart from "no such captions". Other failures are
        logged and reported as None (the caption track is unusable, but that
        is not evidence of throttling).

        Raises:
            TranscriptThrottledError: If YouTube rate-limits the download
                (HTTP 429/503) on every attempt.
        """
        last_code = None
        for attempt, delay in enumerate(self._RETRY_DELAYS, start=1):
            try:
                with urlopen(url, timeout=30) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except HTTPError as e:
                if e.code not in (429, 503):
                    logger.warning("Failed to download subtitle data: %s", e)
                    return None
                last_code = e.code
                if attempt < len(self._RETRY_DELAYS):
                    logger.warning(
                        "Subtitle download rate-limited (HTTP %s); retrying in %ss",
                        e.code,
                        delay,
                    )
                    time.sleep(delay)
            except Exception as e:
                logger.warning("Failed to download subtitle data: %s", e)
                return None

        raise TranscriptThrottledError(
            f"YouTube rate-limited the caption download (HTTP {last_code}) — "
            "the transcript exists but could not be fetched. Retry later; "
            "do not treat this as 'no captions'."
        )

    def _parse_json3(self, data: dict) -> list[TranscriptSegment]:
        """Parse YouTube json3 subtitle format into TranscriptSegment list.

        YouTube json3 structure:
            {"events": [{"tStartMs": int, "dDurationMs": int, "segs": [{"utf8": str}]}]}
        """
        segments = []
        for event in data.get("events", []):
            segs = event.get("segs")
            if not segs:
                continue

            text = "".join(s.get("utf8", "") for s in segs).strip()
            if not text or text == "\n":
                continue

            start_ms = event.get("tStartMs", 0)
            duration_ms = event.get("dDurationMs", 0)

            segments.append(TranscriptSegment(
                start=start_ms / 1000.0,
                duration=duration_ms / 1000.0,
                text=text,
            ))

        return segments

    def _extract_chapters(self, info: dict) -> list[Chapter]:
        """Extract chapter markers when provided by the uploader."""
        return [
            Chapter(title=ch["title"], start=float(ch.get("start_time", 0)))
            for ch in (info.get("chapters") or [])
            if ch.get("title")
        ]
