"""Contracts for the authenticated state-store whole-frame protocol."""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import replace
from typing import Any

import pytest


def _scope(protocol: Any, seed: int = 10) -> Any:
    return protocol.RuntimeScope(
        controller_generation=seed + 1,
        watchdog_generation=seed + 2,
        revocation_generation=seed + 3,
        activation_generation=seed + 4,
        boot_generation=seed + 5,
        controller_child_pid=seed + 1000,
    )


def _outbound(
    protocol: Any,
    *,
    key: object | None = None,
    sequence: object = 1,
    **changes: object,
) -> Any:
    values: dict[str, Any] = {
        "channel_key": b"k" * protocol.CHANNEL_KEY_BYTES if key is None else key,
        "request_id": "request_1",
        "sequence": sequence,
        "resource_id": "state_store_1",
        "runtime_scope": _scope(protocol),
        "request": {"database_id": "runtime", "operation": "kv_get"},
    }
    values.update(changes)
    return protocol.encode_request(**values)


def _verified_request(
    protocol: Any,
    *,
    key: bytes | None = None,
    **changes: object,
) -> tuple[Any, Any]:
    actual_key = key or b"k" * protocol.CHANNEL_KEY_BYTES
    outbound = _outbound(protocol, key=actual_key, **changes)
    verified = protocol.RequestVerifier(
        channel_key=actual_key,
        resource_id=outbound.resource_id,
        runtime_scope=outbound.runtime_scope,
        initial_sequence=outbound.sequence - 1,
    ).verify(outbound.frame)
    return outbound, verified


def _resign(protocol, envelope: dict[str, object], key: bytes, domain: bytes) -> bytes:
    unsigned = dict(envelope)
    unsigned.pop("signature", None)
    envelope = {
        **unsigned,
        "signature": hmac.new(
            key,
            domain + protocol.canonical_json(unsigned),
            hashlib.sha256,
        ).hexdigest(),
    }
    return protocol.canonical_json(envelope)


def test_authenticated_request_and_response_round_trip() -> None:
    from containers.galaxy import state_store_protocol as protocol

    key = b"k" * protocol.CHANNEL_KEY_BYTES
    scope = protocol.RuntimeScope(
        controller_generation=11,
        watchdog_generation=12,
        revocation_generation=13,
        activation_generation=14,
        boot_generation=15,
        controller_child_pid=1601,
    )
    outbound = protocol.encode_request(
        channel_key=key,
        request_id="request_1",
        sequence=1,
        resource_id="state_store_1",
        runtime_scope=scope,
        request={"database_id": "runtime", "operation": "kv_get"},
    )
    verified_request = protocol.RequestVerifier(
        channel_key=key,
        resource_id="state_store_1",
        runtime_scope=scope,
    ).verify(outbound.frame)

    response_frame = protocol.encode_response(
        channel_key=key,
        request=verified_request,
        status="ok",
        result={"value": [1, 2, 3]},
    )
    verified_response = protocol.ResponseVerifier(
        channel_key=key,
        resource_id="state_store_1",
        runtime_scope=scope,
    ).verify(response_frame, expected_request=outbound)

    assert verified_request.request == {
        "database_id": "runtime",
        "operation": "kv_get",
    }
    assert verified_response.status == "ok"
    assert verified_response.result == {"value": [1, 2, 3]}
    assert verified_response.request_digest == outbound.request_digest


def test_canonical_json_is_deterministic_strict_and_utf8() -> None:
    from containers.galaxy import state_store_protocol as protocol

    assert protocol.canonical_json({"z": 1, "a": "café"}) == (
        b'{"a":"caf\xc3\xa9","z":1}'
    )
    with pytest.raises(protocol.ProtocolRefused):
        protocol.canonical_json({"bad": float("nan")})
    with pytest.raises(protocol.ProtocolRefused):
        protocol.canonical_json({"bad": object()})


