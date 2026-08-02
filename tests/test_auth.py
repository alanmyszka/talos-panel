import pytest

from talos_panel.auth import hash_password, token_hash, verify_password


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
