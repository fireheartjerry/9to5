"""RED contracts for public-HTTPS-only external source admission."""

from __future__ import annotations

import importlib

import pytest


def _source():
    return importlib.import_module("platform_core.execution.source_acquisition")


@pytest.mark.parametrize(
    "url",
    [
        "file:///C:/repo",
        "C:/repo",
        "http://example.com/repo.git",
        "https://user:token@example.com/repo.git",
        "https://127.0.0.1/repo.git",
        "https://[::1]/repo.git",
        "https://169.254.169.254/latest/meta-data",
    ],
)
def test_source_normalization_rejects_nonpublic_or_credentialed_inputs(url: str) -> None:
    mod = _source()
    with pytest.raises(mod.SourceAcquisitionUnavailable):
        mod.normalizePublicHttpsSource(url)


def test_missing_authority_refuses_before_resolution_or_resource_creation() -> None:
    mod = _source()
    observations: list[str] = []
    acquisition = mod.SourceAcquisitionController(
        resolver=lambda host: observations.append(f"resolve:{host}") or ("203.0.113.1",),
        resource_factory=lambda request: observations.append("resource") or object(),
    )

    with pytest.raises(mod.SourceAcquisitionUnavailable):
        acquisition.acquire("https://example.com/repo.git", authority=None)

    assert observations == []
