"""Canonical authenticated frames for the isolated state-store RPC.

The protocol is deliberately independent of the host controller and the
container engine.  Both peers retain their own monotonically increasing cursor,
authenticate the complete canonical envelope, and reject an invalid frame
without consuming that cursor.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import threading
from dataclasses import dataclass
from typing import cast

CHANNEL_KEY_BYTES = 32
MAX_FRAME_BYTES = 4 * 1024 * 1024
REQUEST_SCHEMA = "galaxy.state-store.request/v1"
RESPONSE_SCHEMA = "galaxy.state-store.response/v1"

_REQUEST_DOMAIN = b"GALAXY-R3/state-store/request/v1\x00"
_RESPONSE_DOMAIN = b"GALAXY-R3/state-store/response/v1\x00"
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_SCOPE_FIELDS = frozenset(
    {
        "activation_generation",
        "boot_generation",
        "controller_child_pid",
        "controller_generation",
        "revocation_generation",
        "watchdog_generation",
    }
)
_REQUEST_FIELDS = frozenset(
    {
        "request",
        "request_digest",
        "request_id",
        "resource_id",
        "runtime_scope",
        "schema",
        "sequence",
        "signature",
    }
)
_RESPONSE_FIELDS = frozenset(
    {
        "request_digest",
        "request_id",
        "resource_id",
        "result",
        "result_digest",
        "runtime_scope",
        "schema",
        "sequence",
        "signature",
        "status",
    }
)
_STATUSES = frozenset({"error", "ok"})


class ProtocolRefused(RuntimeError):
    """A state-store frame or its expected authority binding is invalid."""


def _validate_channel_key(value: object) -> bytes:
    if type(value) is not bytes or len(value) != CHANNEL_KEY_BYTES:
        raise ProtocolRefused(
            f"state-store channel key must be exactly {CHANNEL_KEY_BYTES} immutable bytes"
        )
    return value


def _validate_identifier(value: object, name: str) -> str:
    if type(value) is not str or not _ID.fullmatch(value):
        raise ProtocolRefused(f"state-store {name} is invalid")
    return value


def _validate_sequence(value: object, *, allow_zero: bool = False) -> int:
    minimum = 0 if allow_zero else 1
    if type(value) is not int or value < minimum:
        qualifier = "nonnegative" if allow_zero else "positive"
        raise ProtocolRefused(f"state-store sequence must be an exact {qualifier} integer")
    return value


def _validate_digest(value: object, name: str) -> str:
    if type(value) is not str or not _DIGEST.fullmatch(value):
        raise ProtocolRefused(f"state-store {name} is invalid")
    return value


def _canonical_json_unchecked(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (RecursionError, TypeError, ValueError, UnicodeEncodeError) as exc:
        raise ProtocolRefused("state-store value is not canonical JSON") from exc


def canonical_json(value: object) -> bytes:
    """Return the sole deterministic UTF-8 representation used by the protocol."""

    encoded = _canonical_json_unchecked(value)
    # Round-trip validation ensures the signed representation is valid JSON;
    # encode_request/encode_response subsequently retain only its detached form.
    _decode_json(encoded)
    return encoded


def _reject_duplicate_members(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ProtocolRefused("state-store JSON contains a duplicate member")
        value[key] = item
    return value


def _decode_json(value: bytes) -> object:
    try:
        return json.loads(
            value.decode("utf-8", errors="strict"),
            object_pairs_hook=_reject_duplicate_members,
            parse_constant=lambda _value: (_ for _ in ()).throw(
                ProtocolRefused("state-store JSON constant is invalid")
            ),
        )
    except ProtocolRefused:
        raise
    except (RecursionError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ProtocolRefused("state-store frame is not valid JSON") from exc


def _detach_object(value: object, name: str) -> dict[str, object]:
    detached = _decode_json(canonical_json(value))
    if type(detached) is not dict:
        raise ProtocolRefused(f"state-store {name} must be a JSON object")
    return cast(dict[str, object], detached)


def _bounded_frame(value: dict[str, object]) -> bytes:
    frame = canonical_json(value)
    if len(frame) > MAX_FRAME_BYTES:
        raise ProtocolRefused("state-store whole frame exceeds its quota")
    return frame


def _decode_frame(frame: object) -> dict[str, object]:
    if type(frame) is not bytes:
        raise ProtocolRefused("state-store frame must be exact immutable bytes")
    if not frame or len(frame) > MAX_FRAME_BYTES:
        raise ProtocolRefused("state-store whole frame exceeds its quota")
    value = _decode_json(frame)
    if type(value) is not dict:
        raise ProtocolRefused("state-store envelope must be a JSON object")
    if canonical_json(value) != frame:
        raise ProtocolRefused("state-store frame is not canonical JSON")
    return value


def _require_exact_fields(
    value: dict[str, object],
    expected: frozenset[str],
    name: str,
) -> None:
    if frozenset(value) != expected:
        raise ProtocolRefused(f"state-store {name} fields differ from the closed schema")


def _digest_json(value: object) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def _sign(
    channel_key: bytes,
    domain: bytes,
    unsigned: dict[str, object],
) -> str:
    return hmac.new(
        channel_key,
        domain + canonical_json(unsigned),
        hashlib.sha256,
    ).hexdigest()


def _verify_signature(
    *,
    channel_key: bytes,
    domain: bytes,
    envelope: dict[str, object],
) -> None:
    signature = _validate_digest(envelope.get("signature"), "signature")
    unsigned = dict(envelope)
    del unsigned["signature"]
    expected = _sign(channel_key, domain, unsigned)
    if not hmac.compare_digest(signature, expected):
        raise ProtocolRefused("state-store frame signature differs")


@dataclass(frozen=True, slots=True)
class RuntimeScope:
    """Exact installed-controller generations bound into every frame."""

    controller_generation: int
    watchdog_generation: int
    revocation_generation: int
    activation_generation: int
    boot_generation: int
    controller_child_pid: int

    def __post_init__(self) -> None:
        generations = (
            self.controller_generation,
            self.watchdog_generation,
            self.revocation_generation,
            self.activation_generation,
            self.boot_generation,
        )
        if any(type(value) is not int or value < 0 for value in generations) or (
            type(self.controller_child_pid) is not int
            or self.controller_child_pid <= 0
        ):
            raise ProtocolRefused(
                "state-store runtime scope requires exact nonnegative generations "
                "and a positive controller child PID"
            )

    def to_dict(self) -> dict[str, int]:
        return {
            "activation_generation": self.activation_generation,
            "boot_generation": self.boot_generation,
            "controller_child_pid": self.controller_child_pid,
            "controller_generation": self.controller_generation,
            "revocation_generation": self.revocation_generation,
            "watchdog_generation": self.watchdog_generation,
        }


def _decode_scope(value: object) -> RuntimeScope:
    if type(value) is not dict or frozenset(value) != _SCOPE_FIELDS:
        raise ProtocolRefused("state-store runtime scope fields differ")
    return RuntimeScope(
        controller_generation=value["controller_generation"],
        watchdog_generation=value["watchdog_generation"],
        revocation_generation=value["revocation_generation"],
        activation_generation=value["activation_generation"],
        boot_generation=value["boot_generation"],
        controller_child_pid=value["controller_child_pid"],
    )


def _validate_scope(value: object) -> RuntimeScope:
    if type(value) is not RuntimeScope:
        raise ProtocolRefused("exact state-store runtime scope is required")
    # Reconstruct so a future relaxed constructor cannot bypass this boundary.
    return _decode_scope(value.to_dict())


@dataclass(frozen=True, slots=True)
class OutboundRequest:
    """Client-owned receipt for one exact request frame."""

    frame: bytes
    request_id: str
    sequence: int
    resource_id: str
    runtime_scope: RuntimeScope
    request_digest: str


@dataclass(frozen=True, slots=True)
class VerifiedRequest:
    """Detached request authenticated by a worker-side verifier."""

    request_id: str
    sequence: int
    resource_id: str
    runtime_scope: RuntimeScope
    request_digest: str
    request: dict[str, object]


@dataclass(frozen=True, slots=True)
class VerifiedResponse:
    """Detached response authenticated against one outbound request."""

    request_id: str
    sequence: int
    resource_id: str
    runtime_scope: RuntimeScope
    request_digest: str
    result_digest: str
    status: str
    result: object


def encode_request(
    *,
    channel_key: bytes,
    request_id: str,
    sequence: int,
    resource_id: str,
    runtime_scope: RuntimeScope,
    request: dict[str, object],
) -> OutboundRequest:
    """Create one canonical request frame and its local matching receipt."""

    key = _validate_channel_key(channel_key)
    request_id = _validate_identifier(request_id, "request_id")
    resource_id = _validate_identifier(resource_id, "resource_id")
    sequence = _validate_sequence(sequence)
    scope = _validate_scope(runtime_scope)
    if type(request) is not dict:
        raise ProtocolRefused("state-store logical request must be a JSON object")
    request_raw = canonical_json(request)
    detached_value = _decode_json(request_raw)
    if type(detached_value) is not dict:  # pragma: no cover - exact input guard above
        raise ProtocolRefused("state-store logical request must be a JSON object")
    detached_request = cast(dict[str, object], detached_value)
    request_digest = hashlib.sha256(request_raw).hexdigest()
    unsigned: dict[str, object] = {
        "request": detached_request,
        "request_digest": request_digest,
        "request_id": request_id,
        "resource_id": resource_id,
        "runtime_scope": scope.to_dict(),
        "schema": REQUEST_SCHEMA,
        "sequence": sequence,
    }
    envelope = {
        **unsigned,
        "signature": _sign(key, _REQUEST_DOMAIN, unsigned),
    }
    return OutboundRequest(
        frame=_bounded_frame(envelope),
        request_id=request_id,
        sequence=sequence,
        resource_id=resource_id,
        runtime_scope=scope,
        request_digest=request_digest,
    )


class RequestVerifier:
    """Authenticate strictly increasing client requests at the worker."""

    def __init__(
        self,
        *,
        channel_key: bytes,
        resource_id: str,
        runtime_scope: RuntimeScope,
        initial_sequence: int = 0,
    ) -> None:
        self._key = _validate_channel_key(channel_key)
        self._resource_id = _validate_identifier(resource_id, "resource_id")
        self._runtime_scope = _validate_scope(runtime_scope)
        self._last_sequence = _validate_sequence(initial_sequence, allow_zero=True)
        self._lock = threading.Lock()

    def verify(self, frame: bytes) -> VerifiedRequest:
        with self._lock:
            envelope = _decode_frame(frame)
            _require_exact_fields(envelope, _REQUEST_FIELDS, "request envelope")
            if envelope["schema"] != REQUEST_SCHEMA:
                raise ProtocolRefused("state-store request schema differs")
            request_id = _validate_identifier(envelope["request_id"], "request_id")
            resource_id = _validate_identifier(envelope["resource_id"], "resource_id")
            sequence = _validate_sequence(envelope["sequence"])
            scope = _decode_scope(envelope["runtime_scope"])
            request_digest = _validate_digest(
                envelope["request_digest"],
                "request digest",
            )
            request = envelope["request"]
            if type(request) is not dict:
                raise ProtocolRefused("state-store logical request must be a JSON object")
            if resource_id != self._resource_id:
                raise ProtocolRefused("state-store request resource differs")
            if scope != self._runtime_scope:
                raise ProtocolRefused("state-store request runtime scope differs")
            if sequence != self._last_sequence + 1:
                raise ProtocolRefused("state-store request sequence is not the exact next value")
            actual_digest = _digest_json(request)
            if not hmac.compare_digest(request_digest, actual_digest):
                raise ProtocolRefused("state-store request digest differs")
            _verify_signature(
                channel_key=self._key,
                domain=_REQUEST_DOMAIN,
                envelope=envelope,
            )
            detached = _detach_object(request, "logical request")
            result = VerifiedRequest(
                request_id=request_id,
                sequence=sequence,
                resource_id=resource_id,
                runtime_scope=scope,
                request_digest=request_digest,
                request=detached,
            )
            self._last_sequence = sequence
            return result


def _validate_verified_request(value: object) -> VerifiedRequest:
    if type(value) is not VerifiedRequest:
        raise ProtocolRefused("exact verified state-store request is required")
    request_id = _validate_identifier(value.request_id, "request_id")
    resource_id = _validate_identifier(value.resource_id, "resource_id")
    sequence = _validate_sequence(value.sequence)
    scope = _validate_scope(value.runtime_scope)
    request_digest = _validate_digest(value.request_digest, "request digest")
    if type(value.request) is not dict:
        raise ProtocolRefused("verified state-store request digest differs")
    request_raw = canonical_json(value.request)
    if not hmac.compare_digest(
        request_digest,
        hashlib.sha256(request_raw).hexdigest(),
    ):
        raise ProtocolRefused("verified state-store request digest differs")
    detached_request = _decode_json(request_raw)
    if type(detached_request) is not dict:  # pragma: no cover - exact guard above
        raise ProtocolRefused("verified state-store request digest differs")
    return VerifiedRequest(
        request_id=request_id,
        sequence=sequence,
        resource_id=resource_id,
        runtime_scope=scope,
        request_digest=request_digest,
        request=cast(dict[str, object], detached_request),
    )


def encode_response(
    *,
    channel_key: bytes,
    request: VerifiedRequest,
    status: str,
    result: object,
) -> bytes:
    """Create one response bound to an authenticated request and runtime."""

    key = _validate_channel_key(channel_key)
    verified = _validate_verified_request(request)
    if type(status) is not str or status not in _STATUSES:
        raise ProtocolRefused("state-store response status is invalid")
    result_raw = canonical_json(result)
    detached_result = _decode_json(result_raw)
    result_digest = hashlib.sha256(result_raw).hexdigest()
    unsigned: dict[str, object] = {
        "request_digest": verified.request_digest,
        "request_id": verified.request_id,
        "resource_id": verified.resource_id,
        "result": detached_result,
        "result_digest": result_digest,
        "runtime_scope": verified.runtime_scope.to_dict(),
        "schema": RESPONSE_SCHEMA,
        "sequence": verified.sequence,
        "status": status,
    }
    return _bounded_frame(
        {
            **unsigned,
            "signature": _sign(key, _RESPONSE_DOMAIN, unsigned),
        }
    )


def _validate_outbound_receipt(
    value: object,
    *,
    channel_key: bytes,
) -> OutboundRequest:
    if type(value) is not OutboundRequest:
        raise ProtocolRefused("exact outbound request receipt is required")
    try:
        request_id = _validate_identifier(value.request_id, "request_id")
        resource_id = _validate_identifier(value.resource_id, "resource_id")
        sequence = _validate_sequence(value.sequence)
        scope = _validate_scope(value.runtime_scope)
        request_digest = _validate_digest(value.request_digest, "request digest")
        envelope = _decode_frame(value.frame)
        _require_exact_fields(envelope, _REQUEST_FIELDS, "request envelope")
        if envelope["schema"] != REQUEST_SCHEMA:
            raise ProtocolRefused("state-store request schema differs")
        frame_request_id = _validate_identifier(envelope["request_id"], "request_id")
        frame_resource_id = _validate_identifier(envelope["resource_id"], "resource_id")
        frame_sequence = _validate_sequence(envelope["sequence"])
        frame_scope = _decode_scope(envelope["runtime_scope"])
        frame_digest = _validate_digest(envelope["request_digest"], "request digest")
        frame_request = envelope["request"]
        if type(frame_request) is not dict:
            raise ProtocolRefused("state-store logical request must be a JSON object")
        actual_digest = _digest_json(frame_request)
        if not hmac.compare_digest(frame_digest, actual_digest):
            raise ProtocolRefused("state-store request digest differs")
        _verify_signature(
            channel_key=channel_key,
            domain=_REQUEST_DOMAIN,
            envelope=envelope,
        )
        if (
            request_id != frame_request_id
            or resource_id != frame_resource_id
            or sequence != frame_sequence
            or scope != frame_scope
            or not hmac.compare_digest(request_digest, frame_digest)
        ):
            raise ProtocolRefused("outbound request metadata differs from its frame")
    except ProtocolRefused as exc:
        raise ProtocolRefused("outbound request receipt is not authentic") from exc
    return value


class ResponseVerifier:
    """Authenticate strictly increasing worker responses at the controller."""

    def __init__(
        self,
        *,
        channel_key: bytes,
        resource_id: str,
        runtime_scope: RuntimeScope,
        initial_sequence: int = 0,
    ) -> None:
        self._key = _validate_channel_key(channel_key)
        self._resource_id = _validate_identifier(resource_id, "resource_id")
        self._runtime_scope = _validate_scope(runtime_scope)
        self._last_sequence = _validate_sequence(initial_sequence, allow_zero=True)
        self._lock = threading.Lock()

    def verify(
        self,
        frame: bytes,
        *,
        expected_request: OutboundRequest,
    ) -> VerifiedResponse:
        with self._lock:
            expected_request = _validate_outbound_receipt(
                expected_request,
                channel_key=self._key,
            )
            expected_request_id = _validate_identifier(
                expected_request.request_id,
                "request_id",
            )
            expected_resource_id = _validate_identifier(
                expected_request.resource_id,
                "resource_id",
            )
            expected_sequence = _validate_sequence(expected_request.sequence)
            expected_scope = _validate_scope(expected_request.runtime_scope)
            expected_digest = _validate_digest(
                expected_request.request_digest,
                "request digest",
            )
            if (
                expected_resource_id != self._resource_id
                or expected_scope != self._runtime_scope
            ):
                raise ProtocolRefused("outbound request scope differs from verifier")

            envelope = _decode_frame(frame)
            _require_exact_fields(envelope, _RESPONSE_FIELDS, "response envelope")
            if envelope["schema"] != RESPONSE_SCHEMA:
                raise ProtocolRefused("state-store response schema differs")
            request_id = _validate_identifier(envelope["request_id"], "request_id")
            resource_id = _validate_identifier(envelope["resource_id"], "resource_id")
            sequence = _validate_sequence(envelope["sequence"])
            scope = _decode_scope(envelope["runtime_scope"])
            request_digest = _validate_digest(
                envelope["request_digest"],
                "request digest",
            )
            result_digest = _validate_digest(
                envelope["result_digest"],
                "result digest",
            )
            status = envelope["status"]
            if type(status) is not str or status not in _STATUSES:
                raise ProtocolRefused("state-store response status is invalid")
            if sequence != self._last_sequence + 1:
                raise ProtocolRefused("state-store response sequence is not the exact next value")
            if (
                request_id != expected_request_id
                or sequence != expected_sequence
                or resource_id != expected_resource_id
                or scope != expected_scope
                or not hmac.compare_digest(request_digest, expected_digest)
            ):
                raise ProtocolRefused("response differs from exact outbound request")
            actual_result_digest = _digest_json(envelope["result"])
            if not hmac.compare_digest(result_digest, actual_result_digest):
                raise ProtocolRefused("state-store response result digest differs")
            _verify_signature(
                channel_key=self._key,
                domain=_RESPONSE_DOMAIN,
                envelope=envelope,
            )
            detached_result = _decode_json(canonical_json(envelope["result"]))
            response = VerifiedResponse(
                request_id=request_id,
                sequence=sequence,
                resource_id=resource_id,
                runtime_scope=scope,
                request_digest=request_digest,
                result_digest=result_digest,
                status=status,
                result=detached_result,
            )
            self._last_sequence = sequence
            return response


__all__ = [
    "CHANNEL_KEY_BYTES",
    "MAX_FRAME_BYTES",
    "OutboundRequest",
    "ProtocolRefused",
    "REQUEST_SCHEMA",
    "RESPONSE_SCHEMA",
    "RequestVerifier",
    "ResponseVerifier",
    "RuntimeScope",
    "VerifiedRequest",
    "VerifiedResponse",
    "canonical_json",
    "encode_request",
    "encode_response",
]
