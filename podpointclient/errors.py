"""Custom errors and helpers for interpreting API failures."""

import re
from typing import Optional

class APIError(Exception):
    """The most generic APIError"""

    def __init__(self, *args, status: int = None):
        super().__init__(*args)
        # APIWrapper historically constructed APIError(status, response).  Keep
        # those args compatible while giving callers a reliable public field.
        self.status = status if status is not None else _status_from_args(args)


def _status_from_args(args) -> Optional[int]:
    """Extract an HTTP status from legacy APIError constructor arguments."""
    for value in args:
        if isinstance(value, int) and not isinstance(value, bool):
            return value
        if isinstance(value, str):
            match = re.search(r"(?:\(|\b)([1-5][0-9]{2})(?:\)|\b)", value)
            if match:
                return int(match.group(1))
    return None


def api_error_status(error: APIError) -> Optional[int]:
    """Return the HTTP status carried by an API error, when available."""
    status = getattr(error, "status", None)
    return status if status is not None else _status_from_args(error.args)


def is_unsupported_api_error(error: APIError) -> bool:
    """Whether an API failure confirms that an endpoint is absent."""
    return api_error_status(error) in (404, 410)


class UnsupportedCapabilityError(APIError):
    """Raised when a charger or installed client does not support a capability."""

    def __init__(self, capability, ppid: str = None):
        self.capability = capability
        self.ppid = ppid
        name = getattr(capability, "value", str(capability))
        suffix = f" for charger {ppid}" if ppid else ""
        super().__init__(f"Capability '{name}' is unsupported{suffix}")

class AuthError(APIError):
    """An error relating to authentication with pod point"""
    def __init__(self, status, response):
        message = f'Auth Error ({status}) - {response}'
        super().__init__(message)

class SessionError(APIError):
    """An error relating to session creation with pod point"""
    def __init__(self, status, response):
        message = f'Session Error ({status}) - {response}'
        super().__init__(message)

class ApiConnectionError(APIError):
    """An error relating to connecting to pod point"""
    def __init__(self, message):
        super().__init__(f'Connection Error: {message}')

class ChargeOverrideValidationError(Exception):
    """An error relating to connecting to pod point"""
    def __init__(self):
        super().__init__(
            'A validate error occured when processing charge override. Please '
            'ensure that an hour, minute or second value is passed and that it is > 0.'
        )


class RequestValidationError(ValueError):
    """Raised before sending an invalid request to Pod Point."""


class ChargeModeTransitionError(APIError):
    """Raised when a prerequisite charger-mode transition does not succeed."""
