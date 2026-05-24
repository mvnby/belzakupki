from __future__ import annotations

import os
import time
from unittest.mock import MagicMock, patch
import httpx
import pytest

from worker.sources.icetrade_by import (
    USER_AGENTS,
    build_headers,
    _apply_throttling,
    _create_client,
    _execute_request,
    is_retryable_exception,
)

def test_user_agent_rotation():
    # Verify we get a user agent from the pool and it rotates/randomizes
    uas = set()
    for _ in range(50):
        headers = build_headers()
        ua = headers.get("User-Agent")
        assert ua in USER_AGENTS
        uas.add(ua)
    
    # Since there are 6 distinct user agents, we should get more than 1 in 50 runs
    assert len(uas) > 1

def test_proxy_configuration():
    # 1. No proxy
    with patch.dict(os.environ, {}, clear=True):
        client = _create_client(verify_ssl=True)
        # Verify no mounts
        assert len(client._mounts) == 0

    # 2. With proxy
    proxy_url = "http://user:pass@1.2.3.4:5678"
    with patch.dict(os.environ, {"ICETRADE_PROXY": proxy_url}):
        client = _create_client(verify_ssl=False)
        # Verify proxy is configured
        assert len(client._mounts) == 1
        proxy_mount = list(client._mounts.values())[0]
        assert proxy_mount._pool._proxy_url.host == b"1.2.3.4"
        assert proxy_mount._pool._proxy_url.port == 5678

def test_apply_throttling():
    # 1. Test with max > min
    with patch.dict(os.environ, {"ICETRADE_MIN_DELAY": "0.1", "ICETRADE_MAX_DELAY": "0.3"}):
        with patch("time.sleep") as mock_sleep:
            _apply_throttling()
            mock_sleep.assert_called_once()
            sleep_val = mock_sleep.call_args[0][0]
            assert 0.1 <= sleep_val <= 0.3

    # 2. Test with min = max
    with patch.dict(os.environ, {"ICETRADE_MIN_DELAY": "0.2", "ICETRADE_MAX_DELAY": "0.2"}):
        with patch("time.sleep") as mock_sleep:
            _apply_throttling()
            mock_sleep.assert_called_once_with(0.2)

def test_is_retryable_exception():
    # 429 is retryable
    resp_429 = httpx.Response(429, request=httpx.Request("GET", "http://test"))
    assert is_retryable_exception(httpx.HTTPStatusError("Err", request=None, response=resp_429)) == True

    # 503 is retryable
    resp_503 = httpx.Response(503, request=httpx.Request("GET", "http://test"))
    assert is_retryable_exception(httpx.HTTPStatusError("Err", request=None, response=resp_503)) == True

    # 404 is NOT retryable
    resp_404 = httpx.Response(404, request=httpx.Request("GET", "http://test"))
    assert is_retryable_exception(httpx.HTTPStatusError("Err", request=None, response=resp_404)) == False

    # Timeout is retryable
    assert is_retryable_exception(httpx.TimeoutException("Timeout")) == True
    # Connect error is retryable
    assert is_retryable_exception(httpx.ConnectError("Connect")) == True

def test_execute_request_success():
    client = MagicMock(spec=httpx.Client)
    mock_resp = httpx.Response(200, text="Success", request=httpx.Request("GET", "http://test"))
    client.request.return_value = mock_resp

    with patch("time.sleep") as mock_sleep:
        resp = _execute_request(client, "GET", "http://test")
        assert resp.status_code == 200
        assert resp.text == "Success"
        # Throttling is applied once
        mock_sleep.assert_called_once()

def test_execute_request_retry_on_503_then_success():
    client = MagicMock(spec=httpx.Client)
    resp_503 = httpx.Response(503, request=httpx.Request("GET", "http://test"))
    resp_200 = httpx.Response(200, text="OK", request=httpx.Request("GET", "http://test"))
    
    # Raise HTTPStatusError(503) on first try, return 200 on second try
    client.request.side_effect = [
        httpx.HTTPStatusError("Unavailable", request=None, response=resp_503),
        resp_200
    ]

    with patch("time.sleep") as mock_sleep:
        resp = _execute_request(client, "GET", "http://test")
        assert resp.status_code == 200
        assert resp.text == "OK"
        # It should have executed the request twice
        assert client.request.call_count == 2
        # 2 throttling sleeps + 1 tenacity wait sleep = 3 sleeps total
        assert mock_sleep.call_count == 3

def test_execute_request_max_retries_failure():
    client = MagicMock(spec=httpx.Client)
    resp_503 = httpx.Response(503, request=httpx.Request("GET", "http://test"))
    client.request.side_effect = httpx.HTTPStatusError("Unavailable", request=None, response=resp_503)

    with patch("time.sleep") as mock_sleep:
        # tenacity reraises the HTTPStatusError when reraise=True
        with pytest.raises(httpx.HTTPStatusError) as exc_info:
            _execute_request(client, "GET", "http://test")
        
        assert exc_info.value.response.status_code == 503
        # The client should have been called 3 times (1 initial + 2 retries)
        assert client.request.call_count == 3
        # 3 throttling sleeps + 2 tenacity wait sleeps = 5 sleeps total
        assert mock_sleep.call_count == 5
