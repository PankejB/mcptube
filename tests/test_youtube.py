# tests/test_youtube.py
"""Tests for YouTube video extraction."""

import json
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError

import pytest
import yt_dlp

from mcptube.ingestion.youtube import (
    ExtractionError,
    TranscriptThrottledError,
    YouTubeExtractor,
)


class TestParseVideoId:
    def test_watch_url(self):
        assert YouTubeExtractor.parse_video_id("https://www.youtube.com/watch?v=BpibZSMGtdY") == "BpibZSMGtdY"

    def test_short_url(self):
        assert YouTubeExtractor.parse_video_id("https://youtu.be/BpibZSMGtdY") == "BpibZSMGtdY"

    def test_embed_url(self):
        assert YouTubeExtractor.parse_video_id("https://www.youtube.com/embed/BpibZSMGtdY") == "BpibZSMGtdY"

    def test_v_path_url(self):
        assert YouTubeExtractor.parse_video_id("https://www.youtube.com/v/BpibZSMGtdY") == "BpibZSMGtdY"

    def test_watch_url_with_extras(self):
        url = "https://www.youtube.com/watch?v=BpibZSMGtdY&t=120&list=PLxyz"
        assert YouTubeExtractor.parse_video_id(url) == "BpibZSMGtdY"

    def test_invalid_url(self):
        with pytest.raises(ExtractionError):
            YouTubeExtractor.parse_video_id("https://example.com/not-youtube")


class TestExtract:
    def _make_info(self, *, subtitles=None, auto_captions=None, chapters=None):
        return {
            "id": "BpibZSMGtdY",
            "title": "Test Video",
            "description": "A test video",
            "channel": "TestChannel",
            "uploader": "TestUploader",
            "duration": 120,
            "thumbnail": "https://i.ytimg.com/vi/BpibZSMGtdY/maxresdefault.jpg",
            "subtitles": subtitles or {},
            "automatic_captions": auto_captions or {},
            "chapters": chapters,
        }

    def _make_json3(self, segments):
        """Build a json3 subtitle structure from (start_ms, duration_ms, text) tuples."""
        return {
            "events": [
                {"tStartMs": s, "dDurationMs": d, "segs": [{"utf8": t}]}
                for s, d, t in segments
            ]
        }

    def _sub_entry(self, url="https://example.com/subs.json3"):
        return {"en": [{"ext": "json3", "url": url}]}

    @patch("mcptube.ingestion.youtube.urlopen")
    @patch("mcptube.ingestion.youtube.yt_dlp.YoutubeDL")
    def test_extract_returns_video(self, mock_ydl_class, mock_urlopen):
        json3 = self._make_json3([(0, 5000, "Hello"), (5000, 4000, "World")])
        import json
        mock_urlopen.return_value.__enter__ = lambda s: s
        mock_urlopen.return_value.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value.read.return_value = json.dumps(json3).encode()

        info = self._make_info(subtitles=self._sub_entry())
        mock_ydl = MagicMock()
        mock_ydl.extract_info.return_value = info
        mock_ydl_class.return_value.__enter__ = lambda s: mock_ydl
        mock_ydl_class.return_value.__exit__ = MagicMock(return_value=False)

        extractor = YouTubeExtractor()
        video = extractor.extract("https://www.youtube.com/watch?v=BpibZSMGtdY")

        assert video.video_id == "BpibZSMGtdY"
        assert video.title == "Test Video"
        assert video.channel == "TestChannel"
        assert video.duration == 120.0
        assert len(video.transcript) == 2
        assert video.transcript[0].text == "Hello"

    @patch("mcptube.ingestion.youtube.yt_dlp.YoutubeDL")
    def test_extract_with_chapters(self, mock_ydl_class):
        chapters = [
            {"title": "Intro", "start_time": 0},
            {"title": "Main", "start_time": 30},
        ]
        info = self._make_info(chapters=chapters)
        mock_ydl = MagicMock()
        mock_ydl.extract_info.return_value = info
        mock_ydl_class.return_value.__enter__ = lambda s: mock_ydl
        mock_ydl_class.return_value.__exit__ = MagicMock(return_value=False)

        extractor = YouTubeExtractor()
        video = extractor.extract("https://www.youtube.com/watch?v=BpibZSMGtdY")
        assert len(video.chapters) == 2
        assert video.chapters[0].title == "Intro"
        assert video.chapters[1].start == 30.0

    @patch("mcptube.ingestion.youtube.yt_dlp.YoutubeDL")
    def test_extract_no_transcript(self, mock_ydl_class):
        info = self._make_info()
        mock_ydl = MagicMock()
        mock_ydl.extract_info.return_value = info
        mock_ydl_class.return_value.__enter__ = lambda s: mock_ydl
        mock_ydl_class.return_value.__exit__ = MagicMock(return_value=False)

        extractor = YouTubeExtractor()
        video = extractor.extract("https://www.youtube.com/watch?v=BpibZSMGtdY")
        assert video.transcript == []

    @patch("mcptube.ingestion.youtube.urlopen")
    @patch("mcptube.ingestion.youtube.yt_dlp.YoutubeDL")
    def test_extract_prefers_manual_subs(self, mock_ydl_class, mock_urlopen):
        import json
        manual_json3 = self._make_json3([(0, 5000, "Manual sub")])
        mock_urlopen.return_value.__enter__ = lambda s: s
        mock_urlopen.return_value.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value.read.return_value = json.dumps(manual_json3).encode()

        info = self._make_info(
            subtitles=self._sub_entry(),
            auto_captions={"en": [{"ext": "json3", "url": "https://example.com/auto.json3"}]},
        )
        mock_ydl = MagicMock()
        mock_ydl.extract_info.return_value = info
        mock_ydl_class.return_value.__enter__ = lambda s: mock_ydl
        mock_ydl_class.return_value.__exit__ = MagicMock(return_value=False)

        extractor = YouTubeExtractor()
        video = extractor.extract("https://www.youtube.com/watch?v=BpibZSMGtdY")
        assert video.transcript[0].text == "Manual sub"

    @patch("mcptube.ingestion.youtube.yt_dlp.YoutubeDL")
    def test_extract_download_error(self, mock_ydl_class):
        mock_ydl = MagicMock()
        mock_ydl.extract_info.side_effect = yt_dlp.utils.DownloadError("Network error")
        mock_ydl_class.return_value.__enter__ = lambda s: mock_ydl
        mock_ydl_class.return_value.__exit__ = MagicMock(return_value=False)

        extractor = YouTubeExtractor()
        with pytest.raises(ExtractionError, match="Failed to extract"):
            extractor.extract("https://www.youtube.com/watch?v=BpibZSMGtdY")


