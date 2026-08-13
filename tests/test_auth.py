import pytest

from talos_panel.auth import (
    consume_recovery_code,
    content_security_policy,
    generate_recovery_codes,
    hash_password,
    token_hash,
    verify_password,
)


def test_passwords_use_argon2_and_verify() -> None:
    encoded = hash_password("a-strong-test-password")
    assert encoded.startswith("$argon2id$")
    assert verify_password(encoded, "a-strong-test-password")
    assert not verify_password(encoded, "wrong-password")


def test_short_password_is_rejected() -> None:
    with pytest.raises(ValueError, match="12"):
        hash_password("too-short")


def test_session_tokens_are_stored_as_hashes() -> None:
    assert token_hash("secret-token") != "secret-token"
    assert len(token_hash("secret-token")) == 64


def test_recovery_codes_are_stored_as_hashes_and_consumed_once() -> None:
    codes, stored = generate_recovery_codes()

    assert len(codes) == 10
    assert len(set(codes)) == 10
    assert all(code not in stored for code in codes)

    accepted, remaining = consume_recovery_code(stored, codes[0].lower())
    reused, _ = consume_recovery_code(remaining, codes[0])

    assert accepted is True
    assert reused is False


def test_invalid_recovery_code_does_not_change_stored_codes() -> None:
    _, stored = generate_recovery_codes()
    accepted, remaining = consume_recovery_code(stored, "not-a-recovery-code")
    assert accepted is False
    assert remaining == stored


def test_swagger_csp_allows_its_assets_without_weakening_application_pages() -> None:
    assert "https://cdn.jsdelivr.net" in content_security_policy("/docs")
    assert "https://cdn.jsdelivr.net" in content_security_policy("/docs/oauth2-redirect")
    assert "https://cdn.jsdelivr.net" not in content_security_policy("/")
