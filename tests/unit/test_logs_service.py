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
        # parsed stays False: these fields are recovered from a formatted line, not
        # read from JSON, and the distinction is what the viewer styles on.
        assert record["parsed"] is False
        assert record["message"] == "[rid] it broke"
        assert record["raw"] == line

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


class TestTextLinesYieldTheirFields:
    """The viewer showed three empty columns for a text-format log.

    Two causes, one symptom: the level was searched for as " - INFO - " while the
    line held " - \x1b[32mINFO\x1b[0m - ", and nothing tried to split the rest of
    the line at all. Historic files still hold those escapes, so stripping them is
    not only about the formatter fix.
    """

    ESC = ""
    LINE = (
        "2026-08-22 15:57:09 - src.routes_fastapi.auth_routes - "
        "[32mINFO[0m - login:98 - [rid-1] Login succeeded"
    )

    def test_the_level_survives_ansi_escapes(self, tmp_path):
        path = _write(tmp_path, [self.LINE])
        assert read_log_tail(path)["records"][0]["level"] == "INFO"

    def test_the_logger_is_extracted(self, tmp_path):
        path = _write(tmp_path, [self.LINE])
        record = read_log_tail(path)["records"][0]
        assert record["logger"] == "src.routes_fastapi.auth_routes"

    def test_the_timestamp_is_extracted(self, tmp_path):
        path = _write(tmp_path, [self.LINE])
        assert read_log_tail(path)["records"][0]["timestamp"] == "2026-08-22 15:57:09"

    def test_the_message_is_the_message_not_the_whole_line(self, tmp_path):
        path = _write(tmp_path, [self.LINE])
        record = read_log_tail(path)["records"][0]
        assert record["message"] == "[rid-1] Login succeeded"

    def test_no_escape_codes_reach_the_rendered_message(self, tmp_path):
        """A log line must never be able to move the reader's cursor."""
        path = _write(tmp_path, [self.LINE])
        assert self.ESC not in read_log_tail(path)["records"][0]["message"]

    def test_a_line_of_another_shape_keeps_its_whole_text(self, tmp_path):
        """Guard against over-correction: no inventing fields for a line that is
        not this format — a traceback line, or output from a library."""
        path = _write(tmp_path, ["Traceback (most recent call last):"])
        record = read_log_tail(path)["records"][0]
        assert record["message"] == "Traceback (most recent call last):"
        assert record["logger"] is None
        assert record["timestamp"] is None

    def test_square_brackets_in_ordinary_text_are_left_alone(self, tmp_path):
        """The escape pattern must not eat text that merely looks like one."""
        path = _write(tmp_path, ["see line [0m] of the file"])
        assert "[0m]" in read_log_tail(path)["records"][0]["message"]
