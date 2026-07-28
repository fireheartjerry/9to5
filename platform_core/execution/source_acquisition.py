"""Public-HTTPS-only admission for external source acquisition.

This module validates authority, URL, resolution, and resource registration.  A
future engine adapter supplies the lower-level tuple firewall and transport;
their absence remains typed unavailable rather than falling back to host Git.

RUN/TEST: python -m pytest tests/execution/test_source_acquisition.py
"""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Sequence, TypeVar
from urllib.parse import SplitResult, urlsplit, urlunsplit

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,191}$")
_T = TypeVar("_T")


class SourceAcquisitionUnavailable(RuntimeError):
    """The requested source cannot pass the bounded public acquisition gate."""


def _time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise SourceAcquisitionUnavailable("source authority expiry is invalid") from exc
    if parsed.tzinfo is None:
        raise SourceAcquisitionUnavailable("source authority expiry is not absolute")
    return parsed.astimezone(timezone.utc)


def _public(address: str) -> str:
    try:
        parsed = ipaddress.ip_address(address)
    except ValueError as exc:
        raise SourceAcquisitionUnavailable("resolver returned a non-numeric address") from exc
    if not parsed.is_global:
        raise SourceAcquisitionUnavailable("source address is not globally routable")
    if parsed.version == 6 and parsed.ipv4_mapped is not None and not parsed.ipv4_mapped.is_global:
        raise SourceAcquisitionUnavailable("source address maps to a non-public IPv4 address")
    return parsed.compressed


@dataclass(frozen=True, slots=True)
class NormalizedSourceUrl:
    url: str
    hostname: str
    port: int
    http_authority: str


def normalizePublicHttpsSource(value: str) -> NormalizedSourceUrl:
    """Normalize public HTTPS syntax without DNS or filesystem observation."""

    if not isinstance(value, str) or not value or "\x00" in value or "\\" in value:
        raise SourceAcquisitionUnavailable("source URL is invalid")
    try:
        parsed: SplitResult = urlsplit(value)
        port = parsed.port or 443
    except ValueError as exc:
        raise SourceAcquisitionUnavailable("source URL is malformed") from exc
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        raise SourceAcquisitionUnavailable("only absolute HTTPS sources are implemented")
    if parsed.username is not None or parsed.password is not None:
        raise SourceAcquisitionUnavailable("credentialed source URLs are forbidden")
    if parsed.fragment or port != 443:
        raise SourceAcquisitionUnavailable("source fragments and alternate ports are unavailable")
    host = parsed.hostname.rstrip(".").lower()
    if not host or host in {"localhost", "localhost.localdomain"} or host.endswith(".local"):
        raise SourceAcquisitionUnavailable("local source authorities are forbidden")
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        try:
            host = host.encode("idna").decode("ascii")
        except UnicodeError as exc:
            raise SourceAcquisitionUnavailable("source hostname is invalid") from exc
    else:
        _public(literal.compressed)
        host = literal.compressed
    path = parsed.path or "/"
    if not path.startswith("/") or any(ord(character) < 0x20 for character in path):
        raise SourceAcquisitionUnavailable("source path is invalid")
    authority = f"[{host}]" if ":" in host else host
    normalized = urlunsplit(("https", authority, path, parsed.query, ""))
    return NormalizedSourceUrl(
        url=normalized,
        hostname=host,
        port=443,
        http_authority=host,
    )


@dataclass(frozen=True, slots=True)
class SourceAcquisitionAuthority:
    transaction_id: str
    deadline: str
    _issuer_identity: int
    _seal: object


@dataclass(frozen=True, slots=True)
class SourceAcquisitionRequest:
    transaction_id: str
    source: NormalizedSourceUrl
    numeric_addresses: tuple[str, ...]
    deadline: str


class SourceAcquisitionController:
    def __init__(
        self,
        *,
        resolver: Callable[[str], Sequence[str]],
        resource_factory: Callable[[SourceAcquisitionRequest], _T],
        process_capability: object | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._resolver = resolver
        self._resource_factory = resource_factory
        self._process_capability = process_capability
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._identity = id(self)
        self._seal = object()

    def issueAuthority(
        self,
        *,
        process_capability: object,
        transaction_id: str,
        deadline: str,
    ) -> SourceAcquisitionAuthority:
        if self._process_capability is None or process_capability is not self._process_capability:
            raise SourceAcquisitionUnavailable("process capability differs")
        if not _ID.fullmatch(transaction_id):
            raise SourceAcquisitionUnavailable("transaction_id is invalid")
        if _time(deadline) <= self._clock().astimezone(timezone.utc):
            raise SourceAcquisitionUnavailable("source authority already expired")
        return SourceAcquisitionAuthority(
            transaction_id=transaction_id,
            deadline=deadline,
            _issuer_identity=self._identity,
            _seal=self._seal,
        )

    def _validate(self, authority: object) -> SourceAcquisitionAuthority:
        if type(authority) is not SourceAcquisitionAuthority:
            raise SourceAcquisitionUnavailable("exact process-local source authority is required")
        assert isinstance(authority, SourceAcquisitionAuthority)
        if authority._issuer_identity != self._identity or authority._seal is not self._seal:
            raise SourceAcquisitionUnavailable("source authority issuer differs")
        if _time(authority.deadline) <= self._clock().astimezone(timezone.utc):
            raise SourceAcquisitionUnavailable("source authority expired")
        return authority

    def acquire(self, url: str, *, authority: object) -> _T:
        validated = self._validate(authority)
        source = normalizePublicHttpsSource(url)
        observed = tuple(self._resolver(source.hostname))
        if not observed or len(observed) > 16:
            raise SourceAcquisitionUnavailable("source resolution is empty or oversized")
        addresses = tuple(sorted({_public(value) for value in observed}))
        request = SourceAcquisitionRequest(
            transaction_id=validated.transaction_id,
            source=source,
            numeric_addresses=addresses,
            deadline=validated.deadline,
        )
        return self._resource_factory(request)


__all__ = [
    "NormalizedSourceUrl",
    "SourceAcquisitionAuthority",
    "SourceAcquisitionController",
    "SourceAcquisitionRequest",
    "SourceAcquisitionUnavailable",
    "normalizePublicHttpsSource",
]
