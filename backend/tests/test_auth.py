import pytest
from pydantic import ValidationError

from app.auth import hash_password, verify_password
from app.schemas import LoginRequest, RegisterRequest


def test_hash_and_verify_password() -> None:
    hashed = hash_password("secret-pass")
    assert hashed.startswith("$argon2id$")
    assert verify_password("secret-pass", hashed)
    assert not verify_password("wrong-pass", hashed)


def test_verify_password_returns_false_for_invalid_hash() -> None:
    assert verify_password("secret-pass", "not-a-valid-hash") is False


def test_register_request_normalizes_email() -> None:
    payload = RegisterRequest(email="  Demo@Local  ", password="secret-pass")
    assert payload.email == "demo@local"


def test_login_request_rejects_invalid_email() -> None:
    with pytest.raises(ValidationError):
        LoginRequest(email="invalid-email", password="secret-pass")
