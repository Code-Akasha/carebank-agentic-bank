from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status

from .auth import TokenPayload, verify_request_token
from .config import get_settings
from .gemini_client import GeminiClient
from .schemas import get_schema_hint, validate_response
from .state import (
    cancel_schedule,
    create_account,
    create_beneficiary,
    create_schedule,
    create_transaction,
    delete_account,
    ensure_state,
    get_action_policy,
    get_balance,
    get_bank_plans,
    get_bank_policies,
    get_products,
    get_providers,
    get_settlement_windows,
    get_simulation,
    get_transaction_lifecycle,
    list_accounts,
    list_beneficiaries,
    list_schedules,
    list_transactions,
    run_schedule,
    save_state,
    set_simulation,
    trigger_scenario,
    update_profile,
    update_transaction_status,
    verify_beneficiary,
)
from .storage import Storage, utc_now_iso
from .webhooks import dispatch_webhook, replay_dead_letter

logger = logging.getLogger(__name__)

router = APIRouter()


@dataclass(frozen=True)
class RequestContext:
    user_id: str
    role: str


def _make_fingerprint(data: dict[str, Any]) -> str:
    payload = json.dumps(data, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _normalize_query(params: dict[str, Any]) -> dict[str, Any]:
    normalized = {}
    for key, value in params.items():
        if isinstance(value, list):
            normalized[key] = ",".join(sorted([str(item) for item in value]))
        else:
            normalized[key] = str(value)
    return normalized


def _should_cache(method: str, body: dict | None) -> bool:
    if method.upper() == "GET":
        return True
    if not body:
        return False
    return bool(body.get("idempotency_key"))


class ProxyService:
    def __init__(self) -> None:
        settings = get_settings()
        self._settings = settings
        self._storage = Storage(settings.database_url or settings.db_path)
        self._gemini = GeminiClient()

    @property
    def storage(self) -> Storage:
        return self._storage

    @property
    def settings(self):
        return self._settings

    def build_response(
        self,
        *,
        schema_key: str,
        request_context: dict[str, Any],
        deterministic: Any,
    ) -> Any:
        schema_hint = get_schema_hint(schema_key)
        if self._gemini.enabled:
            context = {
                **request_context,
                "deterministic_response": deterministic,
            }
            generated = self._gemini.generate_json(
                schema_hint=schema_hint,
                context=context,
            )
            if generated is not None and validate_response(schema_key, generated):
                return generated
        if self._settings.strict_mode and not self._settings.fallback_enabled:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Gemini response unavailable",
            )
        return deterministic


_service: ProxyService | None = None


def get_service() -> ProxyService:
    global _service
    if _service is None:
        _service = ProxyService()
    return _service


def get_context(request: Request) -> RequestContext:
    payload: TokenPayload = verify_request_token(request)
    return RequestContext(user_id=payload.user_id, role=payload.role)


def require_admin(ctx: RequestContext = Depends(get_context)) -> RequestContext:
    if ctx.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin role required",
        )
    return ctx


@router.get("/")
async def root() -> dict[str, str]:
    return {"status": "ok", "service": "agentic-bank-proxy"}


@router.get("/balances")
async def get_balances(
    request: Request,
    ctx: RequestContext = Depends(get_context),
    service: ProxyService = Depends(get_service),
) -> Any:
    state = ensure_state(service.storage, ctx.user_id)
    deterministic = get_balance(state)
    save_state(service.storage, ctx.user_id, state)

    fingerprint = _make_fingerprint(
        {
            "method": "GET",
            "path": "/balances",
            "user_id": ctx.user_id,
        }
    )
    cached = service.storage.get_cache(fingerprint)
    if cached is not None:
        return cached

    response = service.build_response(
        schema_key="balances",
        request_context={"path": "/balances", "user_id": ctx.user_id},
        deterministic=deterministic,
    )
    service.storage.set_cache(
        fingerprint, ctx.user_id, "GET", "/balances", response
    )
    return response


