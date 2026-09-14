# tests/test_config.py
"""Tests for mcptube configuration."""

from pathlib import Path
from unittest.mock import patch

from mcptube.config import Settings


class TestSettings:
    def test_default_settings(self):
        s = Settings()
        assert s.host == "127.0.0.1"
        assert s.port == 9093
        assert s.data_dir == Path.home() / ".mcptube"

    def test_db_path_derived(self):
        s = Settings()
        assert s.db_path == s.data_dir / "mcptube.db"

    def test_frames_dir_default(self):
        s = Settings()
        assert s.frames_dir == s.data_dir / "frames"

    def test_frames_dir_override(self):
        s = Settings(frames_dir=Path("/tmp/custom_frames"))
        assert s.frames_dir == Path("/tmp/custom_frames")

    def test_wiki_dir_default(self):
        s = Settings()
        assert s.wiki_dir == s.data_dir / "wiki"

    def test_wiki_db_default(self):
        s = Settings()
        assert s.wiki_db == s.wiki_dir / "wiki.db"

    def test_wiki_dir_override_moves_db_with_it(self):
        """wiki_db is derived from wiki_dir, so overriding one moves the other."""
        s = Settings(wiki_dir=Path("/tmp/custom_wiki"))
        assert s.wiki_dir == Path("/tmp/custom_wiki")
        assert s.wiki_db == Path("/tmp/custom_wiki") / "wiki.db"

    def test_wiki_db_explicit_override_wins(self):
        s = Settings(wiki_dir=Path("/tmp/w"), wiki_db=Path("/tmp/elsewhere/custom.db"))
        assert s.wiki_db == Path("/tmp/elsewhere/custom.db")

    def test_wiki_dir_env_override(self):
        with patch.dict("os.environ", {"MCPTUBE_WIKI_DIR": "/tmp/env_wiki"}):
            s = Settings()
            assert s.wiki_dir == Path("/tmp/env_wiki")
            assert s.wiki_db == Path("/tmp/env_wiki") / "wiki.db"

    def test_ensure_dirs_creates(self, tmp_path):
        s = Settings(data_dir=tmp_path / "testdata")
        s.ensure_dirs()
        assert s.data_dir.exists()
        assert s.frames_dir.exists()

    def test_env_override(self):
        with patch.dict("os.environ", {"MCPTUBE_PORT": "1234"}):
            s = Settings()
            assert s.port == 1234
