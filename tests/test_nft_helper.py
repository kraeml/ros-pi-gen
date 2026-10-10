from __future__ import annotations

from types import SimpleNamespace

import pytest

from helpers import container


@pytest.fixture
def helper_mocks(monkeypatch):
    builds = []
    sleeps = []
    image_present = [False]
    monkeypatch.setattr(container, "image_exists", lambda tag: image_present[0])

    def build_helper():
        builds.append(True)
        image_present[0] = True
        return SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr(container, "_build_nft_helper", build_helper)
    monkeypatch.setattr(container.time, "sleep", sleeps.append)
    return builds, sleeps, image_present


def test_ensure_nft_helper_builds_when_image_missing(monkeypatch, helper_mocks):
    builds, sleeps, _ = helper_mocks
    checks = iter([False, True])
    monkeypatch.setattr(container, "image_exists", lambda tag: next(checks))

    assert container.ensure_nft_helper() == container.NFT_HELPER_TAG
    assert next(checks, None) is None
    assert len(builds) == 1
    assert sleeps == []


def test_ensure_nft_helper_returns_existing_image_without_build(monkeypatch):
    monkeypatch.setattr(container, "image_exists", lambda tag: True)
    monkeypatch.setattr(
        container,
        "_build_nft_helper",
        lambda: pytest.fail("cached image must skip build"),
    )

    assert container.ensure_nft_helper() == container.NFT_HELPER_TAG


@pytest.mark.parametrize("status", [429, 503])
def test_transient_registry_error_matches_registry_status(status):
    stderr = (
        "unexpected status from HEAD request to "
        f"https://registry-1.docker.io/v2/library/debian/manifests/trixie: {status} "
        "upstream response"
    )

    assert container._is_transient_registry_error(stderr)


@pytest.mark.parametrize(
    "stderr",
    [
        "https://registry-1.docker.io/v2/library/debian/manifests/trixie: "
        "unauthorized; trace id 503abc",
        "https://registry-1.docker.io/v2/library/debian/manifests/trixie: "
        "404 Not Found; upstream said 503",
        "https://example.com/v2/library/debian/manifests/trixie: 429 Too Many Requests",
    ],
)
def test_transient_registry_error_rejects_unrelated_status_text(stderr):
    assert not container._is_transient_registry_error(stderr)


def test_transient_registry_error_supports_registry_port():
    stderr = (
        "unexpected status from HEAD request to "
        "https://registry-1.docker.io:443/v2/library/debian/manifests/trixie: "
        "429 Too Many Requests"
    )

    assert container._is_transient_registry_error(stderr)


@pytest.mark.parametrize("status", [429, 503])
def test_ensure_nft_helper_retries_transient_docker_hub_errors(
    monkeypatch, helper_mocks, status
):
    builds, sleeps, _ = helper_mocks
    checks = iter([False, True])
    monkeypatch.setattr(container, "image_exists", lambda tag: next(checks))
    attempts = iter([
        SimpleNamespace(
            returncode=1,
            stderr=(
                "failed to resolve source metadata: unexpected status from HEAD "
                f"request to https://registry-1.docker.io/v2/library/debian/manifests/trixie: {status} "
                f"{'Too Many Requests' if status == 429 else 'Service Unavailable'}"
            ),
        ),
        SimpleNamespace(returncode=0, stderr=""),
    ])

    def build_helper():
        builds.append(True)
        return next(attempts)

    monkeypatch.setattr(container, "_build_nft_helper", build_helper)

    assert container.ensure_nft_helper() == container.NFT_HELPER_TAG
    assert len(builds) == 2
    assert next(checks, None) is None
    assert sleeps == [container.NFT_HELPER_RETRY_DELAYS[0]]


def test_ensure_nft_helper_stops_after_retry_budget(monkeypatch, helper_mocks):
    builds, sleeps, _ = helper_mocks
    monkeypatch.setattr(
        container,
        "_build_nft_helper",
        lambda: builds.append(True) or SimpleNamespace(
            returncode=1,
            stderr=(
                "unexpected status from HEAD request to "
                "https://registry-1.docker.io/v2/library/debian/manifests/trixie: "
                "429 Too Many Requests"
            ),
        ),
    )
    monkeypatch.setattr(container, "image_exists", lambda tag: False)

    with pytest.raises(container.DockerError, match="nft-Hilfsimage-Build fehlgeschlagen"):
        container.ensure_nft_helper()

    assert len(builds) == len(container.NFT_HELPER_RETRY_DELAYS) + 1
    assert sleeps == list(container.NFT_HELPER_RETRY_DELAYS)


def test_ensure_nft_helper_does_not_retry_non_registry_errors(monkeypatch, helper_mocks):
    builds, sleeps, _ = helper_mocks
    checks = iter([False])
    monkeypatch.setattr(container, "image_exists", lambda tag: next(checks))
    monkeypatch.setattr(
        container,
        "_build_nft_helper",
        lambda: builds.append(True) or SimpleNamespace(
            returncode=1,
            stderr="RUN apt-get update failed with HTTP 429",
        ),
    )

    with pytest.raises(container.DockerError, match="nft-Hilfsimage-Build fehlgeschlagen"):
        container.ensure_nft_helper()

    assert len(builds) == 1
    assert next(checks, None) is None
    assert sleeps == []


def test_ensure_nft_helper_rejects_build_success_without_image(monkeypatch, helper_mocks):
    builds, sleeps, _ = helper_mocks
    checks = iter([False, False])
    monkeypatch.setattr(container, "image_exists", lambda tag: next(checks))
    monkeypatch.setattr(
        container,
        "_build_nft_helper",
        lambda: builds.append(True) or SimpleNamespace(returncode=0, stderr=""),
    )

    with pytest.raises(container.DockerError, match="aber das Image fehlt"):
        container.ensure_nft_helper()

    assert len(builds) == 1
    assert next(checks, None) is None
    assert sleeps == []
