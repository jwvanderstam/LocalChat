"""A template's own assets are referenced root-relative, never absolutely.

Starlette's ``url_for`` returns an *absolute* URL built from the incoming request,
so behind a proxy that terminates TLS the app sees ``http`` and emits
``http://host/static/css/style.css`` into a page the browser loaded over
``https``. Browsers block that as mixed content: every stylesheet and every script
is refused, and the application renders as unstyled markup that never finishes
loading because its JavaScript never ran.

That is exactly what the first Scaleway deployment looked like. The assets were
fine — 200, correct content type, right size — and unreachable anyway.

Making the app honour ``X-Forwarded-Proto`` would also fix it, but only by tying
the UI to the proxy-trust decision in §7 of the deployment guide, which is about
rate limiting and has its own trade-offs. An asset on the same origin needs no
scheme and no host, so the robust fix is to stop emitting them: ``/static/…``
cannot be wrong behind any proxy, under any scheme.
"""

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

TEMPLATES = sorted((Path(__file__).resolve().parents[2] / "templates").glob("*.html"))

# Any src/href pointing at our own static tree.
_ASSET = re.compile(r"""(?:src|href)\s*=\s*["']([^"']*\/static\/[^"']*)["']""")


def test_there_are_templates_to_check():
    """A glob that matches nothing would make every assertion below vacuous."""
    assert len(TEMPLATES) >= 5


@pytest.mark.parametrize("template", TEMPLATES, ids=lambda p: p.name)
def test_no_template_builds_an_absolute_url_for_its_own_assets(template):
    text = template.read_text(encoding="utf-8")

    assert "url_for('static'" not in text and 'url_for("static"' not in text, (
        f"{template.name} uses Starlette's url_for for a static asset. That returns an "
        "absolute URL carrying the scheme the app *thinks* it is serving, which is http "
        "behind a TLS-terminating proxy — and the browser then blocks it as mixed "
        "content. Use /static/... instead."
    )


@pytest.mark.parametrize("template", TEMPLATES, ids=lambda p: p.name)
def test_every_static_reference_is_root_relative(template):
    text = template.read_text(encoding="utf-8")

    offenders = [
        url
        for url in _ASSET.findall(text)
        if not url.startswith("/static/")
    ]

    assert not offenders, (
        f"{template.name} references its own assets with a scheme or host: {offenders}. "
        "A same-origin asset needs neither, and supplying one is what breaks the page "
        "behind a proxy."
    )


def test_the_check_would_notice_a_regression():
    """Guards the regex: a realistic bad reference must actually be caught."""
    bad = '<link href="http://example.test/static/css/style.css" rel="stylesheet">'
    good = '<link href="/static/css/style.css" rel="stylesheet">'

    assert [u for u in _ASSET.findall(bad) if not u.startswith("/static/")]
    assert not [u for u in _ASSET.findall(good) if not u.startswith("/static/")]
