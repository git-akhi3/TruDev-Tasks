from __future__ import annotations

from datetime import datetime, timedelta, timezone
from importlib import import_module
from unittest.mock import AsyncMock

import pytest


def _resolve(module_name: str, fallback: str):
    try:
        return import_module(module_name)
    except ModuleNotFoundError:
        return import_module(fallback)


config_mod = _resolve("pulsepay.core.config", "core.config")
settings = config_mod.settings

pytestmark = [pytest.mark.grader, pytest.mark.task("feature_004")]


def _load_circuit_breaker_class():
    try:
        module = import_module("pulsepay.core.circuit_breaker")
    except ModuleNotFoundError:
        try:
            module = import_module("core.circuit_breaker")
        except ModuleNotFoundError:
            pytest.fail("CircuitBreaker class is missing in core/circuit_breaker.py")

    circuit_breaker_cls = getattr(module, "CircuitBreaker", None)
    if circuit_breaker_cls is None:
        pytest.fail("CircuitBreaker class is missing in core/circuit_breaker.py")
    return circuit_breaker_cls


@pytest.mark.anyio
async def test_circuit_opens_after_threshold_failures():
    """Circuit breaker should transition to open after configured consecutive failures."""
    CircuitBreaker = _load_circuit_breaker_class()
    circuit = CircuitBreaker(
        failure_threshold=settings().CIRCUIT_BREAKER_FAILURE_THRESHOLD,
        recovery_timeout_seconds=settings().CIRCUIT_BREAKER_RECOVERY_TIMEOUT,
        half_open_max_calls=settings().CIRCUIT_BREAKER_HALF_OPEN_MAX_CALLS,
    )

    for _ in range(settings().CIRCUIT_BREAKER_FAILURE_THRESHOLD):
        await circuit.record_failure()

    assert circuit.state == "open"


@pytest.mark.anyio
async def test_open_circuit_fails_fast_without_calling_processor():
    """Open circuit state should fail fast and skip invoking the wrapped processor call."""
    CircuitBreaker = _load_circuit_breaker_class()
    circuit = CircuitBreaker(
        failure_threshold=settings().CIRCUIT_BREAKER_FAILURE_THRESHOLD,
        recovery_timeout_seconds=settings().CIRCUIT_BREAKER_RECOVERY_TIMEOUT,
        half_open_max_calls=settings().CIRCUIT_BREAKER_HALF_OPEN_MAX_CALLS,
    )

    processor = AsyncMock(return_value={"ok": True})
    circuit.state = "open"
    circuit.last_failure_time = datetime.now(timezone.utc)

    with pytest.raises(Exception) as exc:
        await circuit.call(processor)

    assert processor.call_count == 0
    assert "circuit_open" in str(exc.value).lower()


@pytest.mark.anyio
async def test_half_open_transitions_to_closed_on_success():
    """Half-open probe success should transition the circuit back to closed state."""
    CircuitBreaker = _load_circuit_breaker_class()
    circuit = CircuitBreaker(
        failure_threshold=settings().CIRCUIT_BREAKER_FAILURE_THRESHOLD,
        recovery_timeout_seconds=settings().CIRCUIT_BREAKER_RECOVERY_TIMEOUT,
        half_open_max_calls=settings().CIRCUIT_BREAKER_HALF_OPEN_MAX_CALLS,
    )

    circuit.state = "open"
    circuit.last_failure_time = datetime.now(timezone.utc) - timedelta(seconds=settings().CIRCUIT_BREAKER_RECOVERY_TIMEOUT + 1)

    async def _processor():
        return {"status": "ok"}

    await circuit.call(_processor)
    assert circuit.state == "closed"


@pytest.mark.anyio
async def test_circuit_state_in_metrics_endpoint(app_client):
    """Metrics endpoint should expose the current circuit breaker state value."""
    response = await app_client.get("/v1/metrics")
    assert response.status_code == 200

    payload = response.json()
    assert "circuit_breaker_state" in payload
    assert payload["circuit_breaker_state"] in {"closed", "open", "half_open"}
