"""QP-7 — the paths around the golden one: who may do what, in a real browser.

`test_golden_path.py` proves a signed-in user can upload, ask and get a cited
answer. These prove the boundaries around that path: signing out closes the app,
a copied session dies with the sign-out, the workspace switcher changes what the
pages show, an admin can create a usable account, a viewer cannot write, and a
workspace API key reaches its own workspace and no other.

Where the browser hides a control, the server is asked as well. A hidden button
is presentation; the refusal over the wire is the guarantee, and a test of only
the first would stay green if the second were deleted.
"""

from __future__ import annotations

import os
import re
import uuid

import pytest

try:
    from playwright.sync_api import APIRequestContext, Page, Playwright, expect
except ImportError:
    if os.environ.get("CI"):
        raise  # see test_golden_path.py: a skip here is how the old suite stayed broken
    pytest.skip(
        "playwright not installed — run: pip install -r requirements-dev.txt && playwright install chromium",
        allow_module_level=True,
    )

from tests.e2e.conftest import sign_in  # noqa: E402

pytestmark = [pytest.mark.e2e, pytest.mark.slow, pytest.mark.db]

USER_PASSWORD = "e2e-user-password-not-a-secret"


def _unique(label: str) -> str:
    return f"e2e-{label}-{uuid.uuid4().hex[:8]}"


def _create_workspace(page: Page, label: str) -> tuple[str, str]:
    name = _unique(label)
    response = page.request.post("/api/workspaces", data={"name": name})
    assert response.status == 201, response.text()
    return response.json()["workspace"]["id"], name


def _create_user(page: Page, workspace_id: str, workspace_role: str) -> str:
    username = _unique(workspace_role)
    response = page.request.post("/api/users", data={
        "username": username, "password": USER_PASSWORD, "role": "user",
        "workspace_id": workspace_id, "workspace_role": workspace_role,
    })
    assert response.status == 201, response.text()
    return username


def _upload(request: APIRequestContext, workspace_id: str, filename: str) -> int:
    """Upload a small text file; returns the status. The SSE body is read to its
    end, so a 200 means the ingest has finished."""
    response = request.post(
        "/api/documents/upload",
        headers={"X-Workspace-ID": workspace_id},
        multipart={"files": {"name": filename, "mimeType": "text/plain",
                             "buffer": f"Notes kept in {filename}.".encode()}},
    )
    return response.status


def _filenames(request: APIRequestContext, workspace_id: str | None = None) -> list[str]:
    headers = {"X-Workspace-ID": workspace_id} if workspace_id else {}
    response = request.get("/api/documents/list", headers=headers)
    assert response.ok, response.text()
    return [doc["filename"] for doc in response.json()["documents"]]


def _sign_out(page: Page) -> None:
    page.locator("#logout-link").click()
    expect(page).to_have_url(re.compile(r"/login"))


def _switch_to(page: Page, name: str) -> None:
    page.locator("#workspaceDropdown").click()
    page.locator("#workspace-list").get_by_text(name, exact=True).click()
    expect(page.locator("#active-workspace-name")).to_have_text(name)


def test_signing_out_returns_to_the_login_page_and_the_app_stays_closed(page: Page) -> None:
    sign_in(page)

    _sign_out(page)

    page.goto("/")
    expect(page).to_have_url(re.compile(r"/login"))


def test_a_session_cookie_replayed_after_sign_out_is_refused(page: Page) -> None:
    """Sign-out must revoke the token, not only clear the cookie: someone who
    copied the cookie beforehand still holds it."""
    sign_in(page)
    copied = page.context.cookies()
    # The control: the copied cookie is a working session before sign-out, so a
    # 401 afterwards can only come from the revocation. Probed on a route that
    # requires authentication; /api/users/me answers anyone, signed in or not.
    assert page.request.get("/api/workspaces").status == 200

    _sign_out(page)
    page.context.add_cookies(copied)

    assert page.request.get("/api/workspaces").status == 401
    page.goto("/")
    expect(page).to_have_url(re.compile(r"/login"))


