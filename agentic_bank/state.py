from __future__ import annotations

from datetime import datetime
from typing import Any

from .storage import Storage, utc_now_iso


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def ensure_state(storage: Storage, user_id: str) -> dict:
    state = storage.get_state(user_id)
    if state is None:
        state = storage.build_seed_state(user_id)
        storage.save_state(user_id, state)
    return state


def save_state(storage: Storage, user_id: str, state: dict) -> None:
    storage.save_state(user_id, state)


def get_balance(state: dict) -> dict:
    profile = state.get("profile") or {}
    profile["last_updated"] = utc_now_iso()
    state["profile"] = profile
    return profile


def list_transactions(
    state: dict,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    category: str | None = None,
) -> list[dict]:
    transactions = list(state.get("transactions") or [])
    start_dt = _parse_iso(start_date)
    end_dt = _parse_iso(end_date)

    filtered: list[dict] = []
    for tx in transactions:
        if category and str(tx.get("category", "")).lower() != category.lower():
            continue
        tx_date = _parse_iso(str(tx.get("date") or ""))
        if start_dt and tx_date and tx_date < start_dt:
            continue
        if end_dt and tx_date and tx_date > end_dt:
            continue
        filtered.append(tx)
    return filtered


def create_transaction(state: dict, payload: dict) -> dict:
    next_ids = state.get("next_ids") or {}
    transaction_id = int(next_ids.get("transaction", 1))
    next_ids["transaction"] = transaction_id + 1
    state["next_ids"] = next_ids

    amount = float(payload.get("amount", 0.0))
    transaction = {
        "id": transaction_id,
        "user_id": payload.get("user_id"),
        "amount": amount,
        "merchant": payload.get("merchant"),
        "category": payload.get("category", "payment"),
        "description": payload.get("description"),
        "date": utc_now_iso(),
        "status": "queued",
        "payment_rail": payload.get("payment_rail"),
        "metadata": payload.get("metadata") or {},
        "lifecycle": [
            {
                "status": "queued",
                "timestamp": utc_now_iso(),
                "reason": "received",
                "metadata": payload.get("metadata") or {},
            }
        ],
    }

    transactions = list(state.get("transactions") or [])
    transactions.append(transaction)
    state["transactions"] = transactions

    profile = state.get("profile") or {}
    profile["current_balance"] = float(profile.get("current_balance") or 0.0) + amount
    profile["available_balance"] = float(profile.get("available_balance") or 0.0) + amount
    profile["last_updated"] = utc_now_iso()
    state["profile"] = profile

    return transaction


def update_transaction_status(
    state: dict,
    transaction_id: int,
    status: str,
    reason: str | None = None,
    settlement_status: str | None = None,
    settlement_due_at: str | None = None,
) -> dict | None:
    transactions = list(state.get("transactions") or [])
    for tx in transactions:
        if int(tx.get("id") or 0) == transaction_id:
            tx["status"] = status
            lifecycle = list(tx.get("lifecycle") or [])
            lifecycle.append(
                {
                    "status": status,
                    "timestamp": utc_now_iso(),
                    "reason": reason,
                    "metadata": tx.get("metadata") or {},
                    "settlement_status": settlement_status,
                    "settlement_due_at": settlement_due_at,
                }
            )
            tx["lifecycle"] = lifecycle
            return tx
    return None


def get_transaction_lifecycle(state: dict, transaction_id: int) -> dict:
    transactions = list(state.get("transactions") or [])
    for tx in transactions:
        if int(tx.get("id") or 0) == transaction_id:
            return {
                "transaction_id": transaction_id,
                "status": tx.get("status"),
                "lifecycle": tx.get("lifecycle") or [],
            }
    return {
        "transaction_id": transaction_id,
        "status": "unknown",
        "lifecycle": [],
    }


def list_accounts(state: dict) -> list[dict]:
    return list(state.get("accounts") or [])


def create_account(state: dict, payload: dict) -> dict:
    next_ids = state.get("next_ids") or {}
    account_index = int(next_ids.get("account", 1))
    next_ids["account"] = account_index + 1
    state["next_ids"] = next_ids

    account_id = payload.get("account_id") or f"acc_{payload.get('user_id')}_{account_index}"
    initial_deposit = float(
        payload.get("initial_deposit")
        if payload.get("initial_deposit") is not None
        else payload.get("balance") or 0.0
    )
    account = {
        "account_id": account_id,
        "user_id": payload.get("user_id"),
        "provider_id": payload.get("provider_id") or "agentic_proxy",
        "name": payload.get("name") or payload.get("nickname") or "New Account",
        "account_type": payload.get("account_type") or payload.get("type") or "savings",
        "mask": payload.get("mask") or "0001",
        "currency": payload.get("currency") or "INR",
        "institution": payload.get("institution") or "Agentic Proxy Bank",
        "current_balance": initial_deposit,
        "available_balance": initial_deposit,
        "status": "active",
        "last_statement_date": payload.get("last_statement_date"),
        "created_at": utc_now_iso(),
    }
    accounts = list(state.get("accounts") or [])
    accounts.append(account)
    state["accounts"] = accounts

    profile = state.get("profile") or {}
    profile["current_balance"] = float(profile.get("current_balance") or 0.0) + initial_deposit
    profile["available_balance"] = float(profile.get("available_balance") or 0.0) + initial_deposit
    profile["last_updated"] = utc_now_iso()
    state["profile"] = profile
    return account


def delete_account(state: dict, account_id: str) -> dict:
    accounts = list(state.get("accounts") or [])
    remaining = [acct for acct in accounts if str(acct.get("account_id")) != account_id]
    state["accounts"] = remaining
    return {"status": "deleted", "account_id": account_id}


def list_beneficiaries(state: dict) -> list[dict]:
    return list(state.get("beneficiaries") or [])


