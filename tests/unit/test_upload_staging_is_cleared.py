"""An uploaded document must not outlive the ingest that consumed it.

`UPLOAD_FOLDER` is a staging area, not a store. A file is written there, ingested,
and deleted — twice over, by `_stream_file_ingest` and again in the upload stream's
`finally`. Nothing reads it back; the durable copy of a document is its extracted
text and embeddings in PostgreSQL.

Both deletions are in-process, so a crash, an OOM kill or a container stop between
write and ingest leaves the file behind. On a container's ephemeral filesystem that
clears itself. On a host with a mounted volume the documents accumulate for as long
as the deployment lives, readable by anything that can reach the disk — which is the
case this covers.

Nothing on a cold start can still be mid-ingest, so everything present at startup is
by definition an orphan.
"""

import os

import pytest

from src.app_bootstrap import _clear_upload_staging

pytestmark = pytest.mark.unit


@pytest.fixture
def staging(tmp_path, monkeypatch):
    folder = tmp_path / "uploads"
    folder.mkdir()
    monkeypatch.setattr("src.config.UPLOAD_FOLDER", str(folder))
    return folder


class TestOrphansLeftByAnInterruptedIngest:
    def test_every_staged_file_is_removed(self, staging):
        for name in ("contract.pdf", "notes.md", "sheet.xlsx"):
            (staging / name).write_text("sensitive")

        _clear_upload_staging()

        assert list(staging.iterdir()) == []

    def test_the_directory_itself_survives(self, staging):
        """The next upload writes straight into it; recreating it is not this code's job."""
        (staging / "leftover.txt").write_text("x")

        _clear_upload_staging()

        assert staging.is_dir()

    def test_subdirectories_are_left_alone(self, staging):
        """Only files are staged. Anything else was put there deliberately."""
        nested = staging / "keepme"
        nested.mkdir()
        (nested / "inner.txt").write_text("x")
        (staging / "orphan.pdf").write_text("x")

        _clear_upload_staging()

        assert nested.is_dir() and (nested / "inner.txt").exists()
        assert not (staging / "orphan.pdf").exists()


class TestItNeverStopsTheApplication:
    def test_a_missing_folder_is_not_an_error(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.config.UPLOAD_FOLDER", str(tmp_path / "absent"))

        _clear_upload_staging()  # must not raise

    def test_an_undeletable_file_is_logged_and_skipped(self, staging, monkeypatch, caplog):
        """A leftover that cannot be removed must not prevent startup."""
        (staging / "stuck.pdf").write_text("x")
        (staging / "fine.pdf").write_text("x")

        real_remove = os.remove

        def refuse(path, *args, **kwargs):
            if path.endswith("stuck.pdf"):
                raise PermissionError("in use")
            return real_remove(path, *args, **kwargs)

        monkeypatch.setattr("src.app_bootstrap.os.remove", refuse)

        with caplog.at_level("WARNING"):
            _clear_upload_staging()

        assert (staging / "stuck.pdf").exists(), "the undeletable one is still there"
        assert not (staging / "fine.pdf").exists(), "the sweep continued past the failure"
        assert "stuck.pdf" in caplog.text


class TestAnEmptyStagingArea:
    def test_a_clean_start_reports_nothing(self, staging, caplog):
        with caplog.at_level("INFO"):
            _clear_upload_staging()

        assert "Cleared" not in caplog.text, "a normal start should be silent"
