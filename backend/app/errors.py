import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("securesign")


class AppError(Exception):
    def __init__(self, code: str, message: str, status: int,
                 headers: dict[str, str] | None = None) -> None:
        self.code, self.message, self.status = code, message, status
        # For the few answers that are incomplete without one — Retry-After on a 429.
        self.headers = headers


def _envelope(status: int, code: str, message: str,
              headers: dict[str, str] | None = None) -> JSONResponse:
    return JSONResponse(status_code=status, headers=headers,
                        content={"error": {"code": code, "message": message}})


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def app_error(_: Request, exc: AppError) -> JSONResponse:
        return _envelope(exc.status, exc.code, exc.message, exc.headers)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {401: "AUTH_REQUIRED", 403: "FORBIDDEN", 404: "NOT_FOUND",
                413: "PAYLOAD_TOO_LARGE"}.get(exc.status_code, "HTTP_ERROR")
        return _envelope(exc.status_code, code, str(exc.detail))

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        return _envelope(422, "INVALID_INPUT", "Request validation failed.")

    @app.exception_handler(OperationalError)
    async def database_unreachable(_: Request, exc: OperationalError) -> JSONResponse:
        # Fail closed, and say which failure this is: 503 means "we are down, try again",
        # where 500 means "we are broken". A caller can act on the difference, and the
        # Retry-After spares the server a thundering retry the moment it returns.
        log.error("database unreachable: %s", exc.orig or exc)
        return _envelope(503, "SERVICE_UNAVAILABLE",
                         "The service is temporarily unavailable. Please try again shortly.",
                         headers={"Retry-After": "10"})

    @app.exception_handler(Exception)
    async def internal_error(_: Request, exc: Exception) -> JSONResponse:
        log.exception("internal error")  # full detail server-side only (book 10.1.5)
        return _envelope(500, "INTERNAL", "An internal error occurred.")
