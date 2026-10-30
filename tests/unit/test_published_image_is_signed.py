"""QP-8: every image the publish workflow pushes is signed and attested, by its digest.

`docker-publish.yml` is not a required check and runs only after merge, so a step removed
from it fails nowhere: the next image simply ships unsigned, and `cosign verify` in
DEPLOYMENT.md starts failing for operators instead of for us. This pins the workflow's
promises: keyless signing, an SBOM attestation, provenance, all on the pushed digest,
with the permissions they need, and every action pinned to a commit.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml", reason="PyYAML parses the workflow")

_WORKFLOW = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "docker-publish.yml"
_DIGEST = "${{ steps.build.outputs.digest }}"
_PUSHED = "github.event_name != 'pull_request'"


def _workflow() -> dict:
    return yaml.safe_load(_WORKFLOW.read_text(encoding="utf-8"))


def _steps() -> list[dict]:
    return _workflow()["jobs"]["build-and-push"]["steps"]


def _step(uses_prefix: str) -> dict:
    found = [s for s in _steps() if s.get("uses", "").startswith(uses_prefix)]
    assert len(found) == 1, f"expected one {uses_prefix} step, found {len(found)}"
    return found[0]


def test_the_job_may_request_an_oidc_identity_and_write_attestations() -> None:
    permissions = _workflow()["permissions"]
    assert (permissions["id-token"], permissions["attestations"]) == ("write", "write")


def test_the_image_is_signed_by_its_digest() -> None:
    sign = next(s for s in _steps() if "cosign sign" in s.get("run", ""))
    assert sign["env"]["DIGEST"] == _DIGEST
    assert "localchat@${DIGEST}" in sign["run"]


def test_the_sbom_is_made_from_the_pushed_digest_and_attested_to_the_registry() -> None:
    sbom = _step("anchore/sbom-action@")["with"]
    attest = _step("actions/attest@")["with"]
    assert sbom["image"] == f"ghcr.io/jwvanderstam/localchat@{_DIGEST}"
    assert (attest["sbom-path"], attest["subject-digest"], attest["push-to-registry"]) == (
        sbom["output-file"],
        _DIGEST,
        True,
    )


def test_provenance_is_attested_for_the_pushed_digest() -> None:
    provenance = _step("actions/attest-build-provenance@")["with"]
    assert (provenance["subject-digest"], provenance["push-to-registry"]) == (_DIGEST, True)


def test_signing_and_attesting_run_exactly_when_an_image_is_pushed() -> None:
    """A PR builds without pushing, so there is no digest to sign; a push must sign."""
    after_build = _steps()[[s.get("id") for s in _steps()].index("build") + 1 :]
    assert [s.get("if") for s in after_build] == [_PUSHED] * len(after_build)
    assert len(after_build) == 5


def test_every_action_is_pinned_to_a_commit() -> None:
    unpinned = [
        s["uses"] for s in _steps()
        if "uses" in s and not re.fullmatch(r"[\w.-]+/[\w.-]+@[0-9a-f]{40}", s["uses"])
    ]
    assert unpinned == []