@router.get("/transactions")
async def get_transactions(
    request: Request,
    start_date: str | None = None,
    end_date: str | None = None,
    category: str | None = None,
    settlement_status: str | None = None,
    ctx: RequestContext = Depends(get_context),
    service: ProxyService = Depends(get_service),
) -> Any:
    state = ensure_state(service.storage, ctx.user_id)
    deterministic = list_transactions(
        state, start_date=start_date, end_date=end_date, category=category
    )
    save_state(service.storage, ctx.user_id, state)

    fingerprint = _make_fingerprint(
        {
            "method": "GET",
            "path": "/transactions",
            "user_id": ctx.user_id,
            "query": _normalize_query(
                {
                    "start_date": start_date or "",
                    "end_date": end_date or "",
                    "category": category or "",
                    "settlement_status": settlement_status or "",
                }
            ),
        }
    )
    cached = service.storage.get_cache(fingerprint)
    if cached is not None:
        return cached

    response = service.build_response(
        schema_key="transactions",
        request_context={
            "path": "/transactions",
            "user_id": ctx.user_id,
            "query": {
                "start_date": start_date,
                "end_date": end_date,
                "category": category,
                "settlement_status": settlement_status,
            },
        },
        deterministic=deterministic,
    )
    service.storage.set_cache(
        fingerprint, ctx.user_id, "GET", "/transactions", response
    )
    return response


@router.get("/transactions/{transaction_id}/lifecycle")
async def transaction_lifecycle(
    request: Request,
    transaction_id: int,
    ctx: RequestContext = Depends(get_context),
    service: ProxyService = Depends(get_service),
) -> Any:
    state = ensure_state(service.storage, ctx.user_id)
    deterministic = get_transaction_lifecycle(state, transaction_id)
    save_state(service.storage, ctx.user_id, state)

    fingerprint = _make_fingerprint(
        {
            "method": "GET",
            "path": f"/transactions/{transaction_id}/lifecycle",
            "user_id": ctx.user_id,
        }
    )
    cached = service.storage.get_cache(fingerprint)
    if cached is not None:
        return cached

    response = service.build_response(
        schema_key="transaction_lifecycle",
        request_context={
            "path": "/transactions/lifecycle",
            "user_id": ctx.user_id,
            "transaction_id": transaction_id,
        },
        deterministic=deterministic,
    )
    service.storage.set_cache(
        fingerprint,
        ctx.user_id,
        "GET",
        f"/transactions/{transaction_id}/lifecycle",
        response,
    )
    return response


@router.post("/transactions/trigger")
async def trigger_transaction(
    request: Request,
    background_tasks: BackgroundTasks,
    ctx: RequestContext = Depends(get_context),
    service: ProxyService = Depends(get_service),
) -> Any:
    body = await request.json()
    body["user_id"] = body.get("user_id") or ctx.user_id

    state = ensure_state(service.storage, ctx.user_id)
    transaction = create_transaction(state, body)
    save_state(service.storage, ctx.user_id, state)

    metadata = transaction.get("metadata") or {}
    webhook_url = body.get("webhook_url")

    settlement_status = "cleared"
    settlement_due_at = None
    if str(body.get("payment_rail", "")).upper() in {"NEFT", "RTGS"}:
        settlement_status = "pending"
        settlement_due_at = utc_now_iso()

    lifecycle_payload = {
        "event_type": "transaction.lifecycle",
        "transaction_id": transaction.get("id"),
        "user_id": ctx.user_id,
        "status": "success",
        "timestamp": utc_now_iso(),
        "reason": None,
        "metadata": metadata,
        "settlement_status": settlement_status,
        "settlement_due_at": settlement_due_at,
    }

    background_tasks.add_task(
        dispatch_webhook,
        storage=service.storage,
        settings=service.settings,
        webhook_url=webhook_url,
        payload=lifecycle_payload,
    )

    update_transaction_status(
        state,
        int(transaction.get("id")),
        "success",
        reason=None,
        settlement_status=settlement_status,
        settlement_due_at=settlement_due_at,
    )
    save_state(service.storage, ctx.user_id, state)

    deterministic = {
        "status": "accepted",
        "transaction": transaction,
        "webhook": {
            "status": "queued" if webhook_url else "skipped",
            "destination": webhook_url,
        },
    }

    schema_key = "transaction_trigger"
    response = service.build_response(
        schema_key=schema_key,
        request_context={
            "path": "/transactions/trigger",
            "user_id": ctx.user_id,
            "payload": body,
        },
        deterministic=deterministic,
    )

    fingerprint = _make_fingerprint(
        {
            "method": "POST",
            "path": "/transactions/trigger",
            "user_id": ctx.user_id,
            "payload": body,
        }
    )
    if _should_cache("POST", body):
        service.storage.set_cache(
            fingerprint, ctx.user_id, "POST", "/transactions/trigger", response
        )
    return response


