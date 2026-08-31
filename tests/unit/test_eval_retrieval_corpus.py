"""The eval harness can reach a corpus that is not this repository's `docs/`.

DEL-2's stated next step is one run against a maintainer-supplied document set,
and the script could not do it: `ingest_corpus` globbed `*.md`, so any real
corpus — .docx, .pptx, .xlsx, .pdf — ingested as zero documents and scored
against an empty database. The refusal guards fire on reach, not on document
count, so nothing said so; the run just returned a confident set of zeroes.

These pin the two halves of the fix: every supported type is picked up and the
unsupported ones are named, and a case's source resolves outside the repo.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

# `scripts/` is not a package, so the script is loaded by path. It must be in
# sys.modules before exec: @dataclass resolves its own module through it.
_SPEC = importlib.util.spec_from_file_location(
    "eval_retrieval",
    Path(__file__).resolve().parents[2] / "scripts" / "eval_retrieval.py",
)
assert _SPEC
assert _SPEC.loader
ev = importlib.util.module_from_spec(_SPEC)
sys.modules["eval_retrieval"] = ev
_SPEC.loader.exec_module(ev)


@pytest.mark.unit
class TestIngestCorpusFileSelection:
    """What `--corpus` actually picks up."""

    def _corpus(self, tmp_path: Path) -> Path:
        for name in (
            "notes.md",
            "report.docx",
            "deck.pptx",
            "sheet.xlsx",
            "scan.pdf",
            "photo.jpg",
            "archive.zip",
            "no_extension",
        ):
            (tmp_path / name).write_bytes(b"x")
        (tmp_path / "subdir").mkdir()
        return tmp_path

    def test_ingests_every_supported_type_not_just_markdown(self, tmp_path, monkeypatch, capsys):
        seen: list[str] = []

        class _Processor:
            def ingest_document(self, path, workspace_id=None):
                seen.append(Path(path).name)
                return True, "ok", None

        monkeypatch.setitem(
            sys.modules, "src.rag.processor", type(sys)("src.rag.processor")
        )
        sys.modules["src.rag.processor"].doc_processor = _Processor()

        count = ev.ingest_corpus(self._corpus(tmp_path), None)

        assert sorted(seen) == [
            "deck.pptx",
            "notes.md",
            "photo.jpg",
            "report.docx",
            "scan.pdf",
            "sheet.xlsx",
        ]
        assert count == 6

    def test_names_the_files_it_skipped(self, tmp_path, monkeypatch, capsys):
        class _Processor:
            def ingest_document(self, path, workspace_id=None):
                return True, "ok", None

        monkeypatch.setitem(
            sys.modules, "src.rag.processor", type(sys)("src.rag.processor")
        )
        sys.modules["src.rag.processor"].doc_processor = _Processor()

        ev.ingest_corpus(self._corpus(tmp_path), None)

        out = capsys.readouterr().out
        # A corpus quietly two files smaller than the maintainer thinks it is
        # produces a score nobody can reproduce.
        assert "skipped archive.zip" in out
        assert "skipped no_extension" in out
        assert "skipped notes.md" not in out


@pytest.mark.unit
class TestResolveSource:
    """Where a case's source file is looked for."""

    def test_prefers_a_repo_relative_source(self, tmp_path):
        # The in-tree docs cases name `docs/FOO.md` and must keep resolving.
        assert ev.resolve_source("docs/README.md", tmp_path) == ev.REPO_ROOT / "docs/README.md"

    def test_falls_back_to_the_corpus_for_an_external_set(self, tmp_path):
        (tmp_path / "deck.pptx").write_bytes(b"x")
        assert ev.resolve_source("deck.pptx", tmp_path) == tmp_path / "deck.pptx"

    def test_returns_none_when_the_source_is_in_neither(self, tmp_path):
        assert ev.resolve_source("absent.pptx", tmp_path) is None


@pytest.mark.unit
class TestVerifyPremises:
    """The proof check reads extracted text, not bytes."""

    def _case(self, source: str, proof: str):
        return ev.Case(question="q?", source=source, proof=proof, answered_by="x")

    def test_a_binary_source_is_checked_through_the_loader(self, tmp_path, monkeypatch):
        (tmp_path / "deck.pptx").write_bytes(b"PK\x03\x04 not utf-8")
        monkeypatch.setattr(ev, "source_text", lambda p: "bpost solution strategy")

        assert ev.verify_premises([self._case("deck.pptx", "solution strategy")], tmp_path) == []

    def test_a_proof_that_is_gone_is_reported(self, tmp_path, monkeypatch):
        (tmp_path / "deck.pptx").write_bytes(b"PK\x03\x04")
        monkeypatch.setattr(ev, "source_text", lambda p: "something else entirely")

        problems = ev.verify_premises([self._case("deck.pptx", "solution strategy")], tmp_path)

        assert len(problems) == 1
        assert "no longer present" in problems[0]

    def test_a_source_the_loader_cannot_read_is_a_rotted_premise(self, tmp_path, monkeypatch):
        # Not a crash: a .pptx yielding nothing would otherwise ingest as zero
        # chunks and drag the score down looking like a retrieval regression.
        (tmp_path / "deck.pptx").write_bytes(b"PK\x03\x04")

        def _boom(path):
            raise ValueError("no text extracted")

        monkeypatch.setattr(ev, "source_text", _boom)

        problems = ev.verify_premises([self._case("deck.pptx", "anything")], tmp_path)

        assert len(problems) == 1
        assert "could not extract text" in problems[0]

    def test_a_missing_source_is_reported(self, tmp_path):
        problems = ev.verify_premises([self._case("absent.pptx", "x")], tmp_path)

        assert problems == ["absent.pptx: file is gone"]