def test_switching_workspace_shows_only_that_workspaces_documents(page: Page) -> None:
    sign_in(page)
    a_id, a_name = _create_workspace(page, "switch-a")
    b_id, b_name = _create_workspace(page, "switch-b")
    a_doc, b_doc = f"{_unique('in-a')}.txt", f"{_unique('in-b')}.txt"
    assert _upload(page.request, a_id, a_doc) == 200
    assert _upload(page.request, b_id, b_doc) == 200

    page.goto("/documents")
    documents = page.locator("#documents-list")

    _switch_to(page, a_name)
    expect(documents).to_contain_text(a_doc)
    expect(documents).not_to_contain_text(b_doc)

    _switch_to(page, b_name)
    expect(documents).to_contain_text(b_doc)
    expect(documents).not_to_contain_text(a_doc)

    # The choice outlives the page: a reload must not fall back to the first workspace.
    page.reload()
    expect(page.locator("#active-workspace-name")).to_have_text(b_name)
    expect(documents).to_contain_text(b_doc)


def test_an_admin_creates_a_user_with_workspace_access_and_that_user_lands_in_it(
        page: Page, new_context) -> None:  # noqa: ANN001 — pytest-playwright's factory
    sign_in(page)
    workspace_id, workspace_name = _create_workspace(page, "members")
    username = _unique("new-user")

    page.goto("/settings")
    page.locator("#users-tab").click()
    page.locator("#user-create-btn").click()
    page.locator("#nu-username").fill(username)
    page.locator("#nu-password").fill(USER_PASSWORD)
    page.locator("#nu-workspace").select_option(workspace_id)
    page.locator("#nu-wsrole").select_option("editor")
    page.locator("#nu-submit").click()

    card = page.locator("#users-grid .card", has_text=username)
    expect(card).to_contain_text(f"{workspace_name} · editor")

    new_user = new_context().new_page()
    sign_in(new_user, username, USER_PASSWORD)
    expect(new_user.locator("#active-workspace-name")).to_have_text(workspace_name)
    # Exactly the one granted: membership in the same request, and nothing else
    # (RBAC-1 gives a new account no default workspace).
    offered = new_user.request.get("/api/workspaces").json()["workspaces"]
    assert [w["name"] for w in offered] == [workspace_name]


def test_a_viewer_sees_no_upload_control_and_the_server_refuses_an_upload_anyway(
        page: Page, new_context) -> None:  # noqa: ANN001 — pytest-playwright's factory
    sign_in(page)
    workspace_id, workspace_name = _create_workspace(page, "viewer")
    username = _create_user(page, workspace_id, "viewer")

    viewer = new_context().new_page()
    sign_in(viewer, username, USER_PASSWORD)
    # The permission check reads the active workspace the switcher stores, so let
    # the switcher settle before the documents page asks.
    expect(viewer.locator("#active-workspace-name")).to_have_text(workspace_name)

    viewer.goto("/documents")
    expect(viewer.locator("#readonly-banner")).to_be_visible()
    expect(viewer.locator("#upload-section")).to_be_hidden()

    filename = f"{_unique('by-viewer')}.txt"
    assert _upload(viewer.request, workspace_id, filename) == 403
    assert filename not in _filenames(page.request, workspace_id)


def test_a_workspace_api_key_reads_its_own_workspace_and_is_refused_any_other(
        page: Page, playwright: Playwright, base_url: str) -> None:
    sign_in(page)
    a_id, _ = _create_workspace(page, "key-a")
    b_id, _ = _create_workspace(page, "key-b")
    a_doc, b_doc = f"{_unique('in-a')}.txt", f"{_unique('in-b')}.txt"
    assert _upload(page.request, a_id, a_doc) == 200
    assert _upload(page.request, b_id, b_doc) == 200

    page.goto("/settings")
    page.locator("#users-tab").click()
    page.locator("#key-create-btn").click()
    page.locator("#nk-name").fill(_unique("bridge"))
    page.locator("#nk-workspace").select_option(a_id)
    page.locator("#key-create-form button[type=submit]").click()
    revealed = page.locator("#kr-value")
    expect(revealed).not_to_have_value("")
    key = revealed.input_value()

    # A client with the key and nothing else: no session cookie to fall back on.
    client = playwright.request.new_context(
        base_url=base_url, extra_http_headers={"Authorization": f"Bearer {key}"},
    )
    try:
        visible = _filenames(client)
        assert a_doc in visible
        assert b_doc not in visible
        widened = client.get("/api/documents/list", headers={"X-Workspace-ID": b_id})
        assert widened.status == 403
    finally:
        client.dispose()
