"""S5 — resource caps: a request body, and what an Office file unpacks to.

Every JSON route read its body whole, with no ceiling outside the upload route. And
MAX_CONTENT_LENGTH bounded an Office file's *compressed* bytes only: a 16 MB .docx could
unpack to gigabytes in python-docx, python-pptx or openpyxl.
"""

from __future__ import annotations

import io
import os
import zipfile

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from src import config
from src.utils.body_limit import BodySizeLimitMiddleware
from src.utils.file_validation import check_ooxml_bounds, validate_file_content

pytestmark = pytest.mark.unit

_LIMIT = 100
_REFUSAL = {"success": False, "message": "Request body larger than 100 bytes"}


def _client() -> TestClient:
    app = FastAPI()

    @app.post("/api/echo")
    async def echo(request: Request) -> dict:
        return {"length": len(await request.body())}

    @app.post("/api/documents/upload")
    async def upload(request: Request) -> dict:
        return {"length": len(await request.body())}

    app.add_middleware(BodySizeLimitMiddleware, max_bytes=_LIMIT,
                       exempt_paths=frozenset({"/api/documents/upload"}))
    return TestClient(app)


class TestTheRequestBodyCap:
    def test_a_body_at_the_limit_is_served(self):
        resp = _client().post("/api/echo", content=b"x" * _LIMIT)
        assert (resp.status_code, resp.json()) == (200, {"length": _LIMIT})

    def test_a_declared_length_one_over_is_refused_before_the_route(self):
        resp = _client().post("/api/echo", content=b"x" * (_LIMIT + 1))
        assert (resp.status_code, resp.json()) == (413, _REFUSAL)

    def test_a_chunked_body_with_no_length_is_counted_as_it_arrives(self):
        """No Content-Length to check: the cap has to hold on the bytes themselves."""
        def chunks():
            for _ in range(5):
                yield b"x" * 40

        resp = _client().post("/api/echo", content=chunks())
        assert (resp.status_code, resp.json()) == (413, _REFUSAL)

    def test_the_upload_route_keeps_its_own_per_file_cap_instead(self):
        resp = _client().post("/api/documents/upload", content=b"x" * (_LIMIT * 3))
        assert (resp.status_code, resp.json()) == (200, {"length": _LIMIT * 3})

    def test_the_application_mounts_it_at_max_content_length_exempting_only_upload(self):
        os.environ.setdefault("APP_ENV", "development")
        from src.app_fastapi import create_app

        mounted = [m for m in create_app().user_middleware if m.cls is BodySizeLimitMiddleware]
        assert [(m.kwargs["max_bytes"], m.kwargs["exempt_paths"]) for m in mounted] == [
            (config.MAX_CONTENT_LENGTH, frozenset({"/api/documents/upload"}))]


def _ooxml(tmp_path, name: str, parts: dict[str, bytes]) -> str:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
        for part, data in parts.items():
            zf.writestr(part, data)
    path = tmp_path / name
    path.write_bytes(buf.getvalue())
    return str(path)


class TestTheOfficeFileBounds:
    def test_a_part_compressed_like_a_zip_bomb_is_refused(self, tmp_path):
        path = _ooxml(tmp_path, "bomb.docx", {"word/document.xml": b"\0" * (4 * 1024 * 1024)})
        assert check_ooxml_bounds(path) == (
            False, "File has a part compressed more than 200x, which ordinary documents never are")

    def test_the_upload_check_refuses_it_too(self, tmp_path):
        path = _ooxml(tmp_path, "bomb.docx", {"word/document.xml": b"\0" * (4 * 1024 * 1024)})
        assert validate_file_content(path, ".docx")[0] is False

    def test_a_small_repetitive_part_is_not_held_to_the_ratio(self, tmp_path):
        """Below 1 MB a high ratio is ordinary XML; the total cap bounds these."""
        path = _ooxml(tmp_path, "small.docx", {"word/document.xml": b"\0" * (512 * 1024)})
        assert check_ooxml_bounds(path) == (True, "")

    def test_the_total_unpacked_size_is_capped(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "OOXML_MAX_UNCOMPRESSED_BYTES", 10_000)
        path = _ooxml(tmp_path, "big.xlsx", {"xl/a.bin": os.urandom(6_000), "xl/b.bin": os.urandom(6_000)})
        ok, message = check_ooxml_bounds(path)
        assert (ok, message.startswith("File would unpack to 12,")) == (False, True)

    def test_a_total_just_under_the_cap_passes(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "OOXML_MAX_UNCOMPRESSED_BYTES", 20_000)
        path = _ooxml(tmp_path, "ok.xlsx", {"xl/a.bin": os.urandom(6_000), "xl/b.bin": os.urandom(6_000)})
        assert check_ooxml_bounds(path) == (True, "")

    @pytest.mark.parametrize(("loader", "name"), [
        ("load_docx_file", "bomb.docx"), ("load_pptx_file", "bomb.pptx"),
        ("load_excel_file", "bomb.xlsx"),
    ])
    def test_every_loader_refuses_before_opening(self, tmp_path, loader, name):
        """Connectors ingest without the upload check, so the loaders hold the line too."""
        from src.rag.processor import DocumentProcessor

        path = _ooxml(tmp_path, name, {"part.xml": b"\0" * (4 * 1024 * 1024)})
        ok, message = getattr(DocumentProcessor(), loader)(path)
        assert (ok, message) == (
            False, "File has a part compressed more than 200x, which ordinary documents never are")
