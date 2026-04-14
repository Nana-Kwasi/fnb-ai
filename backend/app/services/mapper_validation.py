from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError


class FraudCanonicalV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    transaction_id: str
    account_id: str
    amount: float
    currency: str
    channel: str
    device_id: str | None = None
    ip_address: str | None = None
    merchant_id: str | None = None
    location_country: str | None = None
    tx_timestamp: str
    velocity_1h: int | None = None


class CareCanonicalV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str
    customer_id: str
    message_text: str
    channel: str
    language: str | None = None
    intent_metadata: dict[str, Any] | None = None
    message_ts: str | None = None


def get_contract_schema(model_type: str, contract_version: str) -> type[BaseModel]:
    if model_type == "fraud" and contract_version == "v1":
        return FraudCanonicalV1
    if model_type == "care" and contract_version == "v1":
        return CareCanonicalV1
    raise ValueError(f"Unsupported contract: {model_type}_{contract_version}")


def _deep_get(payload: dict[str, Any], path: str) -> Any:
    cur: Any = payload
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            raise KeyError(path)
    return cur


def apply_mapper_to_raw(mapping_json: dict[str, Any], raw_payload: dict[str, Any]) -> dict[str, Any]:
    canonical: dict[str, Any] = {}
    for target_field, rule in (mapping_json or {}).items():
        if isinstance(rule, str):
            canonical[target_field] = _deep_get(raw_payload, rule)
        elif isinstance(rule, dict):
            if "path" in rule and isinstance(rule["path"], str):
                canonical[target_field] = _deep_get(raw_payload, rule["path"])
            elif "value" in rule:
                canonical[target_field] = rule["value"]
            else:
                raise ValueError(f"Invalid mapper rule for '{target_field}'")
        else:
            raise ValueError(f"Invalid mapper rule type for '{target_field}'")
    return canonical


def validate_mapper_shape(
    *,
    model_type: str,
    contract_version: str,
    mapping_json: dict[str, Any],
) -> list[str]:
    errors: list[str] = []
    if not isinstance(mapping_json, dict) or not mapping_json:
        return ["mapping_json must be a non-empty object."]
    try:
        schema = get_contract_schema(model_type, contract_version)
    except ValueError as exc:
        return [str(exc)]

    allowed = set(schema.model_fields.keys())
    unknown_targets = [k for k in mapping_json.keys() if k not in allowed]
    if unknown_targets:
        errors.append(f"Unknown target fields: {', '.join(sorted(unknown_targets))}")
    return errors


def validate_and_dry_run(
    *,
    model_type: str,
    contract_version: str,
    mapping_json: dict[str, Any],
    raw_payload: dict[str, Any],
) -> tuple[dict[str, Any] | None, list[str]]:
    errors = validate_mapper_shape(
        model_type=model_type,
        contract_version=contract_version,
        mapping_json=mapping_json,
    )
    if errors:
        return None, errors
    try:
        canonical = apply_mapper_to_raw(mapping_json, raw_payload)
    except (KeyError, ValueError) as exc:
        return None, [str(exc)]

    schema = get_contract_schema(model_type, contract_version)
    try:
        out = schema.model_validate(canonical)
        return out.model_dump(), []
    except ValidationError as exc:
        return None, [e.get("msg", "Validation error") for e in exc.errors()]