@router.get("/products")
async def list_products(
    request: Request,
    ctx: RequestContext = Depends(get_context),
    service: ProxyService = Depends(get_service),
) -> Any:
    state = ensure_state(service.storage, ctx.user_id)
    deterministic = get_products(state)
    save_state(service.storage, ctx.user_id, state)

    fingerprint = _make_fingerprint(
        {"method": "GET", "path": "/products", "user_id": ctx.user_id}
    )
    cached = service.storage.get_cache(fingerprint)
    if cached is not None:
        return cached

    response = service.build_response(
        schema_key="products",
        request_context={"path": "/products", "user_id": ctx.user_id},
        deterministic=deterministic,
    )
    service.storage.set_cache(
        fingerprint, ctx.user_id, "GET", "/products", response
    )
    return response


@router.get("/banking/plans")
async def list_bank_plans(
    request: Request,
    ctx: RequestContext = Depends(get_context),
    service: ProxyService = Depends(get_service),
) -> Any:
    state = ensure_state(service.storage, ctx.user_id)
    deterministic = get_bank_plans(state)
    save_state(service.storage, ctx.user_id, state)

    fingerprint = _make_fingerprint(
        {"method": "GET", "path": "/banking/plans", "user_id": ctx.user_id}
    )
    cached = service.storage.get_cache(fingerprint)
    if cached is not None:
        return cached

    response = service.build_response(
        schema_key="bank_plans",
        request_context={"path": "/banking/plans", "user_id": ctx.user_id},
        deterministic=deterministic,
    )
    service.storage.set_cache(
        fingerprint, ctx.user_id, "GET", "/banking/plans", response
    )
    return response


@router.get("/banking/policies")
async def list_bank_policies(
    request: Request,
    ctx: RequestContext = Depends(get_context),
    service: ProxyService = Depends(get_service),
) -> Any:
    state = ensure_state(service.storage, ctx.user_id)
    deterministic = get_bank_policies(state)
    save_state(service.storage, ctx.user_id, state)

    fingerprint = _make_fingerprint(
        {
            "method": "GET",
            "path": "/banking/policies",
            "user_id": ctx.user_id,
        }
    )
    cached = service.storage.get_cache(fingerprint)
    if cached is not None:
        return cached

    response = service.build_response(
        schema_key="bank_policies",
        request_context={"path": "/banking/policies", "user_id": ctx.user_id},
        deterministic=deterministic,
    )
    service.storage.set_cache(
        fingerprint, ctx.user_id, "GET", "/banking/policies", response
    )
    return response


