"""Known-answer tests for the sealed standard-library-only receipt signer."""

from __future__ import annotations

import importlib


def _module():
    return importlib.import_module("bootstrap.galaxy_launcher.activation_crypto")


def test_ed25519_matches_rfc8032_empty_message_vector():
    mod = _module()
    seed = bytes.fromhex("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60")
    expected_public = bytes.fromhex("d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a")
    expected_signature = bytes.fromhex(
        "e5564300c360ac729086e2cc806e828a"
        "84877f1eb8e5d974d873e06522490155"
        "5fb8821590a33bacc61e39701cf9b46b"
        "d25bf5f0595bbe24655141438e7a100b"
    )
    assert mod.public_key_from_seed(seed) == expected_public
    assert mod.sign(seed, b"") == expected_signature
    assert mod.verify(expected_public, b"", expected_signature) is True


def test_ed25519_rejects_message_signature_and_public_key_substitution():
    mod = _module()
    seed = bytes(range(32))
    public_key = mod.public_key_from_seed(seed)
    signature = mod.sign(seed, b"sealed receipt")
    assert mod.verify(public_key, b"sealed receipt", signature) is True
    assert mod.verify(public_key, b"changed receipt", signature) is False
    assert mod.verify(bytes(32), b"sealed receipt", signature) is False
    assert mod.verify(public_key, b"sealed receipt", signature[:-1] + b"\0") is False
