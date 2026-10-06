"""DEMO ONLY. Mutate the stored application payload. Never writes to Hornet."""

from __future__ import annotations

from typing import Any

# Sentinel temperature used when the caller does not supply a replacement.
# It is intentionally outside a normal sensor range so content_match fails.
DEMO_TEMPERATURE = 999.9


def mutate_application_payload(
    payload: Any,
    *,
    replacement: Any = None,
    replacement_set: bool = False,
    temperature: float | None = None,
) -> Any:
    """Return a new application payload.

    replacement_set distinguishes "no replacement" from an explicit JSON null.
    When neither a replacement nor a temperature is given, the demo default
    overwrites the temperature field and marks the object as tampered.
    """
    use_default = not replacement_set and temperature is None
    if replacement_set:
        payload = replacement
    if use_default:
        temperature = DEMO_TEMPERATURE

    if temperature is None:
        return payload

    if not isinstance(payload, dict):
        if use_default:
            return {
                "temperature": temperature,
                "_demo_tampered": True,
                "_previous": payload,
            }
        raise ValueError("temperature tamper requires a JSON object payload")

    updated = dict(payload)
    updated["temperature"] = temperature
    if use_default:
        updated["_demo_tampered"] = True
    return updated