@router.get("/banking/policies/actions/{action_type}")
async def get_policy_for_action(
    request: Request,
    action_type: str,
    ctx: RequestContext = Depends(get_context),
    service: ProxyService = Depends(get_service),
) -> Any:
    state = ensure_state(service.storage, ctx.user_id)
    deterministic = get_action_policy(state, action_type)
    save_state(service.storage, ctx.user_id, state)

    fingerprint = _make_fingerprint(
        {
            "method": "GET",
            "path": f"/banking/policies/actions/{action_type}",
            "user_id": ctx.user_id,
        }
    )
    cached = service.storage.get_cache(fingerprint)
    if cached is not None:
        return cached

    response = service.build_response(
        schema_key="action_policy",
        request_context={
            "path": "/banking/policies/actions",
            "user_id": ctx.user_id,
            "action_type": action_type,
        },
        deterministic=deterministic,
    )
    service.storage.set_cache(
        fingerprint,
        ctx.user_id,
        "GET",
        f"/banking/policies/actions/{action_type}",
        response,
    )
    return response


@router.get("/accounts")
async def list_accounts_endpoint(
    request: Request,
    ctx: RequestContext = Depends(get_context),
    service: ProxyService = Depends(get_service),
) -> Any:
    state = ensure_state(service.storage, ctx.user_id)
    deterministic = list_accounts(state)
    save_state(service.storage, ctx.user_id, state)

    fingerprint = _make_fingerprint(
        {"method": "GET", "path": "/accounts", "user_id": ctx.user_id}
    )
    cached = service.storage.get_cache(fingerprint)
    if cached is not None:
        return cached

    response = service.build_response(
        schema_key="accounts",
        request_context={"path": "/accounts", "user_id": ctx.user_id},
        deterministic=deterministic,
    )
    service.storage.set_cache(
        fingerprint, ctx.user_id, "GET", "/accounts", response
    )
    return response


@router.post("/accounts")
async def create_account_endpoint(
    request: Request,
    ctx: RequestContext = Depends(get_context),
    service: ProxyService = Depends(get_service),
) -> Any:
    body = await request.json()
    body["user_id"] = body.get("user_id") or ctx.user_id

    state = ensure_state(service.storage, ctx.user_id)
    account = create_account(state, body)
    save_state(service.storage, ctx.user_id, state)

    response = service.build_response(
        schema_key="account_create",
        request_context={"path": "/accounts", "user_id": ctx.user_id, "payload": body},
        deterministic={"account": account},
    )

    fingerprint = _make_fingerprint(
        {"method": "POST", "path": "/accounts", "user_id": ctx.user_id, "payload": body}
    )
    if _should_cache("POST", body):
        service.storage.set_cache(fingerprint, ctx.user_id, "POST", "/accounts", response)
    service.storage.delete_cache_entries(user_id=ctx.user_id, method="GET", path="/accounts")
    service.storage.delete_cache_entries(user_id=ctx.user_id, method="GET", path="/balances")
    return response


@router.delete("/accounts/{account_id}")
async def delete_account_endpoint(
    request: Request,
    account_id: str,
    ctx: RequestContext = Depends(get_context),
    service: ProxyService = Depends(get_service),
) -> Any:
    state = ensure_state(service.storage, ctx.user_id)
    deterministic = delete_account(state, account_id)
    save_state(service.storage, ctx.user_id, state)

    response = service.build_response(
        schema_key="account_delete",
        request_context={
            "path": "/accounts/delete",
            "user_id": ctx.user_id,
            "account_id": account_id,
        },
        deterministic=deterministic,
    )
    service.storage.delete_cache_entries(user_id=ctx.user_id, method="GET", path="/accounts")
    service.storage.delete_cache_entries(user_id=ctx.user_id, method="GET", path="/balances")
    return response


