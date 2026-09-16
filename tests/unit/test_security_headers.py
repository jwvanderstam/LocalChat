"""P1-4 — the browser is told what this application permits.

Audit findings M6 (no CSP, no security headers, in the app or in nginx) and M8
(`CORS_ORIGINS` defaulted to scheme-less values that match no browser Origin, and
`setup_cors` fell back to `allow_origins=["*"]` alongside `allow_credentials=True`,
which lets any site make authenticated cross-origin calls).
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.security_fastapi import setup_cors, setup_security_headers


def _app() -> FastAPI:
    app = FastAPI()
    setup_security_headers(app)

    @app.get("/probe")
    def probe() -> dict[str, bool]:
        return {"ok": True}

    return app


@pytest.fixture
def client() -> TestClient:
    return TestClient(_app())


@pytest.mark.unit
class TestEveryResponseCarriesTheHeaders:
    def test_content_security_policy_is_set(self, client):
        assert "Content-Security-Policy" in client.get("/probe").headers

    def test_nosniff_is_set(self, client):
        assert client.get("/probe").headers["X-Content-Type-Options"] == "nosniff"

    def test_referrer_policy_does_not_leak_the_path(self, client):
        policy = client.get("/probe").headers["Referrer-Policy"]
        assert policy == "strict-origin-when-cross-origin"

    def test_framing_is_denied_both_ways(self, client):
        """frame-ancestors for modern browsers, X-Frame-Options for the rest."""
        resp = client.get("/probe")
        assert "frame-ancestors 'none'" in resp.headers["Content-Security-Policy"]
        assert resp.headers["X-Frame-Options"] == "DENY"


@pytest.mark.unit
class TestTheContentSecurityPolicyIsMeaningful:
    def _csp(self, client) -> str:
        return client.get("/probe").headers["Content-Security-Policy"]

    def test_objects_are_banned_outright(self, client):
        assert "object-src 'none'" in self._csp(client)

    def test_form_submissions_cannot_leave_this_origin(self, client):
        assert "form-action 'self'" in self._csp(client)

    def test_the_base_uri_cannot_be_rewritten(self, client):
        """Without this an injected <base> re-points every relative script URL."""
        assert "base-uri 'self'" in self._csp(client)

    def test_connections_are_limited_to_this_origin(self, client):
        assert "connect-src 'self'" in self._csp(client)

    def test_scripts_are_limited_to_this_origin_and_the_one_cdn(self, client):
        csp = self._csp(client)
        script_src = next(d for d in csp.split("; ") if d.startswith("script-src"))
        assert "'self'" in script_src
        assert "https://cdn.jsdelivr.net" in script_src
        # Nothing else: a policy that allows any host is not a policy.
        assert "*" not in script_src.replace("'unsafe-inline'", "")

    def test_inline_scripts_are_not_allowed(self, client):
        """The gap this row existed to close: an XSS payload cannot execute inline."""
        script_src = next(
            d for d in self._csp(client).split("; ") if d.startswith("script-src")
        )
        assert "'unsafe-inline'" not in script_src

    def test_inline_styles_are_still_allowed_and_that_is_deliberate(self, client):
        """43 `style=` attributes across the templates, and no XSS lever among them.

        Stripping them is a larger change for much less: an attacker who can inject
        a style attribute cannot execute code with it. Recorded rather than left to
        look like an oversight.
        """
        style_src = next(
            d for d in self._csp(client).split("; ") if d.startswith("style-src")
        )
        assert "'unsafe-inline'" in style_src

    def test_the_one_permitted_inline_script_is_pinned_by_hash(self, client):
        """base.html and login.html apply the saved theme before first paint.

        It cannot move to a file without flashing the wrong theme on every
        navigation, so CSP permits exactly it, by hash. Recomputed here from the
        templates so a change to either fails rather than being silently blocked
        in the browser.
        """
        import base64
        import hashlib
        import re
        from pathlib import Path

        root = Path(__file__).resolve().parents[2]
        blocks = set()
        for name in ("base.html", "login.html"):
            html = (root / "templates" / name).read_text(encoding="utf-8")
            blocks.update(re.findall(r"<script>(.*?)</script>", html, re.S))

        assert len(blocks) == 1, f"expected one inline script, found {len(blocks)}"
        digest = base64.b64encode(hashlib.sha256(blocks.pop().encode()).digest()).decode()
        assert f"'sha256-{digest}'" in self._csp(client)


@pytest.mark.unit
class TestStrictTransportSecurityOnlyOverTls:
    def test_not_sent_over_plain_http(self, client):
        """Meaningless over HTTP, and it would pin a developer's localhost to HTTPS."""
        assert "Strict-Transport-Security" not in client.get("/probe").headers

    def test_sent_over_https(self):
        client = TestClient(_app(), base_url="https://testserver")
        header = client.get("/probe").headers["Strict-Transport-Security"]
        assert "max-age=31536000" in header
        assert "includeSubDomains" in header