class TestParseJson3:
    def test_parse_segments(self):
        extractor = YouTubeExtractor()
        data = {
            "events": [
                {"tStartMs": 1000, "dDurationMs": 3000, "segs": [{"utf8": "Hello"}]},
                {"tStartMs": 4000, "dDurationMs": 2000, "segs": [{"utf8": "World"}]},
            ]
        }
        segments = extractor._parse_json3(data)
        assert len(segments) == 2
        assert segments[0].start == 1.0
        assert segments[0].duration == 3.0
        assert segments[0].text == "Hello"

    def test_empty_segments_skipped(self):
        extractor = YouTubeExtractor()
        data = {
            "events": [
                {"tStartMs": 0, "dDurationMs": 1000, "segs": [{"utf8": ""}]},
                {"tStartMs": 1000, "dDurationMs": 1000, "segs": [{"utf8": "\n"}]},
                {"tStartMs": 2000, "dDurationMs": 1000, "segs": [{"utf8": "Real text"}]},
            ]
        }
        segments = extractor._parse_json3(data)
        assert len(segments) == 1
        assert segments[0].text == "Real text"


class TestDownloadJsonThrottling:
    """Caption downloads must distinguish rate-limiting from missing captions."""

    @patch("mcptube.ingestion.youtube.time.sleep")
    @patch("mcptube.ingestion.youtube.urlopen")
    def test_raises_throttled_after_exhausting_retries(self, mock_urlopen, mock_sleep):
        mock_urlopen.side_effect = HTTPError("url", 429, "Too Many Requests", {}, None)
        extractor = YouTubeExtractor()

        with pytest.raises(TranscriptThrottledError) as exc:
            extractor._download_json("https://example.com/subs.json")

        assert "429" in str(exc.value)
        assert mock_urlopen.call_count == len(YouTubeExtractor._RETRY_DELAYS)
        # Sleeps between attempts, but not after the final one.
        assert mock_sleep.call_count == len(YouTubeExtractor._RETRY_DELAYS) - 1

    @patch("mcptube.ingestion.youtube.time.sleep")
    @patch("mcptube.ingestion.youtube.urlopen")
    def test_retries_then_succeeds(self, mock_urlopen, mock_sleep):
        payload = json.dumps({"events": []}).encode("utf-8")
        ok = MagicMock()
        ok.read.return_value = payload
        ok.__enter__ = lambda s: s
        ok.__exit__ = lambda *a: None
        mock_urlopen.side_effect = [
            HTTPError("url", 503, "Service Unavailable", {}, None),
            ok,
        ]
        extractor = YouTubeExtractor()

        assert extractor._download_json("https://example.com/subs.json") == {"events": []}
        assert mock_urlopen.call_count == 2

    @patch("mcptube.ingestion.youtube.urlopen")
    def test_non_throttle_http_error_returns_none(self, mock_urlopen):
        """A 404 means the track is unusable — not evidence of throttling."""
        mock_urlopen.side_effect = HTTPError("url", 404, "Not Found", {}, None)
        extractor = YouTubeExtractor()

        assert extractor._download_json("https://example.com/subs.json") is None

    @patch("mcptube.ingestion.youtube.urlopen")
    def test_generic_error_returns_none(self, mock_urlopen):
        mock_urlopen.side_effect = ValueError("boom")
        extractor = YouTubeExtractor()

        assert extractor._download_json("https://example.com/subs.json") is None
