from __future__ import annotations

from typing import Any


SCHEMA_HINTS: dict[str, Any] = {
    "balances": {
        "current_balance": 24500.0,
        "available_balance": 23800.0,
        "last_updated": "2026-05-05T10:00:00+00:00",
    },
    "transactions": [
        {
            "id": 1234,
            "user_id": "user_001",
            "amount": -450.5,
            "merchant": "Cafe Orion",
            "category": "food",
            "description": "Synthetic transaction",
            "date": "2026-05-05T10:00:00+00:00",
        }
    ],
    "transaction_trigger": {
        "status": "accepted",
        "transaction": {
            "id": 2345,
            "user_id": "user_001",
            "amount": -1200.0,
            "merchant": "Savings Transfer",
            "category": "savings",
            "description": "Executed by action engine",
            "date": "2026-05-05T10:00:00+00:00",
            "status": "queued",
        },
        "webhook": {
            "status": "queued",
            "destination": "https://backend/api/actions/webhooks/mockbank",
        },
    },
    "transaction_lifecycle": {
        "transaction_id": 2345,
        "status": "success",
        "lifecycle": [
            {
                "status": "success",
                "timestamp": "2026-05-05T10:00:00+00:00",
                "reason": "settled",
                "metadata": {},
            }
        ],
    },
    "accounts": [
        {
            "account_id": "acc_user_001_1",
            "user_id": "user_001",
            "name": "Primary Savings",
            "account_type": "savings",
            "current_balance": 24500.0,
            "available_balance": 23800.0,
            "status": "active",
        }
    ],
    "account": {
        "account_id": "acc_user_001_2",
        "user_id": "user_001",
        "name": "Travel Bucket",
        "account_type": "savings",
        "current_balance": 1500.0,
        "available_balance": 1500.0,
        "status": "active",
    },
    "account_create": {"account": {"account_id": "acc_user_001_2"}},
    "account_delete": {"status": "deleted", "account_id": "acc_user_001_2"},
    "beneficiaries": [
        {
            "id": "benef_1",
            "user_id": "user_001",
            "name": "Mom",
            "payment_rail": "UPI",
            "upi_handle": "mom@upi",
            "reference": "upi:mom@upi",
            "verified": True,
            "created_at": "2026-05-05T10:00:00+00:00",
        }
    ],
    "beneficiary": {
        "id": "benef_1",
        "user_id": "user_001",
        "name": "Mom",
        "payment_rail": "UPI",
        "upi_handle": "mom@upi",
        "reference": "upi:mom@upi",
        "verified": True,
        "created_at": "2026-05-05T10:00:00+00:00",
    },
    "schedules": [
        {
            "id": "sch_1",
            "user_id": "user_001",
            "status": "active",
            "payload": {"amount": 500.0, "cadence": "monthly"},
            "created_at": "2026-05-05T10:00:00+00:00",
        }
    ],
    "schedule": {
        "id": "sch_1",
        "user_id": "user_001",
        "status": "active",
        "payload": {"amount": 500.0, "cadence": "monthly"},
        "created_at": "2026-05-05T10:00:00+00:00",
    },
    "schedule_result": {"status": "executed", "schedule": {"id": "sch_1"}},
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
        "policy_matrix": {},
    },
    "action_policy": {
        "action_type": "pay_rent",
        "requires_approval": True,
        "max_amount": 150000.0,
        "allow_trusted_recurring_bypass": True,
        "country": "IN",
        "policy_version": "proxy-1",
        "default_payment_rail": "UPI",
        "regulatory_context": ["synthetic"],
    },
    "products": [
        {
            "id": "prod_savings_plus",
            "name": "Savings Plus",
            "category": "savings",
            "interest_rate": 4.5,
        }
    ],
    "providers": [
        {
            "provider_id": "agentic_proxy",
            "name": "Agentic Proxy Bank",
            "status": "active",
        }
    ],
    "admin_users": {
        "users": [
            {
                "user_id": "user_001",
                "current_balance": 24500.0,
                "available_balance": 23800.0,
            }
        ]
    },
    "dead_letters": {
        "records": [
            {
                "id": "dl_1",
                "payload": {},
                "status": "dead_lettered",
                "attempt_count": 3,
            }
        ]
    },
    "profile": {
        "user_id": "user_001",
        "current_balance": 24500.0,
        "available_balance": 23800.0,
        "last_updated": "2026-05-05T10:00:00+00:00",
    },
    "simulation_toggle": {"enabled": True},
    "simulation_status": {"enabled": True, "last_updated": "2026-05-05T10:00:00+00:00"},
    "scenario_trigger": {"status": "queued", "scenario_type": "default"},
    "settlement_windows": {
        "windows": [
            {"rail": "UPI", "status": "open"},
            {"rail": "NEFT", "status": "open"},
        ]
    },
}


