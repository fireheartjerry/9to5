"""GALAXY R3 structural-manifest qualification tests."""

from __future__ import annotations

import copy

import pytest

from platform_core.core.galaxy_topology import (
    ManifestValidationError,
    load_manifest,
    main,
    manifest_path,
    validate_manifest,
)


def test_frozen_manifest_reconciles_all_structural_counts() -> None:
    manifest = load_manifest(manifest_path())

    report = validate_manifest(manifest)

    assert report.base == (71, 95)
    assert report.core == (131, 250)
    assert report.federation_ready == (134, 256)
    assert report.source_maturities == frozenset({"specified"})


def test_duplicate_ordered_edge_is_rejected_even_with_a_new_id() -> None:
    manifest = load_manifest(manifest_path())
    duplicate = copy.deepcopy(manifest["edges"][0])
    duplicate["edge_id"] = "DUPLICATE-PAIR"
    manifest["edges"].append(duplicate)

    with pytest.raises(ManifestValidationError, match="duplicate ordered edge"):
        validate_manifest(manifest)


def test_source_manifest_cannot_claim_runtime_authority() -> None:
    manifest = load_manifest(manifest_path())
    manifest["nodes"][0]["active"] = True

    with pytest.raises(ManifestValidationError, match="runtime authority field"):
        validate_manifest(manifest)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda manifest: manifest["nodes"].append(
                copy.deepcopy(manifest["nodes"][0])
            ),
            "duplicate node ID",
        ),
        (
            lambda manifest: manifest["edges"].append(
                {
                    **copy.deepcopy(manifest["edges"][0]),
                    "source_node_id": manifest["edges"][1]["source_node_id"],
                    "target_node_id": manifest["edges"][1]["target_node_id"],
                }
            ),
            "duplicate edge ID",
        ),
        (
            lambda manifest: manifest["edges"][0].update(
                {"target_node_id": "MISSING"}
            ),
            "dangling endpoint",
        ),
        (
            lambda manifest: manifest["edges"][0].update(
                {"target_node_id": manifest["edges"][0]["source_node_id"]}
            ),
            "self-loop",
        ),
        (
            lambda manifest: manifest["nodes"][0].update(
                {"source_implementation_maturity": "active"}
            ),
            "invalid source implementation maturity",
        ),
        (
            lambda manifest: manifest["edges"].pop(),
            "count drift",
        ),
    ],
)
def test_structural_corruption_fails_closed(mutate, message: str) -> None:
    manifest = load_manifest(manifest_path())
    mutate(manifest)

    with pytest.raises(ManifestValidationError, match=message):
        validate_manifest(manifest)


def test_payload_schema_must_be_closed() -> None:
    manifest = load_manifest(manifest_path())
    schema = manifest["edges"][0]["closed_payload_schema"]
    manifest["payload_schemas"][schema]["additionalProperties"] = True

    with pytest.raises(ManifestValidationError, match="schema is not closed"):
        validate_manifest(manifest)


def test_endpoint_schema_contract_must_match_edge() -> None:
    manifest = load_manifest(manifest_path())
    edge = manifest["edges"][0]
    target = next(
        node for node in manifest["nodes"] if node["node_id"] == edge["target_node_id"]
    )
    target["typed_input_schemas"].remove(edge["closed_payload_schema"])

    with pytest.raises(ManifestValidationError, match="incompatible endpoint schemas"):
        validate_manifest(manifest)


def test_overlay_cannot_amplify_authority() -> None:
    manifest = load_manifest(manifest_path())
    edge = next(edge for edge in manifest["edges"] if edge["layer"] != "base")
    edge["authority_and_security_class"] = "mutation_spine_authority"

    with pytest.raises(ManifestValidationError, match="authority amplification"):
        validate_manifest(manifest)


def test_overlay_cannot_enter_mutation_spine() -> None:
    manifest = load_manifest(manifest_path())
    edge = next(edge for edge in manifest["edges"] if edge["layer"] != "base")
    edge["target_node_id"] = "RS"
    edge["source_and_target_contract_versions"]["target"] = "galaxy.node.rs/v1"
    target = next(node for node in manifest["nodes"] if node["node_id"] == "RS")
    target["typed_input_schemas"].append(edge["closed_payload_schema"])

    with pytest.raises(ManifestValidationError, match="authority ingress"):
        validate_manifest(manifest)


def test_static_linter_cli_reports_all_three_count_surfaces(capsys) -> None:
    assert main([]) == 0

    output = capsys.readouterr().out
    assert "base=71/95" in output
    assert "core=131/250" in output
    assert "federation_ready=134/256" in output
