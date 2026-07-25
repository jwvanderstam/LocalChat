"""
Integration tests for repo-docs routes (src/routes_fastapi/docs_routes.py).

Covers:
  GET /api/repo-docs
  GET /api/repo-docs/{slug}
  GET /api/repo-docs/{slug}/fragments/{fragment_slug}
"""


class TestListDocs:
    def test_returns_known_slugs(self, client):
        response = client.get("/api/repo-docs")
        assert response.status_code == 200
        slugs = {d["slug"] for d in response.json()}
        assert "claude-md" in slugs
        assert "rules-testing" in slugs


class TestGetDoc:
    def test_known_slug_returns_rendered_html(self, client):
        response = client.get("/api/repo-docs/claude-md")
        assert response.status_code == 200
        body = response.json()
        assert body["slug"] == "claude-md"
        assert body["html"]

    def test_unknown_slug_returns_404(self, client):
        response = client.get("/api/repo-docs/does-not-exist")
        assert response.status_code == 404
        assert response.json()["error"] == "DocNotFoundError"


class TestGetFragment:
    def test_unknown_doc_slug_returns_404(self, client):
        response = client.get("/api/repo-docs/does-not-exist/fragments/anything")
        assert response.status_code == 404

    def test_unknown_fragment_slug_returns_404(self, client):
        response = client.get("/api/repo-docs/claude-md/fragments/does-not-exist")
        assert response.status_code == 404
