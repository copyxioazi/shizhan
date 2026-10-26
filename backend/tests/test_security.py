import pytest
from app.core.errors import ApiError
from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)


def test_password_hash_roundtrip():
    hashed = hash_password("demo12345")
    assert hashed.startswith("$2")
    assert hashed != "demo12345"
    assert verify_password("demo12345", hashed)
    assert not verify_password("wrong-password", hashed)


def test_jwt_roundtrip():
    token, expires_in = create_access_token(42, "demo", "user")
    assert expires_in == 86400
    payload = decode_access_token(token)
    assert payload["user_id"] == 42
    assert payload["username"] == "demo"
    assert payload["role"] == "user"
    assert payload["exp"] - payload["iat"] == 86400


def test_invalid_token_rejected():
    with pytest.raises(ApiError) as exc_info:
        decode_access_token("not-a-valid-token")
    assert exc_info.value.code == 1002