@router.get("/beneficiaries")
async def list_beneficiaries_endpoint(
    request: Request,
    ctx: RequestContext = Depends(get_context),
    service: ProxyService = Depends(get_service),
) -> Any:
    state = ensure_state(service.storage, ctx.user_id)
    deterministic = list_beneficiaries(state)
    save_state(service.storage, ctx.user_id, state)

    fingerprint = _make_fingerprint(
        {"method": "GET", "path": "/beneficiaries", "user_id": ctx.user_id}
    )
    cached = service.storage.get_cache(fingerprint)
    if cached is not None:
        return cached

    response = service.build_response(
        schema_key="beneficiaries",
        request_context={"path": "/beneficiaries", "user_id": ctx.user_id},
        deterministic=deterministic,
    )
    service.storage.set_cache(
        fingerprint, ctx.user_id, "GET", "/beneficiaries", response
    )
    return response


@router.post("/beneficiaries")
async def create_beneficiary_endpoint(
    request: Request,
    ctx: RequestContext = Depends(get_context),
    service: ProxyService = Depends(get_service),
) -> Any:
    body = await request.json()
    body["user_id"] = body.get("user_id") or ctx.user_id

    state = ensure_state(service.storage, ctx.user_id)
    deterministic = create_beneficiary(state, body)
    save_state(service.storage, ctx.user_id, state)

    response = service.build_response(
        schema_key="beneficiary",
        request_context={"path": "/beneficiaries", "user_id": ctx.user_id, "payload": body},
        deterministic=deterministic,
    )

    fingerprint = _make_fingerprint(
        {"method": "POST", "path": "/beneficiaries", "user_id": ctx.user_id, "payload": body}
    )
    if _should_cache("POST", body):
        service.storage.set_cache(
            fingerprint, ctx.user_id, "POST", "/beneficiaries", response
        )
    return response


@router.put("/beneficiaries/{beneficiary_id}/verify")
async def verify_beneficiary_endpoint(
    request: Request,
    beneficiary_id: str,
    ctx: RequestContext = Depends(get_context),
    service: ProxyService = Depends(get_service),
) -> Any:
    state = ensure_state(service.storage, ctx.user_id)
    deterministic = verify_beneficiary(state, beneficiary_id)
    save_state(service.storage, ctx.user_id, state)

    response = service.build_response(
        schema_key="beneficiary",
        request_context={
            "path": "/beneficiaries/verify",
            "user_id": ctx.user_id,
            "beneficiary_id": beneficiary_id,
        },
        deterministic=deterministic,
    )
    return response


@router.get("/settlement-windows")
async def settlement_windows_endpoint(
    request: Request,
    for_date: str | None = None,
    ctx: RequestContext = Depends(get_context),
    service: ProxyService = Depends(get_service),
) -> Any:
    state = ensure_state(service.storage, ctx.user_id)
    deterministic = get_settlement_windows(state)
    save_state(service.storage, ctx.user_id, state)

    fingerprint = _make_fingerprint(
        {"method": "GET", "path": "/settlement-windows", "user_id": ctx.user_id}
    )
    cached = service.storage.get_cache(fingerprint)
    if cached is not None:
        return cached

    response = service.build_response(
        schema_key="settlement_windows",
        request_context={"path": "/settlement-windows", "user_id": ctx.user_id},
        deterministic=deterministic,
    )
    service.storage.set_cache(
        fingerprint, ctx.user_id, "GET", "/settlement-windows", response
    )
    return response


@router.get("/schedules")
async def list_schedules_endpoint(
    request: Request,
    include_inactive: bool = False,
    ctx: RequestContext = Depends(get_context),
    service: ProxyService = Depends(get_service),
) -> Any:
    state = ensure_state(service.storage, ctx.user_id)
    deterministic = list_schedules(state)
    save_state(service.storage, ctx.user_id, state)

    fingerprint = _make_fingerprint(
        {
            "method": "GET",
            "path": "/schedules",
            "user_id": ctx.user_id,
            "query": _normalize_query({"include_inactive": include_inactive}),
        }
    )
    cached = service.storage.get_cache(fingerprint)
    if cached is not None:
        return cached

    response = service.build_response(
        schema_key="schedules",
        request_context={
            "path": "/schedules",
            "user_id": ctx.user_id,
            "include_inactive": include_inactive,
        },
        deterministic=deterministic,
    )
    service.storage.set_cache(
        fingerprint, ctx.user_id, "GET", "/schedules", response
    )
    return response


