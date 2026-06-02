"""Tests for the redaction helper."""

from __future__ import annotations

from bybit_mcp.safety.redaction import is_sensitive_arg, redact_payload


def test_credential_keys_redacted():
    payload = {"api_key": "abc", "secret": "xyz", "token": "tok"}
    scrubbed = redact_payload(payload)
    assert scrubbed == {"api_key": "[redacted]", "secret": "[redacted]", "token": "[redacted]"}


def test_marker_substring_keys_redacted():
    """``*token*``-style markers and access_token / refresh_token get scrubbed."""
    for key in ("access_token", "refresh_token", "x_api_key", "api_secret", "password"):
        assert redact_payload({key: "v"}) == {key: "[redacted]"}


def test_pii_exact_keys_redacted():
    for key in ("account_number", "routing_number", "ssn", "tin"):
        assert redact_payload({key: "v"}) == {key: "[redacted]"}


def test_account_ref_preserved():
    """account_ref is the OPAQUE accountability chain — must NOT be scrubbed."""
    payload = {"account_ref": "acct-0001", "account_id": "PII123"}
    scrubbed = redact_payload(payload)
    assert scrubbed == {"account_ref": "acct-0001", "account_id": "[redacted]"}


def test_camel_case_variants_redacted():
    for key in ("apiKey", "accessToken", "routingNumber", "socialSecurityNumber"):
        assert redact_payload({key: "v"}) == {key: "[redacted]"}


def test_benign_keys_pass_through():
    payload = {"symbol": "BTCUSDT", "qty": "0.001", "price": "65000", "side": "Buy"}
    assert redact_payload(payload) == payload


def test_nested_structures():
    payload = {
        "order": {
            "symbol": "BTCUSDT",
            "broker_request": {"api_key": "abc", "qty": "0.001"},
        },
        "history": [{"token": "x"}, {"safe": "y"}],
    }
    scrubbed = redact_payload(payload)
    assert scrubbed == {
        "order": {
            "symbol": "BTCUSDT",
            "broker_request": {"api_key": "[redacted]", "qty": "0.001"},
        },
        "history": [{"token": "[redacted]"}, {"safe": "y"}],
    }


def test_is_sensitive_arg_classifier():
    assert is_sensitive_arg("api_key") is True
    assert is_sensitive_arg("access_token") is True
    assert is_sensitive_arg("accountNumber") is True
    assert is_sensitive_arg("symbol") is False
    assert is_sensitive_arg("qty") is False
    assert is_sensitive_arg("account_ref") is False  # preserved intentionally
