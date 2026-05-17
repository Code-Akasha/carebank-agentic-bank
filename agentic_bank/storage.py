from __future__ import annotations

import hashlib
import json
import random
import sqlite3
from datetime import datetime, timezone
from threading import Lock
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _seed_from_user_id(user_id: str) -> int:
    digest = hashlib.sha256(user_id.encode("utf-8")).hexdigest()
    return int(digest[:8], 16)


def _json_dumps(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=True, separators=(",", ":"))


def _json_loads(raw: str | None) -> Any:
    if not raw:
        return None
    return json.loads(raw)


class Storage:
    def __init__(self, db_path: str) -> None:
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = Lock()
        self._init_db()

    def _init_db(self) -> None:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS response_cache (
                    fingerprint TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    method TEXT NOT NULL,
                    path TEXT NOT NULL,
                    response_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS world_state (
                    user_id TEXT PRIMARY KEY,
                    state_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS dead_letters (
                    id TEXT PRIMARY KEY,
                    webhook_url TEXT,
                    payload_json TEXT NOT NULL,
                    attempts_json TEXT,
                    status TEXT NOT NULL,
                    attempt_count INTEGER NOT NULL,
                    last_error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            self._conn.commit()

    def get_cache(self, fingerprint: str) -> dict | None:
        with self._lock:
            cur = self._conn.execute(
                "SELECT response_json FROM response_cache WHERE fingerprint = ?",
                (fingerprint,),
            )
            row = cur.fetchone()
        if not row:
            return None
        return _json_loads(row[0])

    def set_cache(
        self,
        fingerprint: str,
        user_id: str,
        method: str,
        path: str,
        response: Any,
    ) -> None:
        payload = _json_dumps(response)
        with self._lock:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO response_cache
                    (fingerprint, user_id, method, path, response_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (fingerprint, user_id, method, path, payload, utc_now_iso()),
            )
            self._conn.commit()

    def get_state(self, user_id: str) -> dict | None:
        with self._lock:
            cur = self._conn.execute(
                "SELECT state_json FROM world_state WHERE user_id = ?",
                (user_id,),
            )
            row = cur.fetchone()
        if not row:
            return None
        return _json_loads(row[0])

    def save_state(self, user_id: str, state: dict) -> None:
        payload = _json_dumps(state)
        with self._lock:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO world_state
                    (user_id, state_json, updated_at)
                VALUES (?, ?, ?)
                """,
                (user_id, payload, utc_now_iso()),
            )
            self._conn.commit()

    def list_state_users(self) -> list[str]:
        with self._lock:
            cur = self._conn.execute("SELECT user_id FROM world_state")
            rows = cur.fetchall()
        return [str(row[0]) for row in rows]

    def get_dead_letters(self, status_filter: str | None = None) -> list[dict]:
        query = "SELECT * FROM dead_letters"
        params: tuple[Any, ...] = ()
        if status_filter:
            query += " WHERE status = ?"
            params = (status_filter,)
        with self._lock:
            cur = self._conn.execute(query, params)
            rows = cur.fetchall()
        records: list[dict] = []
        for row in rows:
            records.append(
                {
                    "id": row[0],
                    "webhook_url": row[1],
                    "payload": _json_loads(row[2]) or {},
                    "attempts": _json_loads(row[3]) or [],
                    "status": row[4],
                    "attempt_count": int(row[5]),
                    "last_error": row[6],
                    "created_at": row[7],
                    "updated_at": row[8],
                }
            )
        return records

    def get_dead_letter(self, dead_letter_id: str) -> dict | None:
        with self._lock:
            cur = self._conn.execute(
                "SELECT * FROM dead_letters WHERE id = ?",
                (dead_letter_id,),
            )
            row = cur.fetchone()
        if not row:
            return None
        return {
            "id": row[0],
            "webhook_url": row[1],
            "payload": _json_loads(row[2]) or {},
            "attempts": _json_loads(row[3]) or [],
            "status": row[4],
            "attempt_count": int(row[5]),
            "last_error": row[6],
            "created_at": row[7],
            "updated_at": row[8],
        }

    def upsert_dead_letter(self, record: dict) -> None:
        attempts = record.get("attempts") or []
        payload = _json_dumps(record.get("payload") or {})
        attempts_payload = _json_dumps(attempts)
        with self._lock:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO dead_letters
                    (id, webhook_url, payload_json, attempts_json, status,
                     attempt_count, last_error, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.get("id"),
                    record.get("webhook_url"),
                    payload,
                    attempts_payload,
                    record.get("status"),
                    int(record.get("attempt_count") or 0),
                    record.get("last_error"),
                    record.get("created_at") or utc_now_iso(),
                    record.get("updated_at") or utc_now_iso(),
                ),
            )
            self._conn.commit()

    def build_seed_state(self, user_id: str) -> dict:
        rng = random.Random(_seed_from_user_id(user_id))
        current_balance = round(15000 + rng.random() * 45000, 2)
        available_balance = round(current_balance - rng.random() * 2000, 2)

        base_account_id = f"acc_{user_id}_1"
        account = {
            "account_id": base_account_id,
            "user_id": user_id,
            "provider_id": "agentic_proxy",
            "name": "Primary Savings",
            "account_type": "savings",
            "mask": "0001",
            "currency": "INR",
            "institution": "Agentic Proxy Bank",
            "current_balance": current_balance,
            "available_balance": available_balance,
            "status": "active",
            "last_statement_date": None,
            "created_at": utc_now_iso(),
        }

        transactions: list[dict] = []
        for index in range(10):
            amount = round(-(200 + rng.random() * 1200), 2)
            transactions.append(
                {
                    "id": 1000 + index,
                    "user_id": user_id,
                    "amount": amount,
                    "merchant": rng.choice(
                        [
                            "Cafe Orion",
                            "Metro Mart",
                            "Fuel Bay",
                            "Cloud Telecom",
                            "Cinema House",
                        ]
                    ),
                    "category": rng.choice(
                        ["food", "shopping", "fuel", "utilities", "entertainment"]
                    ),
                    "description": "Synthetic transaction",
                    "date": utc_now_iso(),
                    "status": "success",
                    "lifecycle": [
                        {
                            "status": "success",
                            "timestamp": utc_now_iso(),
                            "reason": "seeded",
                            "metadata": {},
                        }
                    ],
                }
            )

        default_policy_matrix = {
            "pay_rent": {
                "action_type": "pay_rent",
                "requires_approval": True,
                "max_amount": 150000.0,
                "allow_trusted_recurring_bypass": True,
            },
            "pay_bill": {
                "action_type": "pay_bill",
                "requires_approval": True,
                "max_amount": 50000.0,
                "allow_trusted_recurring_bypass": True,
            },
            "pay_gas": {
                "action_type": "pay_gas",
                "requires_approval": True,
                "max_amount": 10000.0,
                "allow_trusted_recurring_bypass": True,
            },
            "pay_utility": {
                "action_type": "pay_utility",
                "requires_approval": True,
                "max_amount": 50000.0,
                "allow_trusted_recurring_bypass": True,
            },
            "transfer_savings": {
                "action_type": "transfer_savings",
                "requires_approval": True,
                "max_amount": 25000.0,
                "allow_trusted_recurring_bypass": True,
            },
        }

        return {
            "profile": {
                "user_id": user_id,
                "current_balance": current_balance,
                "available_balance": available_balance,
                "last_updated": utc_now_iso(),
            },
            "accounts": [account],
            "transactions": transactions,
            "beneficiaries": [],
            "schedules": [],
            "products": [
                {
                    "id": "prod_savings_plus",
                    "name": "Savings Plus",
                    "category": "savings",
                    "interest_rate": 4.5,
                },
                {
                    "id": "prod_fd_1yr",
                    "name": "1-Year Fixed Deposit",
                    "category": "investments",
                    "interest_rate": 7.1,
                },
                {
                    "id": "prod_credit_bridge",
                    "name": "Credit Bridge",
                    "category": "credit",
                    "interest_rate": 12.0,
                },
                {
                    "id": "prod_home_loan",
                    "name": "Care Home Loan",
                    "category": "loan",
                    "interest_rate": 8.5,
                },
                {
                    "id": "prod_auto_loan",
                    "name": "Care Auto Loan",
                    "category": "loan",
                    "interest_rate": 9.2,
                },
                {
                    "id": "prod_cc_platinum",
                    "name": "Platinum Rewards Card",
                    "category": "credit_card",
                    "interest_rate": 18.0,
                },
                {
                    "id": "prod_health_insure",
                    "name": "Care Health Insurance",
                    "category": "insurance",
                    "interest_rate": 0.0,
                },
            ],
            "bank_plans": {
                "plans": [
                    {
                        "plan_id": "starter",
                        "name": "Starter",
                        "monthly_fee": 0.0,
                        "features": ["upi", "neft", "insights"],
                    }
                ]
            },
            "bank_policies": {
                "country": "IN",
                "policy_version": "proxy-1",
                "default_payment_rail": "UPI",
                "regulatory_context": ["synthetic"],
                "policy_matrix": default_policy_matrix,
            },
            "providers": [
                {
                    "provider_id": "agentic_proxy",
                    "name": "Agentic Proxy Bank",
                    "status": "active",
                }
            ],
            "next_ids": {
                "transaction": 2000,
                "beneficiary": 1,
                "schedule": 1,
                "account": 2,
            },
            "simulation": {"enabled": True, "scenario": None},
        }
