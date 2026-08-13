from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse
from starlette.exceptions import HTTPException


def _expects_html_navigation(request: Request) -> bool:
    if request.url.path.startswith("/api/") or request.headers.get("X-Talos-Async") == "true":
        return False
    return request.method != "GET" and "text/html" in request.headers.get("accept", "")


def _error_target(request: Request, message: str) -> str:
    fallback = "/login" if getattr(request.state, "user", None) is None else "/"
    referer = request.headers.get("referer")
    if not referer:
        target = urlsplit(fallback)
    else:
        target = urlsplit(referer)
        if target.netloc and target.netloc != request.url.netloc:
            target = urlsplit(fallback)
    query = [(key, value) for key, value in parse_qsl(target.query) if key != "error"]
    query.append(("error", message))
    return urlunsplit(("", "", target.path or fallback, urlencode(query), target.fragment))


async def http_exception_handler(request: Request, exc: HTTPException):
    if _expects_html_navigation(request):
        return RedirectResponse(_error_target(request, str(exc.detail)), status_code=303)
    return JSONResponse(
        {"detail": exc.detail},
        status_code=exc.status_code,
        headers=exc.headers,
    )


async def validation_exception_handler(request: Request, exc: RequestValidationError):
    if _expects_html_navigation(request):
        errors = exc.errors()
        if errors:
            location = ".".join(str(part) for part in errors[0].get("loc", ())[1:])
            detail = errors[0].get("msg", "Invalid form data")
            message = f"{location}: {detail}" if location else detail
        else:
            message = "Invalid form data"
        return RedirectResponse(_error_target(request, message), status_code=303)
    return JSONResponse({"detail": exc.errors()}, status_code=422)
