"""Unit tests for the admin log viewer's reader (`src/services/logs.py`)."""

from __future__ import annotations

import json

import pytest

from src.services.logs import MAX_LIMIT, _read_last_lines, read_log_tail

pytestmark = pytest.mark.unit


def _json_line(level: str = "INFO", message: str = "hello", logger: str = "src.app") -> str:
    return json.dumps({
        "timestamp": "2026-08-21T10:00:00+00:00",
        "level": level,
        "logger": logger,
        "message": message,
    })


def _write(tmp_path, lines: list[str]):
    path = tmp_path / "app.log"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(path)


class TestReadLastLines:
    def test_returns_only_the_trailing_lines(self, tmp_path):
        path = _write(tmp_path, [f"line {i}" for i in range(100)])
        assert _read_last_lines(path, 3) == ["line 97", "line 98", "line 99"]

    def test_asking_for_more_than_exists_returns_everything(self, tmp_path):
        path = _write(tmp_path, ["only", "two"])
        assert _read_last_lines(path, 50) == ["only", "two"]

    def test_reads_across_chunk_boundaries(self, tmp_path):
        """The reader walks backwards in 64 KB blocks; a tail spanning several of
        them must not lose or duplicate lines at the seams."""
        lines = [f"{i:06d} " + "x" * 200 for i in range(2000)]  # ~400 KB
        path = _write(tmp_path, lines)
        assert _read_last_lines(path, 500) == lines[-500:]

    def test_an_empty_file_yields_no_lines(self, tmp_path):
        path = tmp_path / "empty.log"
        path.write_text("", encoding="utf-8")
        assert _read_last_lines(str(path), 10) == []


class TestParsing:
    def test_json_lines_are_split_into_fields(self, tmp_path):
        path = _write(tmp_path, [_json_line(level="WARNING", message="disk almost full")])
        record = read_log_tail(path)["records"][0]
        assert record["level"] == "WARNING"
        assert record["message"] == "disk almost full"
        assert record["logger"] == "src.app"
        assert record["parsed"] is True

    def test_text_lines_still_yield_their_level(self, tmp_path):
        """LOG_FORMAT can change between runs, so one file holds both shapes."""
        line = "2026-08-21 10:00:00 - src.app - ERROR - boot:12 - [rid] it broke"
        path = _write(tmp_path, [line])
        record = read_log_tail(path)["records"][0]
        assert record["level"] == "ERROR"
        assert record["parsed"] is False
        assert record["message"] == line

    def test_a_mixed_file_parses_each_line_on_its_own_merits(self, tmp_path):
        path = _write(tmp_path, [
            _json_line(level="INFO", message="structured"),
            "2026-08-21 10:00:00 - src.app - ERROR - boot:12 - [rid] plain",
        ])
        records = read_log_tail(path)["records"]
        assert [r["parsed"] for r in records] == [True, False]
        assert [r["level"] for r in records] == ["INFO", "ERROR"]

    def test_malformed_json_is_shown_rather_than_dropped(self, tmp_path):
        """A truncated line — a rotation mid-write — is still evidence."""
        path = _write(tmp_path, ['{"level": "INFO", "message": "cut off'])
        record = read_log_tail(path)["records"][0]
        assert record["parsed"] is False
        assert "cut off" in record["message"]


class TestFiltering:
    def test_level_filter_keeps_only_that_level(self, tmp_path):
        path = _write(tmp_path, [
            _json_line(level="INFO", message="a"),
            _json_line(level="ERROR", message="b"),
            _json_line(level="INFO", message="c"),
        ])
        records = read_log_tail(path, level="ERROR")["records"]
        assert [r["message"] for r in records] == ["b"]

    def test_query_matches_case_insensitively(self, tmp_path):
        path = _write(tmp_path, [
            _json_line(message="Connection refused"),
            _json_line(message="all good"),
        ])
        records = read_log_tail(path, query="connection")["records"]
        assert [r["message"] for r in records] == ["Connection refused"]

    def test_level_and_query_both_apply(self, tmp_path):
        path = _write(tmp_path, [
            _json_line(level="ERROR", message="disk full"),
            _json_line(level="INFO", message="disk full"),
            _json_line(level="ERROR", message="unrelated"),
        ])
        records = read_log_tail(path, level="ERROR", query="disk")["records"]
        assert [r["message"] for r in records] == ["disk full"]


class TestLimits:
    def test_limit_caps_the_rows_returned(self, tmp_path):
        path = _write(tmp_path, [_json_line(message=str(i)) for i in range(50)])
        assert len(read_log_tail(path, limit=5)["records"]) == 5

    def test_limit_is_clamped_to_the_ceiling(self, tmp_path):
        """Without the cap a caller could pull the whole file into memory."""
        path = _write(tmp_path, [_json_line(message=str(i)) for i in range(MAX_LIMIT + 200)])
        assert len(read_log_tail(path, limit=99999)["records"]) == MAX_LIMIT

    def test_the_newest_lines_are_the_ones_kept(self, tmp_path):
        path = _write(tmp_path, [_json_line(message=str(i)) for i in range(50)])
        records = read_log_tail(path, limit=3)["records"]
        assert [r["message"] for r in records] == ["47", "48", "49"]


class TestUnreadableFile:
    def test_a_missing_file_reports_rather_than_raises(self, tmp_path):
        """The viewer must explain itself; a 500 tells the admin nothing."""
        result = read_log_tail(str(tmp_path / "nope.log"))
        assert result["available"] is False
        assert result["records"] == []
        assert "does not exist" in result["reason"]

    def test_a_directory_in_place_of_the_file_reports_rather_than_raises(self, tmp_path):
        result = read_log_tail(str(tmp_path))
        assert result["available"] is False
        assert result["records"] == []