def create_beneficiary(state: dict, payload: dict) -> dict:
    next_ids = state.get("next_ids") or {}
    beneficiary_index = int(next_ids.get("beneficiary", 1))
    next_ids["beneficiary"] = beneficiary_index + 1
    state["next_ids"] = next_ids

    beneficiary_id = payload.get("beneficiary_id") or f"benef_{beneficiary_index}"
    beneficiary = {
        "id": beneficiary_id,
        "user_id": payload.get("user_id"),
        "name": payload.get("name") or payload.get("label") or "Beneficiary",
        "payment_rail": payload.get("payment_rail") or "UPI",
        "account_number": payload.get("account_number"),
        "ifsc": payload.get("ifsc"),
        "upi_handle": payload.get("upi_handle"),
        "nickname": payload.get("nickname"),
        "reference": payload.get("reference")
        or payload.get("upi_handle")
        or payload.get("upi")
        or "upi:unknown",
        "verified": bool(payload.get("verified", False)),
        "created_at": utc_now_iso(),
    }
    beneficiaries = list(state.get("beneficiaries") or [])
    beneficiaries.append(beneficiary)
    state["beneficiaries"] = beneficiaries
    return beneficiary


def verify_beneficiary(state: dict, beneficiary_id: str) -> dict:
    beneficiaries = list(state.get("beneficiaries") or [])
    for beneficiary in beneficiaries:
        if str(beneficiary.get("id")) == beneficiary_id:
            beneficiary["verified"] = True
            return beneficiary
    return {"id": beneficiary_id, "verified": True}


def list_schedules(state: dict) -> list[dict]:
    return list(state.get("schedules") or [])


def create_schedule(state: dict, payload: dict) -> dict:
    next_ids = state.get("next_ids") or {}
    schedule_index = int(next_ids.get("schedule", 1))
    next_ids["schedule"] = schedule_index + 1
    state["next_ids"] = next_ids

    schedule_id = payload.get("schedule_id") or f"sch_{schedule_index}"
    schedule = {
        "id": schedule_id,
        "user_id": payload.get("user_id"),
        "status": "active",
        "payload": payload,
        "created_at": utc_now_iso(),
        "updated_at": utc_now_iso(),
    }
    schedules = list(state.get("schedules") or [])
    schedules.append(schedule)
    state["schedules"] = schedules
    return schedule


def run_schedule(state: dict, schedule_id: str) -> dict:
    schedules = list(state.get("schedules") or [])
    for schedule in schedules:
        if str(schedule.get("id")) == schedule_id:
            schedule["updated_at"] = utc_now_iso()
            return {"status": "executed", "schedule": schedule}
    return {"status": "not_found", "schedule_id": schedule_id}


def cancel_schedule(state: dict, schedule_id: str) -> dict:
    schedules = list(state.get("schedules") or [])
    remaining = []
    removed = None
    for schedule in schedules:
        if str(schedule.get("id")) == schedule_id:
            removed = schedule
            continue
        remaining.append(schedule)
    state["schedules"] = remaining
    if removed:
        return {"status": "cancelled", "schedule": removed}
    return {"status": "not_found", "schedule_id": schedule_id}


def get_bank_plans(state: dict) -> dict:
    return state.get("bank_plans") or {"plans": []}


def get_bank_policies(state: dict) -> dict:
    return state.get("bank_policies") or {}


def get_action_policy(state: dict, action_type: str) -> dict:
    policies = state.get("bank_policies") or {}
    matrix = policies.get("policy_matrix") or {}
    policy = matrix.get(action_type)
    if policy:
        return {
            **policy,
            "country": policies.get("country", "IN"),
            "policy_version": policies.get("policy_version"),
            "default_payment_rail": policies.get("default_payment_rail"),
            "regulatory_context": policies.get("regulatory_context") or [],
        }
    return {
        "action_type": action_type,
        "requires_approval": True,
        "max_amount": 10000.0,
        "allow_trusted_recurring_bypass": True,
        "country": policies.get("country", "IN"),
        "policy_version": policies.get("policy_version"),
        "default_payment_rail": policies.get("default_payment_rail"),
        "regulatory_context": policies.get("regulatory_context") or [],
    }


def get_products(state: dict) -> list[dict]:
    return list(state.get("products") or [])


def get_providers(state: dict) -> list[dict]:
    return list(state.get("providers") or [])


def get_settlement_windows(state: dict) -> dict:
    return {
        "windows": [
            {"rail": "UPI", "status": "open"},
            {"rail": "NEFT", "status": "open"},
        ]
    }


def update_profile(state: dict, user_id: str, payload: dict) -> dict:
    profile = state.get("profile") or {}
    profile["user_id"] = user_id
    if payload.get("current_balance") is not None:
        profile["current_balance"] = float(payload.get("current_balance"))
    if payload.get("available_balance") is not None:
        profile["available_balance"] = float(payload.get("available_balance"))
    profile["last_updated"] = utc_now_iso()
    state["profile"] = profile
    return profile


def set_simulation(state: dict, enabled: bool) -> dict:
    simulation = state.get("simulation") or {}
    simulation["enabled"] = bool(enabled)
    simulation["last_updated"] = utc_now_iso()
    state["simulation"] = simulation
    return simulation


def get_simulation(state: dict) -> dict:
    simulation = state.get("simulation") or {"enabled": True}
    simulation.setdefault("last_updated", utc_now_iso())
    return simulation


def trigger_scenario(state: dict, scenario_type: str) -> dict:
    simulation = state.get("simulation") or {}
    simulation["scenario"] = scenario_type
    simulation["last_updated"] = utc_now_iso()
    state["simulation"] = simulation
    return {"status": "queued", "scenario_type": scenario_type}
