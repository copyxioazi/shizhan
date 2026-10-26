import pytest
from app.core.errors import ApiError
from app.services.config_service import _validate_key_value


def test_unknown_key_rejected():
    with pytest.raises(ApiError) as exc_info:
        _validate_key_value("unknown.key", 1)
    assert exc_info.value.code == 8001


def test_out_of_range_rejected():
    with pytest.raises(ApiError):
        _validate_key_value("runtime.max_concurrent_projects", 11)


def test_valid_values_normalized():
    assert _validate_key_value("sandbox.network_enabled", True) is True
    assert _validate_key_value("sandbox.command_allowlist", ["python"]) == ["python"]
    assert _validate_key_value("runtime.max_concurrent_projects", 1) == 1


def test_orchestration_mode_and_bounds():
    assert _validate_key_value("orchestration.analysis_mode", "react") == "react"
    assert _validate_key_value("orchestration.react_max_steps", 5) == 5
    with pytest.raises(ApiError):
        _validate_key_value("orchestration.analysis_mode", "unknown")
    with pytest.raises(ApiError):
        _validate_key_value("orchestration.react_max_steps", 0)


def test_orchestration_engine_values():
    assert _validate_key_value("orchestration.engine", "langgraph") == "langgraph"
    with pytest.raises(ApiError):
        _validate_key_value("orchestration.engine", "celery")


def test_verify_retry_bounds():
    assert _validate_key_value("orchestration.verify_max_retries", 1) == 1
    with pytest.raises(ApiError):
        _validate_key_value("orchestration.verify_max_retries", 4)
