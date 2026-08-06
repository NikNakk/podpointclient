"""Utilities for ensuring credentials do not escape into logs or exceptions."""
from collections.abc import Mapping
from typing import Any, Iterable

REDACTED = "<redacted>"
RESPONSE_BODY_OMITTED = "Response body omitted for security"

_SENSITIVE_KEY_PARTS = (
    "authorization",
    "credential",
    "email",
    "password",
    "secret",
    "token",
)


def _is_sensitive_key(key: Any) -> bool:
    normalized = str(key).lower().replace("-", "").replace("_", "")
    return any(part in normalized for part in _SENSITIVE_KEY_PARTS)


def _redact_known_values(value: str, sensitive_values: Iterable[Any]) -> str:
    result = value
    for sensitive_value in sensitive_values:
        if sensitive_value is None:
            continue
        sensitive_text = str(sensitive_value)
        if sensitive_text:
            result = result.replace(sensitive_text, REDACTED)
    return result


def sanitize_for_logging(
    value: Any,
    sensitive_values: Iterable[Any] = ()
) -> Any:
    """Return a log-safe copy with sensitive keys and known values redacted."""
    return _sanitize(value, tuple(sensitive_values))


def _sanitize(value: Any, sensitive_values: tuple) -> Any:
    if isinstance(value, Mapping):
        return {
            key: (
                REDACTED
                if _is_sensitive_key(key)
                else _sanitize(item, sensitive_values)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_sanitize(item, sensitive_values) for item in value]
    if isinstance(value, tuple):
        return tuple(_sanitize(item, sensitive_values) for item in value)
    if isinstance(value, str):
        return _redact_known_values(value, sensitive_values)
    return value


def url_for_logging(url: str) -> str:
    """Return a URL without query parameters or fragments."""
    return str(url).split("?", 1)[0].split("#", 1)[0]
