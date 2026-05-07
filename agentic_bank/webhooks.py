from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import time
import uuid
from typing import Any

import httpx

from .config import Settings
from .storage import Storage, utc_now_iso


def _sign_payload(secret: str, payload: dict[str, Any]) -> tuple[bytes, str, str]:
    timestamp = str(int(time.time()))
    body = json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
    signed_payload = f"{timestamp}.{body.decode('utf-8')}"
    signature = hmac.new(
        secret.encode("utf-8"),
        signed_payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return body, timestamp, signature


async def dispatch_webhook(
    *,
    storage: Storage,
    settings: Settings,
    webhook_url: str | None,
    payload: dict[str, Any],
) -> dict[str, Any]:
    if not webhook_url:
        return {"status": "skipped", "reason": "webhook_url_missing"}
    if not settings.webhook_secret:
        return {"status": "skipped", "reason": "webhook_secret_missing"}

    attempt_log: list[dict[str, Any]] = []
    last_error: str | None = None

    for attempt in range(1, max(1, settings.webhook_max_attempts) + 1):
        try:
            body, timestamp, signature = _sign_payload(
                settings.webhook_secret, payload
            )
            headers = {
                "X-CareBank-Timestamp": timestamp,
                "X-CareBank-Signature": signature,
                "Content-Type": "application/json",
            }
            async with httpx.AsyncClient(
                timeout=settings.webhook_timeout_seconds
            ) as client:
                response = await client.post(webhook_url, content=body, headers=headers)
            if response.status_code < 300:
                attempt_log.append(
                    {
                        "attempt": attempt,
                        "timestamp": utc_now_iso(),
                        "status": response.status_code,
                    }
                )
                return {
                    "status": "delivered",
                    "attempts": attempt_log,
                }
            last_error = f"status={response.status_code}"
        except Exception as exc:  # noqa: BLE001
            last_error = str(exc)
        attempt_log.append(
            {
                "attempt": attempt,
                "timestamp": utc_now_iso(),
                "error": last_error,
            }
        )
        if attempt < settings.webhook_max_attempts and settings.webhook_retry_backoff_seconds > 0:
            await asyncio.sleep(settings.webhook_retry_backoff_seconds)

    dead_letter_id = f"dl_{uuid.uuid4().hex[:12]}"
    record = {
        "id": dead_letter_id,
        "webhook_url": webhook_url,
        "payload": payload,
        "attempts": attempt_log,
        "status": "dead_lettered",
        "attempt_count": len(attempt_log),
        "last_error": last_error,
        "created_at": utc_now_iso(),
        "updated_at": utc_now_iso(),
    }
    storage.upsert_dead_letter(record)
    return {
        "status": "dead_lettered",
        "dead_letter_id": dead_letter_id,
        "attempts": attempt_log,
    }


async def replay_dead_letter(
    *,
    storage: Storage,
    settings: Settings,
    record: dict[str, Any],
    webhook_url: str | None,
) -> dict[str, Any]:
    payload = record.get("payload") or {}
    target_url = webhook_url or record.get("webhook_url")
    response = await dispatch_webhook(
        storage=storage,
        settings=settings,
        webhook_url=target_url,
        payload=payload,
    )
    record["attempts"] = response.get("attempts") or record.get("attempts") or []
    record["attempt_count"] = len(record["attempts"])
    record["updated_at"] = utc_now_iso()
    if response.get("status") == "delivered":
        record["status"] = "delivered"
        record["last_error"] = None
    else:
        record["status"] = "dead_lettered"
        record["last_error"] = response.get("last_error")
    storage.upsert_dead_letter(record)
    return response
