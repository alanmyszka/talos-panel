from urllib.parse import parse_qs, urlsplit

import pytest
from starlette.exceptions import HTTPException
from starlette.requests import Request

from talos_panel.error_handlers import http_exception_handler


def request_for(path: str, *, accept: str, referer: str | None = None) -> Request:
    headers = [(b"accept", accept.encode())]
    if referer:
        headers.append((b"referer", referer.encode()))
    return Request(
        {
            "type": "http",
            "method": "POST",
            "scheme": "http",
            "server": ("localhost", 8000),
            "path": path,
            "query_string": b"",
            "headers": headers,
        }
    )


@pytest.mark.asyncio
async def test_browser_form_error_redirects_back_with_message() -> None:
    request = request_for(
        "/servers",
        accept="text/html,application/xhtml+xml",
        referer="http://localhost:8000/servers/new",
    )
    response = await http_exception_handler(
        request, HTTPException(409, "Host port is already assigned")
    )

    assert response.status_code == 303
    target = urlsplit(response.headers["location"])
    assert target.path == "/servers/new"
    assert parse_qs(target.query)["error"] == ["Host port is already assigned"]


@pytest.mark.asyncio
async def test_api_error_remains_json() -> None:
    request = request_for("/api/v1/servers", accept="application/json")
    response = await http_exception_handler(request, HTTPException(409, "Conflict"))

    assert response.status_code == 409
    assert response.body == b'{"detail":"Conflict"}'
