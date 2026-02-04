from app.auth import hash_password, verify_password


def test_hash_and_verify_password() -> None:
    hashed = hash_password("secret-pass")
    assert verify_password("secret-pass", hashed)
    assert not verify_password("wrong-pass", hashed)
