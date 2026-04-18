from __future__ import annotations

from datetime import datetime, timedelta, timezone
from importlib import import_module

import pytest
from sqlalchemy import select


def _resolve(module_name: str, fallback: str):
    try:
        return import_module(module_name)
    except ModuleNotFoundError:
        return import_module(fallback)


webhook_models_mod = _resolve("pulsepay.webhooks.models", "webhooks.models")
WebhookEndpoint = webhook_models_mod.WebhookEndpoint
WebhookEvent = webhook_models_mod.WebhookEvent

pytestmark = [pytest.mark.grader, pytest.mark.task("feature_003")]


async def _create_event(db_session, *, status: str, attempt_count: int = 0, replay_count: int = 0, last_replayed_at=None):
    endpoint = WebhookEndpoint(
        client_id="cust-fx003",
        url="https://merchant.example/replay",
        signing_secret="secret-fx003",
        is_active=True,
    )
    db_session.add(endpoint)
    await db_session.commit()
    await db_session.refresh(endpoint)

    event = WebhookEvent(
        endpoint_id=endpoint.id,
        event_type="payment.failed",
        payload={"payment_id": "p_fx003"},
        status=status,
        attempt_count=attempt_count,
    )
    if hasattr(event, "replay_count"):
        event.replay_count = replay_count
    if hasattr(event, "last_replayed_at"):
        event.last_replayed_at = last_replayed_at

    db_session.add(event)
    await db_session.commit()
    await db_session.refresh(event)
    return event


@pytest.mark.anyio
async def test_replay_resets_attempt_count(app_client, db_session):
    """Replay should reset webhook attempt_count to zero and queue delivery again."""
    event = await _create_event(db_session, status="failed", attempt_count=5)

    response = await app_client.post(
        f"/v1/webhooks/events/{event.id}/replay",
        headers={"X-API-Key": "grader-fx3"},
    )
    assert response.status_code == 200

    refreshed = await db_session.get(WebhookEvent, event.id)
    assert refreshed.attempt_count == 0
    assert refreshed.status == "queued"


@pytest.mark.anyio
async def test_replay_increments_replay_count(app_client, db_session):
    """Replay should increment replay_count for each allowed replay request."""
    event = await _create_event(db_session, status="failed", attempt_count=4, replay_count=0)

    first = await app_client.post(f"/v1/webhooks/events/{event.id}/replay", headers={"X-API-Key": "grader-fx3"})
    assert first.status_code == 200

    refreshed = await db_session.get(WebhookEvent, event.id)
    assert getattr(refreshed, "replay_count", None) == 1

    if hasattr(refreshed, "last_replayed_at"):
        refreshed.last_replayed_at = datetime.now(timezone.utc) - timedelta(seconds=61)
        await db_session.commit()

    second = await app_client.post(f"/v1/webhooks/events/{event.id}/replay", headers={"X-API-Key": "grader-fx3"})
    assert second.status_code == 200

    refreshed2 = await db_session.get(WebhookEvent, event.id)
    assert getattr(refreshed2, "replay_count", None) == 2


@pytest.mark.anyio
async def test_cannot_replay_running_event(app_client, db_session):
    """Replay must reject events whose delivery is currently running."""
    event = await _create_event(db_session, status="running", attempt_count=1)

    response = await app_client.post(
        f"/v1/webhooks/events/{event.id}/replay",
        headers={"X-API-Key": "grader-fx3"},
    )
    assert response.status_code == 409
    assert response.json().get("error", {}).get("code") in {
        "WEBHOOK_DELIVERY_IN_PROGRESS",
        "INVALID_STATE_TRANSITION",
    }


@pytest.mark.anyio
async def test_cannot_replay_twice_within_60_seconds(app_client, db_session):
    """Replay should be rate-limited to one replay per event per sixty-second window."""
    event = await _create_event(
        db_session,
        status="failed",
        attempt_count=1,
        replay_count=1,
        last_replayed_at=datetime.now(timezone.utc) - timedelta(seconds=30),
    )

    response = await app_client.post(
        f"/v1/webhooks/events/{event.id}/replay",
        headers={"X-API-Key": "grader-fx3"},
    )
    assert response.status_code == 429
    assert "Retry-After" in response.headers
    retry_after = float(response.headers["Retry-After"])
    assert retry_after <= 30