@pytest.mark.parametrize(
    "key",
    [b"x" * 31, b"x" * 33, bytearray(b"x" * 32), "x" * 32],
)
def test_channel_key_is_exactly_32_immutable_bytes(key: object) -> None:
    from containers.galaxy import state_store_protocol as protocol

    with pytest.raises(protocol.ProtocolRefused, match="channel key"):
        _outbound(protocol, key=key)
    with pytest.raises(protocol.ProtocolRefused, match="channel key"):
        protocol.RequestVerifier(
            channel_key=key,
            resource_id="state_store_1",
            runtime_scope=_scope(protocol),
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("controller_generation", -1),
        ("watchdog_generation", True),
        ("revocation_generation", 1.0),
        ("activation_generation", "1"),
        ("boot_generation", None),
        ("controller_child_pid", 0),
    ],
)
def test_runtime_scope_requires_exact_nonnegative_generations_and_positive_pid(
    field: str,
    value: object,
) -> None:
    from containers.galaxy import state_store_protocol as protocol

    values: dict[str, Any] = {
        "controller_generation": 1,
        "watchdog_generation": 2,
        "revocation_generation": 3,
        "activation_generation": 4,
        "boot_generation": 5,
        "controller_child_pid": 6,
    }
    values[field] = value
    with pytest.raises(protocol.ProtocolRefused, match="runtime scope"):
        protocol.RuntimeScope(**values)


@pytest.mark.parametrize("sequence", [0, -1, True, 1.0, "1"])
def test_request_sequence_is_an_exact_positive_integer(sequence: object) -> None:
    from containers.galaxy import state_store_protocol as protocol

    with pytest.raises(protocol.ProtocolRefused, match="sequence"):
        _outbound(protocol, sequence=sequence)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("request_id", ""),
        ("request_id", "contains space"),
        ("request_id", 1),
        ("resource_id", "../state"),
        ("resource_id", False),
    ],
)
def test_request_and_resource_ids_use_the_closed_identifier_vocabulary(
    field: str,
    value: object,
) -> None:
    from containers.galaxy import state_store_protocol as protocol

    with pytest.raises(protocol.ProtocolRefused, match=field):
        _outbound(protocol, **{field: value})


@pytest.mark.parametrize("logical_request", [[], "request", 7, None, ("tuple",)])
def test_logical_request_must_be_a_json_object(logical_request: object) -> None:
    from containers.galaxy import state_store_protocol as protocol

    with pytest.raises(protocol.ProtocolRefused, match="request.*object"):
        _outbound(protocol, request=logical_request)


def test_request_encoding_snapshots_nested_mutable_json() -> None:
    from containers.galaxy import state_store_protocol as protocol

    request: dict[str, Any] = {
        "database_id": "runtime",
        "values": [1, {"safe": True}],
    }
    outbound = _outbound(protocol, request=request)
    request["values"][1]["safe"] = False
    request["values"].append(2)
    verified = protocol.RequestVerifier(
        channel_key=b"k" * 32,
        resource_id="state_store_1",
        runtime_scope=_scope(protocol),
    ).verify(outbound.frame)
    assert verified.request == {
        "database_id": "runtime",
        "values": [1, {"safe": True}],
    }
    assert verified.request is not request


