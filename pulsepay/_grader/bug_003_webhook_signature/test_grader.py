from __future__ import annotations

import hashlib
import hmac
import json
from importlib import import_module

import httpx
import pytest
from sqlalchemy import select


def _resolve(module_name: str, fallback: str):
    try:
        return import_module(module_name)
    except ModuleNotFoundError:
        return import_module(fallback)


webhook_models_mod = _resolve("pulsepay.webhooks.models", "webhooks.models")
webhook_dispatcher_mod = _resolve("pulsepay.webhooks.dispatcher", "webhooks.dispatcher")

WebhookEndpoint = webhook_models_mod.WebhookEndpoint
WebhookEvent = webhook_models_mod.WebhookEvent
WebhookDispatcher = webhook_dispatcher_mod.WebhookDispatcher

pytestmark = [pytest.mark.grader, pytest.mark.task("bug_003")]


async def _dispatch_and_capture(db_session, monkeypatch):
    endpoint = WebhookEndpoint(
        client_id="cust-bug003",
        url="https://merchant.example/webhooks",
        signing_secret="secret-bug003",
        is_active=True,
    )
    db_session.add(endpoint)
    await db_session.commit()
    await db_session.refresh(endpoint)

    dispatcher = WebhookDispatcher(db_session)
    events = await dispatcher.dispatch(
        event_type="payment.succeeded",
        payload={"payment_id": "p_001", "amount": "12.34", "currency": "USD"},
        customer_id="cust-bug003",
    )
    event = events[0]

    captured: dict[str, object] = {}

    async def _fake_post(self, url, content=None, headers=None, **kwargs):
        captured["url"] = url
        captured["content"] = content
        captured["headers"] = headers or {}

        class _Response:
            is_success = True

        return _Response()

    monkeypatch.setattr(httpx.AsyncClient, "post", _fake_post)
    await dispatcher.deliver(event.id)

    refreshed = (await db_session.execute(select(WebhookEvent).where(WebhookEvent.id == event.id))).scalar_one()
    return endpoint, refreshed, captured


@pytest.mark.anyio
async def test_signature_matches_hmac_of_json_body(db_session, monkeypatch):
    """Webhook dispatch must sign the canonical JSON payload body with HMAC-SHA256."""
    endpoint, event, captured = await _dispatch_and_capture(db_session, monkeypatch)
    signature = (captured.get("headers") or {}).get("X-PulsePay-Signature")
    assert signature

    expected_body = json.dumps(event.payload, separators=(",", ":"), sort_keys=True)
    expected_signature = hmac.new(
        endpoint.signing_secret.encode("utf-8"),
        expected_body.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    assert signature == expected_signature


@pytest.mark.anyio
async def test_signature_does_not_match_str_repr(db_session, monkeypatch):
    """Webhook dispatch signatures must not match HMAC computed from Python dict string representation."""
    endpoint, event, captured = await _dispatch_and_capture(db_session, monkeypatch)
    signature = (captured.get("headers") or {}).get("X-PulsePay-Signature")
    assert signature

    broken_signature = hmac.new(
        endpoint.signing_secret.encode("utf-8"),
        str(event.payload).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    assert signature != broken_signature