@router.post("/schedules")
async def create_schedule_endpoint(
    request: Request,
    ctx: RequestContext = Depends(get_context),
    service: ProxyService = Depends(get_service),
) -> Any:
    body = await request.json()
    body["user_id"] = body.get("user_id") or ctx.user_id

    state = ensure_state(service.storage, ctx.user_id)
    deterministic = create_schedule(state, body)
    save_state(service.storage, ctx.user_id, state)

    response = service.build_response(
        schema_key="schedule",
        request_context={"path": "/schedules", "user_id": ctx.user_id, "payload": body},
        deterministic=deterministic,
    )

    fingerprint = _make_fingerprint(
        {"method": "POST", "path": "/schedules", "user_id": ctx.user_id, "payload": body}
    )
    if _should_cache("POST", body):
        service.storage.set_cache(fingerprint, ctx.user_id, "POST", "/schedules", response)
    return response


@router.post("/schedules/{schedule_id}/run")
async def run_schedule_endpoint(
    request: Request,
    schedule_id: str,
    force: bool = False,
    ctx: RequestContext = Depends(get_context),
    service: ProxyService = Depends(get_service),
) -> Any:
    state = ensure_state(service.storage, ctx.user_id)
    deterministic = run_schedule(state, schedule_id)
    save_state(service.storage, ctx.user_id, state)

    response = service.build_response(
        schema_key="schedule_result",
        request_context={
            "path": "/schedules/run",
            "user_id": ctx.user_id,
            "schedule_id": schedule_id,
            "force": force,
        },
        deterministic=deterministic,
    )
    return response


@router.delete("/schedules/{schedule_id}")
async def cancel_schedule_endpoint(
    request: Request,
    schedule_id: str,
    ctx: RequestContext = Depends(get_context),
    service: ProxyService = Depends(get_service),
) -> Any:
    state = ensure_state(service.storage, ctx.user_id)
    deterministic = cancel_schedule(state, schedule_id)
    save_state(service.storage, ctx.user_id, state)

    response = service.build_response(
        schema_key="schedule_result",
        request_context={
            "path": "/schedules/delete",
            "user_id": ctx.user_id,
            "schedule_id": schedule_id,
        },
        deterministic=deterministic,
    )
    return response


@router.get("/providers")
async def list_providers_endpoint(
    request: Request,
    ctx: RequestContext = Depends(get_context),
    service: ProxyService = Depends(get_service),
) -> Any:
    state = ensure_state(service.storage, ctx.user_id)
    deterministic = get_providers(state)
    save_state(service.storage, ctx.user_id, state)

    fingerprint = _make_fingerprint(
        {"method": "GET", "path": "/providers", "user_id": ctx.user_id}
    )
    cached = service.storage.get_cache(fingerprint)
    if cached is not None:
        return cached

    response = service.build_response(
        schema_key="providers",
        request_context={"path": "/providers", "user_id": ctx.user_id},
        deterministic=deterministic,
    )
    service.storage.set_cache(
        fingerprint, ctx.user_id, "GET", "/providers", response
    )
    return response


@router.post("/profiles")
async def create_profile_endpoint(
    request: Request,
    admin: RequestContext = Depends(require_admin),
    service: ProxyService = Depends(get_service),
) -> Any:
    body = await request.json()
    user_id = body.get("user_id")
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id required")

    state = ensure_state(service.storage, user_id)
    deterministic = update_profile(state, user_id, body)
    save_state(service.storage, user_id, state)

    response = service.build_response(
        schema_key="profile",
        request_context={"path": "/profiles", "user_id": user_id, "payload": body},
        deterministic=deterministic,
    )
    return response