def test_request_encoding_uses_one_canonical_projection_during_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A retained nested value cannot change between digest and transport."""

    from containers.galaxy import state_store_protocol as protocol

    request = {"database_id": "runtime", "value": {"safe": True}}
    original = protocol.canonical_json
    projected = False

    def mutate_after_first_projection(value: object) -> bytes:
        nonlocal projected
        raw = original(value)
        if value is request and not projected:
            projected = True
            request["value"]["safe"] = False
        return raw

    monkeypatch.setattr(protocol, "canonical_json", mutate_after_first_projection)
    outbound = _outbound(protocol, request=request)
    verified = protocol.RequestVerifier(
        channel_key=b"k" * 32,
        resource_id="state_store_1",
        runtime_scope=_scope(protocol),
    ).verify(outbound.frame)

    assert projected
    assert request == {"database_id": "runtime", "value": {"safe": False}}
    assert verified.request == {
        "database_id": "runtime",
        "value": {"safe": True},
    }


def test_request_verifier_rejects_unsigned_unknown_missing_and_noncanonical_frames() -> None:
    from containers.galaxy import state_store_protocol as protocol

    outbound = _outbound(protocol)
    envelope = json.loads(outbound.frame)
    verifier_args = {
        "channel_key": b"k" * 32,
        "resource_id": "state_store_1",
        "runtime_scope": _scope(protocol),
    }
    malformed: list[object] = []
    unsigned = dict(envelope)
    unsigned.pop("signature")
    malformed.append(protocol.canonical_json(unsigned))
    unknown = {**envelope, "surprise": True}
    malformed.append(protocol.canonical_json(unknown))
    missing = dict(envelope)
    missing.pop("request_digest")
    malformed.append(protocol.canonical_json(missing))
    malformed.append(b" " + outbound.frame)
    malformed.append(outbound.frame + b"\n")
    malformed.append(outbound.frame.decode("utf-8"))
    malformed.append(bytearray(outbound.frame))

    for frame in malformed:
        with pytest.raises(protocol.ProtocolRefused):
            protocol.RequestVerifier(**verifier_args).verify(frame)


def test_request_verifier_rejects_duplicate_json_members() -> None:
    from containers.galaxy import state_store_protocol as protocol

    duplicate = b'{"schema":"one","schema":"two"}'
    with pytest.raises(protocol.ProtocolRefused, match="duplicate"):
        protocol.RequestVerifier(
            channel_key=b"k" * 32,
            resource_id="state_store_1",
            runtime_scope=_scope(protocol),
        ).verify(duplicate)


@pytest.mark.parametrize(
    "mutation",
    ["schema", "resource", "scope", "sequence", "digest", "request", "signature"],
)
def test_request_verifier_rejects_authenticated_field_mismatch_or_mutation(
    mutation: str,
) -> None:
    from containers.galaxy import state_store_protocol as protocol

    key = b"k" * 32
    envelope = json.loads(_outbound(protocol, key=key).frame)
    if mutation == "schema":
        envelope["schema"] = "galaxy.state-store.request/v2"
    elif mutation == "resource":
        envelope["resource_id"] = "state_store_2"
    elif mutation == "scope":
        envelope["runtime_scope"]["boot_generation"] += 1
    elif mutation == "sequence":
        envelope["sequence"] = 2
    elif mutation == "digest":
        envelope["request_digest"] = "0" * 64
    elif mutation == "request":
        envelope["request"]["operation"] = "kv_delete"
    elif mutation == "signature":
        envelope["signature"] = "0" * 64
    if mutation != "signature":
        frame = _resign(
            protocol,
            envelope,
            key,
            b"GALAXY-R3/state-store/request/v1\x00",
        )
    else:
        frame = protocol.canonical_json(envelope)

    with pytest.raises(protocol.ProtocolRefused):
        protocol.RequestVerifier(
            channel_key=key,
            resource_id="state_store_1",
            runtime_scope=_scope(protocol),
        ).verify(frame)


def test_request_signature_is_domain_separated_and_uses_compare_digest(monkeypatch) -> None:
    from containers.galaxy import state_store_protocol as protocol

    outbound = _outbound(protocol)
    envelope = json.loads(outbound.frame)
    unsigned = dict(envelope)
    actual = unsigned.pop("signature")
    response_domain_signature = hmac.new(
        b"k" * 32,
        b"GALAXY-R3/state-store/response/v1\x00" + protocol.canonical_json(unsigned),
        hashlib.sha256,
    ).hexdigest()
    assert actual != response_domain_signature

    calls: list[tuple[object, object]] = []
    original = hmac.compare_digest

    def observed(left, right):
        calls.append((left, right))
        return original(left, right)

    monkeypatch.setattr(protocol.hmac, "compare_digest", observed)
    protocol.RequestVerifier(
        channel_key=b"k" * 32,
        resource_id="state_store_1",
        runtime_scope=_scope(protocol),
    ).verify(outbound.frame)
    assert calls


def test_request_verifier_rejects_replay_gap_and_out_of_order_without_consuming_cursor() -> None:
    from containers.galaxy import state_store_protocol as protocol

    key = b"k" * 32
    verifier = protocol.RequestVerifier(
        channel_key=key,
        resource_id="state_store_1",
        runtime_scope=_scope(protocol),
    )
    first = _outbound(protocol, key=key, sequence=1)
    verifier.verify(first.frame)
    with pytest.raises(protocol.ProtocolRefused, match="sequence"):
        verifier.verify(first.frame)
    with pytest.raises(protocol.ProtocolRefused, match="sequence"):
        verifier.verify(_outbound(protocol, key=key, sequence=3).frame)

    bad_second = bytearray(_outbound(protocol, key=key, sequence=2).frame)
    bad_second[-2] = ord("0") if bad_second[-2] != ord("0") else ord("1")
    with pytest.raises(protocol.ProtocolRefused):
        verifier.verify(bytes(bad_second))
    assert verifier.verify(_outbound(protocol, key=key, sequence=2).frame).sequence == 2


def test_response_accepts_detached_scalar_json_result_and_valid_statuses() -> None:
    from containers.galaxy import state_store_protocol as protocol

    key = b"k" * 32
    for status, result in (("ok", None), ("error", "ValueError")):
        outbound, request = _verified_request(protocol, key=key)
        frame = protocol.encode_response(
            channel_key=key,
            request=request,
            status=status,
            result=result,
        )
        response = protocol.ResponseVerifier(
            channel_key=key,
            resource_id=outbound.resource_id,
            runtime_scope=outbound.runtime_scope,
        ).verify(frame, expected_request=outbound)
        assert response.result == result
        assert response.status == status


@pytest.mark.parametrize("status", ["", "success", "OK", 1, None])
def test_response_status_uses_a_closed_exact_vocabulary(status: object) -> None:
    from containers.galaxy import state_store_protocol as protocol

    _out, request = _verified_request(protocol)
    with pytest.raises(protocol.ProtocolRefused, match="status"):
        protocol.encode_response(
            channel_key=b"k" * 32,
            request=request,
            status=status,
            result=None,
        )


def test_response_encoding_snapshots_nested_mutable_json() -> None:
    from containers.galaxy import state_store_protocol as protocol

    key = b"k" * 32
    outbound, request = _verified_request(protocol, key=key)
    result = {"items": [{"safe": True}]}
    frame = protocol.encode_response(
        channel_key=key,
        request=request,
        status="ok",
        result=result,
    )
    result["items"][0]["safe"] = False
    response = protocol.ResponseVerifier(
        channel_key=key,
        resource_id=outbound.resource_id,
        runtime_scope=outbound.runtime_scope,
    ).verify(frame, expected_request=outbound)
    assert response.result == {"items": [{"safe": True}]}
    assert response.result is not result


def test_response_verifier_rejects_unsigned_unknown_missing_and_wrong_frame_types() -> None:
    from containers.galaxy import state_store_protocol as protocol

    key = b"k" * 32
    outbound, request = _verified_request(protocol, key=key)
    frame = protocol.encode_response(
        channel_key=key,
        request=request,
        status="ok",
        result={"stored": True},
    )
    envelope = json.loads(frame)
    unsigned = dict(envelope)
    unsigned.pop("signature")
    unknown = {**envelope, "extra": 1}
    missing = dict(envelope)
    missing.pop("result_digest")
    malformed: list[object] = [
        protocol.canonical_json(unsigned),
        protocol.canonical_json(unknown),
        protocol.canonical_json(missing),
        b" " + frame,
        frame.decode("utf-8"),
        bytearray(frame),
    ]
    for value in malformed:
        with pytest.raises(protocol.ProtocolRefused):
            protocol.ResponseVerifier(
                channel_key=key,
                resource_id=outbound.resource_id,
                runtime_scope=outbound.runtime_scope,
            ).verify(value, expected_request=outbound)


@pytest.mark.parametrize(
    "mutation",
    [
        "schema",
        "request_id",
        "resource",
        "scope",
        "sequence",
        "request_digest",
        "result_digest",
        "result",
        "status",
        "signature",
    ],
)
def test_response_verifier_rejects_authenticated_mismatch_mutation_or_substitution(
    mutation: str,
) -> None:
    from containers.galaxy import state_store_protocol as protocol

    key = b"k" * 32
    outbound, request = _verified_request(protocol, key=key)
    envelope = json.loads(
        protocol.encode_response(
            channel_key=key,
            request=request,
            status="ok",
            result={"stored": True},
        )
    )
    if mutation == "schema":
        envelope["schema"] = "galaxy.state-store.response/v2"
    elif mutation == "request_id":
        envelope["request_id"] = "request_other"
    elif mutation == "resource":
        envelope["resource_id"] = "state_store_other"
    elif mutation == "scope":
        envelope["runtime_scope"]["controller_generation"] += 1
    elif mutation == "sequence":
        envelope["sequence"] = 2
    elif mutation == "request_digest":
        envelope["request_digest"] = "1" * 64
    elif mutation == "result_digest":
        envelope["result_digest"] = "2" * 64
    elif mutation == "result":
        envelope["result"]["stored"] = False
    elif mutation == "status":
        envelope["status"] = "success"
    elif mutation == "signature":
        envelope["signature"] = "3" * 64
    if mutation != "signature":
        frame = _resign(
            protocol,
            envelope,
            key,
            b"GALAXY-R3/state-store/response/v1\x00",
        )
    else:
        frame = protocol.canonical_json(envelope)

    with pytest.raises(protocol.ProtocolRefused):
        protocol.ResponseVerifier(
            channel_key=key,
            resource_id=outbound.resource_id,
            runtime_scope=outbound.runtime_scope,
        ).verify(frame, expected_request=outbound)


def test_response_from_another_request_is_rejected_even_with_valid_signature() -> None:
    from containers.galaxy import state_store_protocol as protocol

    key = b"k" * 32
    expected, _expected_verified = _verified_request(protocol, key=key)
    _other, other_verified = _verified_request(
        protocol,
        key=key,
        request_id="request_other",
        request={"database_id": "other", "operation": "kv_get"},
    )
    substituted = protocol.encode_response(
        channel_key=key,
        request=other_verified,
        status="ok",
        result={"secret": True},
    )
    with pytest.raises(protocol.ProtocolRefused):
        protocol.ResponseVerifier(
            channel_key=key,
            resource_id=expected.resource_id,
            runtime_scope=expected.runtime_scope,
        ).verify(substituted, expected_request=expected)


def test_response_verifier_rejects_replay_and_preserves_cursor_after_bad_signature() -> None:
    from containers.galaxy import state_store_protocol as protocol

    key = b"k" * 32
    first, first_verified = _verified_request(protocol, key=key, sequence=1)
    first_frame = protocol.encode_response(
        channel_key=key,
        request=first_verified,
        status="ok",
        result={"sequence": 1},
    )
    verifier = protocol.ResponseVerifier(
        channel_key=key,
        resource_id=first.resource_id,
        runtime_scope=first.runtime_scope,
    )
    verifier.verify(first_frame, expected_request=first)
    with pytest.raises(protocol.ProtocolRefused, match="sequence"):
        verifier.verify(first_frame, expected_request=first)

    second, second_verified = _verified_request(protocol, key=key, sequence=2)
    second_frame = protocol.encode_response(
        channel_key=key,
        request=second_verified,
        status="ok",
        result={"sequence": 2},
    )
    broken = bytearray(second_frame)
    broken[-2] = ord("0") if broken[-2] != ord("0") else ord("1")
    with pytest.raises(protocol.ProtocolRefused):
        verifier.verify(bytes(broken), expected_request=second)
    assert verifier.verify(second_frame, expected_request=second).sequence == 2


def test_response_requires_exact_outbound_request_receipt() -> None:
    from containers.galaxy import state_store_protocol as protocol

    key = b"k" * 32
    outbound, request = _verified_request(protocol, key=key)
    frame = protocol.encode_response(
        channel_key=key,
        request=request,
        status="ok",
        result=None,
    )
    with pytest.raises(protocol.ProtocolRefused, match="outbound request"):
        protocol.ResponseVerifier(
            channel_key=key,
            resource_id=outbound.resource_id,
            runtime_scope=outbound.runtime_scope,
        ).verify(frame, expected_request=replace(outbound, request_id="request_other"))


def test_response_rejects_forged_receipt_metadata_even_when_it_matches_substitution() -> None:
    from containers.galaxy import state_store_protocol as protocol

    key = b"k" * 32
    original, _original_verified = _verified_request(protocol, key=key)
    other, other_verified = _verified_request(
        protocol,
        key=key,
        request_id="request_other",
        request={"database_id": "other", "operation": "kv_get"},
    )
    substituted = protocol.encode_response(
        channel_key=key,
        request=other_verified,
        status="ok",
        result={"secret": True},
    )
    forged_receipt = replace(
        original,
        request_id=other.request_id,
        request_digest=other.request_digest,
    )

    with pytest.raises(protocol.ProtocolRefused, match="outbound request"):
        protocol.ResponseVerifier(
            channel_key=key,
            resource_id=original.resource_id,
            runtime_scope=original.runtime_scope,
        ).verify(substituted, expected_request=forged_receipt)


def test_whole_frame_quota_includes_envelope_overhead_for_both_directions(
    monkeypatch,
) -> None:
    from containers.galaxy import state_store_protocol as protocol

    key = b"k" * 32
    payload = {"value": "x" * 300}
    assert len(protocol.canonical_json(payload)) < 512
    monkeypatch.setattr(protocol, "MAX_FRAME_BYTES", 512)
    with pytest.raises(protocol.ProtocolRefused, match="frame.*quota"):
        _outbound(protocol, key=key, request=payload)

    monkeypatch.setattr(protocol, "MAX_FRAME_BYTES", 4 * 1024 * 1024)
    _out, request = _verified_request(protocol, key=key)
    monkeypatch.setattr(protocol, "MAX_FRAME_BYTES", 512)
    with pytest.raises(protocol.ProtocolRefused, match="frame.*quota"):
        protocol.encode_response(
            channel_key=key,
            request=request,
            status="ok",
            result=payload,
        )


def test_exact_frame_quota_boundary_and_shared_decode_limit(monkeypatch) -> None:
    from containers.galaxy import state_store_protocol as protocol

    key = b"k" * 32
    outbound = _outbound(protocol, key=key)
    monkeypatch.setattr(protocol, "MAX_FRAME_BYTES", len(outbound.frame))
    exact = _outbound(protocol, key=key)
    assert exact.frame == outbound.frame
    protocol.RequestVerifier(
        channel_key=key,
        resource_id=outbound.resource_id,
        runtime_scope=outbound.runtime_scope,
    ).verify(exact.frame)

    monkeypatch.setattr(protocol, "MAX_FRAME_BYTES", len(outbound.frame) - 1)
    with pytest.raises(protocol.ProtocolRefused, match="frame.*quota"):
        _outbound(protocol, key=key)
    with pytest.raises(protocol.ProtocolRefused, match="frame.*quota"):
        protocol.RequestVerifier(
            channel_key=key,
            resource_id=outbound.resource_id,
            runtime_scope=outbound.runtime_scope,
        ).verify(outbound.frame)

    monkeypatch.setattr(protocol, "MAX_FRAME_BYTES", 4 * 1024 * 1024)
    outbound, request = _verified_request(protocol, key=key)
    response = protocol.encode_response(
        channel_key=key,
        request=request,
        status="ok",
        result={"ok": True},
    )
    monkeypatch.setattr(protocol, "MAX_FRAME_BYTES", len(response) - 1)
    with pytest.raises(protocol.ProtocolRefused, match="frame.*quota"):
        protocol.ResponseVerifier(
            channel_key=key,
            resource_id=outbound.resource_id,
            runtime_scope=outbound.runtime_scope,
        ).verify(response, expected_request=outbound)


def test_channel_key_material_is_never_serialized_into_frames() -> None:
    from containers.galaxy import state_store_protocol as protocol

    key = b"q" * 32
    outbound, request = _verified_request(protocol, key=key)
    response = protocol.encode_response(
        channel_key=key,
        request=request,
        status="ok",
        result={"ok": True},
    )
    assert key not in outbound.frame
    assert key not in response