@pytest.mark.unit
class TestCorsNeverFallsBackToAWildcard:
    def _with_cors(self, monkeypatch, *, enabled: bool, origins: list[str]) -> FastAPI:
        from src import config

        monkeypatch.setattr(config, "CORS_ENABLED", enabled)
        monkeypatch.setattr(config, "CORS_ORIGINS", origins)
        app = FastAPI()
        setup_cors(app)
        return app

    def _middleware_names(self, app: FastAPI) -> list[str]:
        return [m.cls.__name__ for m in app.user_middleware]

    def test_no_origins_leaves_cors_off_rather_than_wildcarded(self, monkeypatch):
        """`config.CORS_ORIGINS or ["*"]` reached the wildcard by accident (M8)."""
        app = self._with_cors(monkeypatch, enabled=True, origins=[])
        assert "CORSMiddleware" not in self._middleware_names(app)

    def test_an_explicit_wildcard_is_also_refused(self, monkeypatch):
        """With allow_credentials=True a wildcard lets any site call this API."""
        app = self._with_cors(monkeypatch, enabled=True, origins=["*"])
        assert "CORSMiddleware" not in self._middleware_names(app)

    def test_a_scheme_less_origin_aborts_the_boot(self, monkeypatch):
        """It matches no Origin header, so it is a silent no-op — the M8 default."""
        with pytest.raises(SystemExit):
            self._with_cors(monkeypatch, enabled=True, origins=["localhost"])

    def test_a_proper_origin_is_installed(self, monkeypatch):
        """The negative space: refusing everything would satisfy the three above."""
        app = self._with_cors(monkeypatch, enabled=True, origins=["https://app.example.com"])
        assert "CORSMiddleware" in self._middleware_names(app)

    def test_disabled_installs_nothing(self, monkeypatch):
        app = self._with_cors(monkeypatch, enabled=False, origins=["https://app.example.com"])
        assert "CORSMiddleware" not in self._middleware_names(app)


@pytest.mark.unit
class TestTheDefaultOriginsCarryAScheme:
    def test_the_shipped_default_would_match_a_browser(self):
        """`localhost` was the default and matches no Origin header at all."""
        from src import config

        assert config.CORS_ORIGINS
        assert all("://" in origin for origin in config.CORS_ORIGINS)


@pytest.mark.unit
class TestTheExtractedScriptsAreActuallyLoaded:
    """The inline blocks moved to files; a page that forgot its tag is silently dead.

    Nothing else would catch it: the template renders, the console shows no error
    the suite can see, and the page simply stops working.
    """

    def _templates(self):
        from pathlib import Path

        return Path(__file__).resolve().parents[2] / "templates"

    @pytest.mark.parametrize(
        ("template", "script"),
        [
            ("base.html", "/static/js/statusbar.js"),
            ("models.html", "/static/js/models.js"),
            ("settings.html", "/static/js/settings-page.js"),
        ],
    )
    def test_each_page_loads_the_file_its_script_moved_to(self, template, script):
        html = (self._templates() / template).read_text(encoding="utf-8")
        assert f'<script src="{script}"></script>' in html

    def test_no_template_carries_an_inline_event_handler(self):
        """CSP blocks them, so one left behind is a control that does nothing."""
        import re

        offenders = []
        for path in self._templates().glob("*.html"):
            html = path.read_text(encoding="utf-8")
            for match in re.finditer(r"\son(?:click|change|submit|input)=", html):
                offenders.append(f"{path.name}:{html[:match.start()].count(chr(10)) + 1}")
        assert not offenders, offenders
