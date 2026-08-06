"""Regression tests preventing credentials from escaping through diagnostics."""
import logging
from datetime import datetime, timedelta

import aiohttp
from aioresponses import aioresponses
import pytest

from podpointclient.client import PodPointClient
from podpointclient.endpoints import (
    API_BASE_URL, CHARGERS, GOOGLE_BASE_URL, PASSWORD_VERIFY, SESSIONS,
)
from podpointclient.errors import APIError
from podpointclient.helpers.api_wrapper import APIWrapper
from podpointclient.helpers.auth import Auth
from podpointclient.helpers.redaction import REDACTED, sanitize_for_logging

EMAIL = "credential-leak@example.invalid"
PASSWORD = "distinctive-password-secret"
ACCESS_TOKEN = "distinctive-access-token"
REFRESH_TOKEN = "distinctive-refresh-token"


def assert_secrets_absent(value):
    text = str(value)
    for secret in (EMAIL, PASSWORD, ACCESS_TOKEN, REFRESH_TOKEN):
        assert secret not in text


@pytest.mark.asyncio
async def test_wrapper_never_logs_json_or_form_request_bodies(caplog):
    caplog.set_level(logging.DEBUG)
    with aioresponses() as mocked:
        mocked.post(
            "https://example.invalid/login?token=query-secret",
            payload={},
        )
        mocked.post("https://example.invalid/refresh", payload={})
        async with aiohttp.ClientSession() as session:
            wrapper = APIWrapper(session)
            await wrapper.post(
                "https://example.invalid/login?token=query-secret",
                body={"email": EMAIL, "password": PASSWORD},
                headers={},
            )
            await wrapper.post(
                "https://example.invalid/refresh",
                body=f"grant_type=refresh_token&refresh_token={REFRESH_TOKEN}",
                headers={},
            )

    assert_secrets_absent(caplog.text)
    assert "query-secret" not in caplog.text
    assert "POST https://example.invalid/login" in caplog.text


@pytest.mark.asyncio
async def test_auth_debug_logging_redacts_successful_credentials(caplog):
    caplog.set_level(logging.DEBUG)
    auth_response = {
        "expiresIn": "3600",
        "idToken": ACCESS_TOKEN,
        "refreshToken": REFRESH_TOKEN,
        "message": f"issued for {EMAIL}",
    }
    session_response = {
        "sessions": {"id": "session-id", "user_id": "user-id"}
    }
    with aioresponses() as mocked:
        mocked.post(f"{GOOGLE_BASE_URL}{PASSWORD_VERIFY}", payload=auth_response)
        mocked.post(f"{API_BASE_URL}{SESSIONS}", payload=session_response)
        async with aiohttp.ClientSession() as session:
            auth = Auth(
                email=EMAIL,
                password=PASSWORD,
                session=session,
                http_debug=True,
            )
            assert await auth.async_update_access_token() is True

    assert_secrets_absent(caplog.text)
    assert REDACTED in caplog.text


@pytest.mark.asyncio
async def test_http_error_body_is_absent_from_exception_and_logs(caplog):
    caplog.set_level(logging.DEBUG)
    response_body = (
        '{"email":"' + EMAIL + '","password":"' + PASSWORD
        + '","refresh_token":"' + REFRESH_TOKEN + '"}'
    )
    with aioresponses() as mocked:
        mocked.get(
            "https://example.invalid/failure",
            status=400,
            body=response_body,
        )
        async with aiohttp.ClientSession() as session:
            wrapper = APIWrapper(session)
            with pytest.raises(APIError) as exc_info:
                await wrapper.get(
                    "https://example.invalid/failure",
                    headers={"Authorization": f"Bearer {ACCESS_TOKEN}"},
                )

    assert "Response body omitted for security" in str(exc_info.value)
    assert_secrets_absent(exc_info.value)
    assert_secrets_absent(caplog.text)


@pytest.mark.asyncio
async def test_client_http_debug_redacts_known_and_keyed_secrets(caplog):
    caplog.set_level(logging.DEBUG)
    payload = {
        "email": EMAIL,
        "password": PASSWORD,
        "accessToken": ACCESS_TOKEN,
        "nested": {"refresh_token": REFRESH_TOKEN},
        "message": f"response for {EMAIL} using {ACCESS_TOKEN}",
    }
    with aioresponses() as mocked:
        mocked.get(f"https://mobile-api.pod-point.com{CHARGERS}", payload=payload)
        async with aiohttp.ClientSession() as session:
            client = PodPointClient(
                EMAIL,
                PASSWORD,
                session=session,
                http_debug=True,
            )
            client.auth.access_token = ACCESS_TOKEN
            client.auth.refresh_token = REFRESH_TOKEN
            client.auth.access_token_expiry = datetime.now() + timedelta(hours=1)
            assert await client.async_get_chargers() == []

    assert_secrets_absent(caplog.text)
    assert REDACTED in caplog.text


def test_recursive_redaction_handles_sensitive_keys_and_known_values():
    value = {
        "authorization": f"Bearer {ACCESS_TOKEN}",
        "credentials": [{"password": PASSWORD}],
        "message": f"token value was {REFRESH_TOKEN}",
    }
    sanitized = sanitize_for_logging(value, sensitive_values=(REFRESH_TOKEN,))

    assert sanitized["authorization"] == REDACTED
    assert sanitized["credentials"] == REDACTED
    assert sanitized["message"] == f"token value was {REDACTED}"
    assert_secrets_absent(sanitized)
