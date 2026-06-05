from __future__ import annotations

import hashlib
import json
import random
import sqlite3
from datetime import datetime, timezone, timedelta
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


def _is_postgres_target(db_target: str) -> bool:
    return db_target.startswith("postgres://") or db_target.startswith(
        "postgresql://"
    )


def _normalize_postgres_dsn(db_target: str) -> str:
    if db_target.startswith("postgres://"):
        return "postgresql://" + db_target.removeprefix("postgres://")
    return db_target


def _get_psycopg2():
    try:
        import psycopg2
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "PostgreSQL storage requires psycopg2-binary to be installed"
        ) from exc
    return psycopg2


class Storage:
    def __init__(self, db_path: str) -> None:
        self._is_postgres = _is_postgres_target(db_path)
        self._lock = Lock()
        if self._is_postgres:
            self._dsn = _normalize_postgres_dsn(db_path)
            self._conn = None
        else:
            self._dsn = ""
            self._conn = sqlite3.connect(db_path, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
        self._init_db()

    def _sqlite_execute(self, query: str, params: tuple[Any, ...] = ()) -> None:
        with self._lock:
            assert self._conn is not None
            self._conn.execute(query, params)
            self._conn.commit()

    def _sqlite_fetchone(
        self, query: str, params: tuple[Any, ...] = ()
    ) -> sqlite3.Row | None:
        with self._lock:
            assert self._conn is not None
            cursor = self._conn.execute(query, params)
            return cursor.fetchone()

    def _sqlite_fetchall(
        self, query: str, params: tuple[Any, ...] = ()
    ) -> list[sqlite3.Row]:
        with self._lock:
            assert self._conn is not None
            cursor = self._conn.execute(query, params)
            return cursor.fetchall()

    def _postgres_execute(self, query: str, params: tuple[Any, ...] = ()) -> None:
        psycopg2 = _get_psycopg2()
        with psycopg2.connect(self._dsn) as conn:
            with conn.cursor() as cursor:
                cursor.execute(query, params)

    def _postgres_fetchone(
        self, query: str, params: tuple[Any, ...] = ()
    ) -> tuple[Any, ...] | None:
        psycopg2 = _get_psycopg2()
        with psycopg2.connect(self._dsn) as conn:
            with conn.cursor() as cursor:
                cursor.execute(query, params)
                return cursor.fetchone()

    def _postgres_fetchall(
        self, query: str, params: tuple[Any, ...] = ()
    ) -> list[tuple[Any, ...]]:
        psycopg2 = _get_psycopg2()
        with psycopg2.connect(self._dsn) as conn:
            with conn.cursor() as cursor:
                cursor.execute(query, params)
                return cursor.fetchall()

    def _init_db(self) -> None:
        statements = [
            """
            CREATE TABLE IF NOT EXISTS response_cache (
                fingerprint TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                method TEXT NOT NULL,
                path TEXT NOT NULL,
                response_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS world_state (
                user_id TEXT PRIMARY KEY,
                state_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """,
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
            """,
        ]
        if self._is_postgres:
            psycopg2 = _get_psycopg2()
            with psycopg2.connect(self._dsn) as conn:
                with conn.cursor() as cursor:
                    for statement in statements:
                        cursor.execute(statement)
            return

        with self._lock:
            assert self._conn is not None
            for statement in statements:
                self._conn.execute(statement)
            self._conn.commit()

    def get_cache(self, fingerprint: str) -> dict | None:
        if self._is_postgres:
            row = self._postgres_fetchone(
                "SELECT response_json FROM response_cache WHERE fingerprint = %s",
                (fingerprint,),
            )
        else:
            row = self._sqlite_fetchone(
                "SELECT response_json FROM response_cache WHERE fingerprint = ?",
                (fingerprint,),
            )
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
        if self._is_postgres:
            self._postgres_execute(
                """
                INSERT INTO response_cache
                    (fingerprint, user_id, method, path, response_json, created_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (fingerprint) DO UPDATE SET
                    user_id = EXCLUDED.user_id,
                    method = EXCLUDED.method,
                    path = EXCLUDED.path,
                    response_json = EXCLUDED.response_json,
                    created_at = EXCLUDED.created_at
                """,
                (fingerprint, user_id, method, path, payload, utc_now_iso()),
            )
            return

        self._sqlite_execute(
            """
            INSERT OR REPLACE INTO response_cache
                (fingerprint, user_id, method, path, response_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (fingerprint, user_id, method, path, payload, utc_now_iso()),
        )

    def delete_cache_entries(
        self,
        *,
        user_id: str,
        method: str,
        path: str,
    ) -> None:
        if self._is_postgres:
            self._postgres_execute(
                "DELETE FROM response_cache WHERE user_id = %s AND method = %s AND path = %s",
                (user_id, method, path),
            )
            return

        self._sqlite_execute(
            "DELETE FROM response_cache WHERE user_id = ? AND method = ? AND path = ?",
            (user_id, method, path),
        )

    def get_state(self, user_id: str) -> dict | None:
        if self._is_postgres:
            row = self._postgres_fetchone(
                "SELECT state_json FROM world_state WHERE user_id = %s",
                (user_id,),
            )
        else:
            row = self._sqlite_fetchone(
                "SELECT state_json FROM world_state WHERE user_id = ?",
                (user_id,),
            )
        if not row:
            return None
        return _json_loads(row[0])

    def save_state(self, user_id: str, state: dict) -> None:
        payload = _json_dumps(state)
        if self._is_postgres:
            self._postgres_execute(
                """
                INSERT INTO world_state
                    (user_id, state_json, updated_at)
                VALUES (%s, %s, %s)
                ON CONFLICT (user_id) DO UPDATE SET
                    state_json = EXCLUDED.state_json,
                    updated_at = EXCLUDED.updated_at
                """,
                (user_id, payload, utc_now_iso()),
            )
            return

        self._sqlite_execute(
            """
            INSERT OR REPLACE INTO world_state
                (user_id, state_json, updated_at)
            VALUES (?, ?, ?)
            """,
            (user_id, payload, utc_now_iso()),
        )

    def list_state_users(self) -> list[str]:
        if self._is_postgres:
            rows = self._postgres_fetchall("SELECT user_id FROM world_state")
        else:
            rows = self._sqlite_fetchall("SELECT user_id FROM world_state")
        return [str(row[0]) for row in rows]

    def get_dead_letters(self, status_filter: str | None = None) -> list[dict]:
        query = "SELECT * FROM dead_letters"
        params: tuple[Any, ...] = ()
        if status_filter:
            query += " WHERE status = %s" if self._is_postgres else " WHERE status = ?"
            params = (status_filter,)
        rows = (
            self._postgres_fetchall(query, params)
            if self._is_postgres
            else self._sqlite_fetchall(query, params)
        )
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
        query = (
            "SELECT * FROM dead_letters WHERE id = %s"
            if self._is_postgres
            else "SELECT * FROM dead_letters WHERE id = ?"
        )
        row = (
            self._postgres_fetchone(query, (dead_letter_id,))
            if self._is_postgres
            else self._sqlite_fetchone(query, (dead_letter_id,))
        )
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
        params = (
            record.get("id"),
            record.get("webhook_url"),
            payload,
            attempts_payload,
            record.get("status"),
            int(record.get("attempt_count") or 0),
            record.get("last_error"),
            record.get("created_at") or utc_now_iso(),
            record.get("updated_at") or utc_now_iso(),
        )
        if self._is_postgres:
            self._postgres_execute(
                """
                INSERT INTO dead_letters
                    (id, webhook_url, payload_json, attempts_json, status,
                     attempt_count, last_error, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    webhook_url = EXCLUDED.webhook_url,
                    payload_json = EXCLUDED.payload_json,
                    attempts_json = EXCLUDED.attempts_json,
                    status = EXCLUDED.status,
                    attempt_count = EXCLUDED.attempt_count,
                    last_error = EXCLUDED.last_error,
                    created_at = EXCLUDED.created_at,
                    updated_at = EXCLUDED.updated_at
                """,
                params,
            )
            return

        self._sqlite_execute(
            """
            INSERT OR REPLACE INTO dead_letters
                (id, webhook_url, payload_json, attempts_json, status,
                 attempt_count, last_error, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            params,
        )

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
        now = datetime.now(timezone.utc)
        for index in range(80):
            amount = round(-(100 + rng.random() * 2500), 2)
            if rng.random() > 0.85:
                # Occasional credit (e.g. salary, refund)
                amount = round((5000 + rng.random() * 20000), 2)
            
            days_ago = rng.randint(0, 90)
            hours_ago = rng.randint(0, 23)
            tx_date = (now - timedelta(days=days_ago, hours=hours_ago)).isoformat()

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
                            "Tech Store",
                            "Health Plus",
                            "Food Delivery Co",
                        ]
                    ),
                    "category": rng.choice(
                        ["food", "shopping", "fuel", "utilities", "entertainment", "health", "transfer"]
                    ),
                    "description": "Synthetic transaction",
                    "date": tx_date,
                    "status": "success",
                    "lifecycle": [
                        {
                            "status": "success",
                            "timestamp": tx_date,
                            "reason": "seeded",
                            "metadata": {},
                        }
                    ],
                }
            )
        
        # Sort transactions by date descending
        transactions.sort(key=lambda t: t["date"], reverse=True)

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
