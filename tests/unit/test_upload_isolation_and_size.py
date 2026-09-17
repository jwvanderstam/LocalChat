"""P1-1 — one upload cannot reach, or delete, another's file; and none is unbounded.

Two audit findings in one code path:

* **H4** — every upload was written to ``UPLOAD_FOLDER/<sanitized name>``. Two
  workspaces uploading ``report.pdf`` shared one path, so one overwrote the other,
  one ingest could read the other's bytes, and whichever finished first deleted the
  file the other was still using.
* **M2** — the body was read with a single unbounded ``file.file.read()``.
  ``MAX_CONTENT_LENGTH`` existed but was applied to nothing, so an upload of any size
  was read into memory in full.
"""

from __future__ import annotations

import io
import os
from pathlib import Path

import pytest
from starlette.datastructures import Headers
from starlette.datastructures import UploadFile as StarletteUploadFile

from src.routes_fastapi.document_routes import UploadTooLargeError, _save_upload_file


def _upload(name: str, content: bytes) -> StarletteUploadFile:
    return StarletteUploadFile(
        file=io.BytesIO(content),
        filename=name,
        headers=Headers({"content-type": "text/plain"}),
    )


@pytest.fixture
def staging(tmp_path, monkeypatch):
    folder = tmp_path / "uploads"
    folder.mkdir()
    monkeypatch.setattr("src.config.UPLOAD_FOLDER", str(folder))
    return folder


@pytest.mark.unit
class TestTwoUploadsOfTheSameNameDoNotCollide:
    def test_they_land_on_different_paths(self, staging):
        first = _save_upload_file(_upload("report.txt", b"workspace A content"))
        second = _save_upload_file(_upload("report.txt", b"workspace B content"))

        assert first is not None and second is not None
        assert first != second

    def test_each_keeps_its_own_content(self, staging):
        """The failure H4 describes: one upload reading the other's bytes."""
        first = _save_upload_file(_upload("report.txt", b"workspace A content"))
        second = _save_upload_file(_upload("report.txt", b"workspace B content"))

        assert Path(first).read_bytes() == b"workspace A content"
        assert Path(second).read_bytes() == b"workspace B content"

    def test_cleaning_up_one_leaves_the_other(self, staging):
        """The other half: whichever finished first deleted the live file."""
        import shutil

        first = _save_upload_file(_upload("report.txt", b"A"))
        second = _save_upload_file(_upload("report.txt", b"B"))

        shutil.rmtree(os.path.dirname(first))

        assert not os.path.exists(first)
        assert os.path.exists(second)

    def test_the_document_keeps_its_own_name(self, staging):
        """The ingest names the document from the basename, so it must survive."""
        path = _save_upload_file(_upload("Quarterly Report.txt", b"x"))
        # The point is that it is not randomised — mkstemp would have put a temp
        # name into the document library. Sanitisation itself is tested elsewhere.
        assert os.path.basename(path) == "Quarterly Report.txt"

    def test_each_upload_stages_inside_the_upload_folder(self, staging):
        path = _save_upload_file(_upload("report.txt", b"x"))
        assert Path(staging) in Path(path).parents


@pytest.mark.unit
class TestTheSizeLimitIsEnforced:
    def test_an_oversized_upload_is_refused(self, staging, monkeypatch):
        monkeypatch.setattr("src.config.MAX_CONTENT_LENGTH", 100)
        with pytest.raises(UploadTooLargeError):
            _save_upload_file(_upload("big.txt", b"x" * 101))

    def test_a_file_at_the_limit_is_accepted(self, staging, monkeypatch):
        """The boundary on the other side — a cap of zero would pass the test above."""
        monkeypatch.setattr("src.config.MAX_CONTENT_LENGTH", 100)
        assert _save_upload_file(_upload("ok.txt", b"x" * 100)) is not None

    def test_nothing_is_left_behind_when_it_is_refused(self, staging, monkeypatch):
        """Refusing mid-write must not leave the part it already wrote."""
        monkeypatch.setattr("src.config.MAX_CONTENT_LENGTH", 100)
        with pytest.raises(UploadTooLargeError):
            _save_upload_file(_upload("big.txt", b"x" * 5000))

        assert list(Path(staging).iterdir()) == []

    def test_the_whole_file_is_never_read_at_once(self, staging, monkeypatch):
        """M2's actual defect: one unbounded read, so size was decided after the fact."""
        monkeypatch.setattr("src.config.MAX_CONTENT_LENGTH", 10 * 1024 * 1024)
        reads: list[int | None] = []

        class _RecordingFile(io.BytesIO):
            def read(self, size: int | None = -1) -> bytes:  # type: ignore[override]
                reads.append(size)
                return super().read(size)

        upload = StarletteUploadFile(
            file=_RecordingFile(b"y" * (3 * 1024 * 1024)),
            filename="medium.txt",
            headers=Headers({"content-type": "text/plain"}),
        )
        _save_upload_file(upload)

        assert reads, "read() was never called"
        assert all(size not in (-1, None) for size in reads), reads


@pytest.mark.unit
class TestTheStagingSweepRemovesDirectories:
    """Startup clears orphans; each upload is now a directory, not a loose file."""

    def test_an_orphaned_upload_directory_is_removed(self, staging, monkeypatch):
        from src.app_bootstrap import _clear_upload_staging

        orphan = staging / "upload-abc123"
        orphan.mkdir()
        (orphan / "left-behind.txt").write_text("interrupted ingest")

        _clear_upload_staging()

        assert not orphan.exists()

    def test_a_dotfile_is_still_left_alone(self, staging, monkeypatch):
        """uploads/.gitkeep is tracked — sweeping it dirties the working tree."""
        from src.app_bootstrap import _clear_upload_staging

        keep = staging / ".gitkeep"
        keep.write_text("")

        _clear_upload_staging()

        assert keep.exists()


@pytest.mark.unit
class TestMoreThanOneWorkerIsRefused:
    """P1-5, audit M7 — the setting contradicted ADR-1 and failed silently."""

    def test_one_worker_is_accepted(self, monkeypatch):
        from src import config

        monkeypatch.setattr(config, "UVICORN_WORKERS", 1)
        config.validate_single_worker()  # does not raise

    def test_two_workers_abort_the_boot(self, monkeypatch):
        """Not a warning: two workers diverge quietly rather than failing."""
        from src import config

        monkeypatch.setattr(config, "UVICORN_WORKERS", 2)
        with pytest.raises(SystemExit) as exc_info:
            config.validate_single_worker()
        assert exc_info.value.code == 1

    def test_the_check_runs_on_every_app_creation(self, monkeypatch):
        """In every environment, not only production: the divergence is not
        production-specific, and it is silent wherever it happens."""
        import src.app_fastapi as app_fastapi
        from src import config

        monkeypatch.setattr(config, "UVICORN_WORKERS", 4)
        with pytest.raises(SystemExit):
            app_fastapi.create_app()
