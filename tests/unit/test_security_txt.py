"""QP-8 — `/.well-known/security.txt` (RFC 9116) is served and still valid.

The file carries an `Expires` date the RFC requires, and a reader must treat an expired
file as stale. Nothing renews it by itself, so this fails 30 days before it lapses: the
renewal is a one-line edit, and a red run is how anyone hears about it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.routes_fastapi import web_routes

pytestmark = pytest.mark.unit

_STATIC = Path(__file__).resolve().parents[2] / "static"


@pytest.fixture
def body() -> str:
    app = FastAPI()
    app.include_router(web_routes.router)
    app.state.static_folder = str(_STATIC)
    response = TestClient(app).get("/.well-known/security.txt")
    assert response.status_code == 200
    assert response.headers["content-type"] == "text/plain; charset=utf-8"
    return response.text


def _fields(body: str, name: str) -> list[str]:
    return [line.split(":", 1)[1].strip() for line in body.splitlines() if line.startswith(f"{name}:")]


def test_security_txt_names_the_private_advisory_form_and_the_maintainer(body: str) -> None:
    assert _fields(body, "Contact") == [
        "https://github.com/jwvanderstam/LocalChat/security/advisories/new",
        "mailto:jw.vander.stam@gmail.com",
    ]


def test_security_txt_carries_exactly_one_expires(body: str) -> None:
    assert len(_fields(body, "Expires")) == 1


def test_security_txt_expires_more_than_30_days_from_now(body: str) -> None:
    expires = datetime.fromisoformat(_fields(body, "Expires")[0])
    assert expires - datetime.now(UTC) > timedelta(days=30), (
        "static/security.txt expires within 30 days: move Expires a year ahead"
    )


def test_security_txt_expires_less_than_a_year_from_now(body: str) -> None:
    # RFC 9116 §2.5.5: an Expires further out than a year is not recommended.
    expires = datetime.fromisoformat(_fields(body, "Expires")[0])
    assert expires - datetime.now(UTC) <= timedelta(days=366)