@router.get("/admin/users")
async def admin_users_endpoint(
    request: Request,
    admin: RequestContext = Depends(require_admin),
    service: ProxyService = Depends(get_service),
    page: int = 1,
    per_page: int = 200,
) -> Any:
    users = []
    for user_id in service.storage.list_state_users():
        state = ensure_state(service.storage, user_id)
        profile = get_balance(state)
        users.append(
            {
                "user_id": user_id,
                "current_balance": profile.get("current_balance"),
                "available_balance": profile.get("available_balance"),
            }
        )
        save_state(service.storage, user_id, state)

    deterministic = {"users": users, "page": page, "per_page": per_page}
    response = service.build_response(
        schema_key="admin_users",
        request_context={"path": "/admin/users"},
        deterministic=deterministic,
    )
    return response


@router.get("/admin/webhooks/dead-letter")
async def admin_dead_letters_endpoint(
    request: Request,
    status_filter: str | None = None,
    admin: RequestContext = Depends(require_admin),
    service: ProxyService = Depends(get_service),
) -> Any:
    records = service.storage.get_dead_letters(status_filter)
    deterministic = {"records": records}
    response = service.build_response(
        schema_key="dead_letters",
        request_context={"path": "/admin/webhooks/dead-letter"},
        deterministic=deterministic,
    )
    return response


@router.post("/admin/webhooks/dead-letter/{dead_letter_id}/replay")
async def replay_dead_letter_endpoint(
    request: Request,
    dead_letter_id: str,
    admin: RequestContext = Depends(require_admin),
    service: ProxyService = Depends(get_service),
) -> Any:
    try:
        body = await request.json()
    except Exception:
        body = {}
    webhook_url = body.get("webhook_url") if isinstance(body, dict) else None

    record = service.storage.get_dead_letter(dead_letter_id)
    if not record:
        raise HTTPException(status_code=404, detail="dead letter not found")

    response = await replay_dead_letter(
        storage=service.storage,
        settings=service.settings,
        record=record,
        webhook_url=webhook_url,
    )
    return response


@router.post("/admin/simulation/toggle")
async def simulation_toggle_endpoint(
    request: Request,
    admin: RequestContext = Depends(require_admin),
    service: ProxyService = Depends(get_service),
) -> Any:
    body = await request.json()
    enabled = bool(body.get("enabled"))
    state = ensure_state(service.storage, admin.user_id)
    deterministic = set_simulation(state, enabled)
    save_state(service.storage, admin.user_id, state)
    response = service.build_response(
        schema_key="simulation_toggle",
        request_context={"path": "/admin/simulation/toggle", "payload": body},
        deterministic=deterministic,
    )
    return response


@router.get("/admin/simulation/status")
async def simulation_status_endpoint(
    request: Request,
    admin: RequestContext = Depends(require_admin),
    service: ProxyService = Depends(get_service),
) -> Any:
    state = ensure_state(service.storage, admin.user_id)
    deterministic = get_simulation(state)
    save_state(service.storage, admin.user_id, state)
    response = service.build_response(
        schema_key="simulation_status",
        request_context={"path": "/admin/simulation/status"},
        deterministic=deterministic,
    )
    return response


@router.post("/admin/scenario")
async def scenario_trigger_endpoint(
    request: Request,
    admin: RequestContext = Depends(require_admin),
    service: ProxyService = Depends(get_service),
) -> Any:
    body = await request.json()
    user_id = body.get("user_id")
    scenario_type = body.get("scenario_type") or "default"
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id required")

    state = ensure_state(service.storage, user_id)
    deterministic = trigger_scenario(state, scenario_type)
    save_state(service.storage, user_id, state)
    response = service.build_response(
        schema_key="scenario_trigger",
        request_context={
            "path": "/admin/scenario",
            "user_id": user_id,
            "payload": body,
        },
        deterministic=deterministic,
    )
    return response
