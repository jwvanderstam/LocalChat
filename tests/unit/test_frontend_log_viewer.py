"""Frontend branch logic for the admin log viewer (`static/js/logs.js`).

Runs the real file under node. The case that matters is escaping: a log line
contains text this application never authored — a filename someone chose, a header
they sent — and the viewer renders it into the DOM.
"""

from __future__ import annotations

import pytest

from tests.utils.js_harness import NODE_MISSING, run_js

pytestmark = [
    pytest.mark.unit,
    pytest.mark.skipif(NODE_MISSING, reason="node is not installed"),
]


def _record(**overrides):
    record = {
        "timestamp": "2026-08-21T10:11:12.345678+00:00",
        "level": "ERROR",
        "logger": "src.app",
        "message": "something broke",
        "parsed": True,
        "raw": "raw line",
    }
    record.update(overrides)
    return record


def _run(records, *, available=True, reason="", admin=True, **kwargs):
    payload = {"records": records, "available": available, "scanned": len(records)}
    if not available:
        payload["reason"] = reason
    return run_js(
        "logs.js",
        routes=[
            ("/api/users/me", {"role": "admin" if admin else "user"}),
            ("/api/logs", payload),
        ],
        **kwargs,
    )


class TestAdminGating:
    def test_a_non_admin_never_requests_the_log(self):
        """Hiding the tab is presentation; not fetching is the part that matters."""
        result = _run([_record()], admin=False)
        assert not any("/api/logs" in call["url"] for call in result["calls"])

    def test_an_admin_reaches_the_log_endpoint(self):
        result = _run([_record()])
        assert any("/api/logs" in call["url"] for call in result["calls"])


class TestEscaping:
    def test_a_script_tag_in_a_message_is_not_rendered_as_markup(self):
        result = _run([_record(message="<script>alert(1)</script>")])
        html = result["html"]["log-rows"]
        assert "<script>" not in html
        assert "&lt;script&gt;" in html

    def test_an_img_onerror_payload_cannot_become_an_element(self):
        """The payload stays visible as text — that is fine. What must not survive
        is the markup: no real <img> tag, and the quotes around the handler are
        escaped so it cannot break out of the attribute it is rendered near."""
        result = _run([_record(message='<img src=x onerror="alert(1)">')])
        html = result["html"]["log-rows"]
        assert "<img" not in html
        assert "&lt;img" in html
        assert 'onerror="alert(1)"' not in html
        assert "onerror=&quot;alert(1)&quot;" in html

    def test_a_hostile_logger_name_is_escaped_in_the_title_attribute(self):
        """The logger lands in an attribute as well as a cell, so a quote breaks out."""
        result = _run([_record(logger='x" onmouseover="alert(1)')])
        html = result["html"]["log-rows"]
        assert 'onmouseover="alert' not in html


class TestRendering:
    def test_the_message_is_shown(self):
        result = _run([_record(message="disk almost full")])
        assert "disk almost full" in result["html"]["log-rows"]

    def test_newest_line_is_rendered_first(self):
        """The API returns oldest-first; on screen the newest belongs at the top."""
        result = _run([_record(message="older"), _record(message="newer")])
        html = result["html"]["log-rows"]
        assert html.index("newer") < html.index("older")

    def test_an_unparsed_line_shows_no_invented_logger(self):
        result = _run([_record(parsed=False, logger=None, timestamp=None,
                               message="2026-08-21 - plain text line")])
        html = result["html"]["log-rows"]
        assert "plain text line" in html
        assert "src.app" not in html

    def test_each_record_produces_a_row(self):
        result = _run([_record(message=f"line {i}") for i in range(4)])
        assert result["html"]["log-rows"].count("<tr") == 4


class TestUnavailableLog:
    def test_a_missing_log_explains_itself_instead_of_rendering_empty(self):
        result = _run([], available=False, reason="log file does not exist")
        assert "log file does not exist" in result["html"]["log-alert"]

    def test_a_missing_log_points_at_the_sink_configuration(self):
        """The file sink can be off by configuration, not only broken."""
        result = _run([], available=False, reason="log file does not exist")
        assert "LOG_SINKS" in result["html"]["log-alert"]