_VALIDATION_RULES: dict[str, dict[str, Any]] = {
    "balances": {"type": "object", "required": ["current_balance", "available_balance", "last_updated"]},
    "transactions": {
        "type": "list",
        "item_required": ["id", "user_id", "amount", "merchant", "category", "description", "date"],
    },
    "transaction_trigger": {"type": "object", "required": ["status", "transaction"]},
    "transaction_lifecycle": {"type": "object", "required": ["transaction_id", "status", "lifecycle"]},
    "accounts": {
        "type": "list",
        "item_required": [
            "account_id",
            "user_id",
            "name",
            "account_type",
            "current_balance",
            "available_balance",
            "status",
        ],
    },
    "account": {
        "type": "object",
        "required": [
            "account_id",
            "user_id",
            "name",
            "account_type",
            "current_balance",
            "available_balance",
            "status",
        ],
    },
    "account_create": {"type": "object", "required": ["account"]},
    "account_delete": {"type": "object", "required": ["status", "account_id"]},
    "beneficiaries": {
        "type": "list",
        "item_required": [
            "id",
            "user_id",
            "name",
            "reference",
            "verified",
            "created_at",
        ],
    },
    "beneficiary": {
        "type": "object",
        "required": [
            "id",
            "user_id",
            "name",
            "reference",
            "verified",
            "created_at",
        ],
    },
    "schedules": {
        "type": "list",
        "item_required": ["id", "user_id", "status", "payload", "created_at"],
    },
    "schedule": {"type": "object", "required": ["id", "user_id", "status", "payload", "created_at"]},
    "schedule_result": {"type": "object", "required": ["status"]},
    "bank_plans": {"type": "object", "required": ["plans"]},
    "bank_policies": {"type": "object", "required": ["country", "policy_version", "policy_matrix"]},
    "action_policy": {"type": "object", "required": ["action_type", "requires_approval", "max_amount"]},
    "products": {"type": "list", "item_required": ["id", "name", "category"]},
    "providers": {"type": "list", "item_required": ["provider_id", "name", "status"]},
    "admin_users": {"type": "object", "required": ["users"]},
    "dead_letters": {"type": "object", "required": ["records"]},
    "profile": {"type": "object", "required": ["user_id", "current_balance", "available_balance"]},
    "simulation_toggle": {"type": "object", "required": ["enabled"]},
    "simulation_status": {"type": "object", "required": ["enabled"]},
    "scenario_trigger": {"type": "object", "required": ["status"]},
    "settlement_windows": {"type": "object", "required": ["windows"]},
}


def get_schema_hint(schema_key: str) -> Any:
    return SCHEMA_HINTS.get(schema_key, {})


def validate_response(schema_key: str, data: Any) -> bool:
    rule = _VALIDATION_RULES.get(schema_key)
    if not rule:
        return True
    if rule["type"] == "object":
        if not isinstance(data, dict):
            return False
        for key in rule.get("required", []):
            if key not in data:
                return False
        return True
    if rule["type"] == "list":
        if not isinstance(data, list):
            return False
        required = rule.get("item_required", [])
        for item in data:
            if not isinstance(item, dict):
                return False
            for key in required:
                if key not in item:
                    return False
        return True
    return True
