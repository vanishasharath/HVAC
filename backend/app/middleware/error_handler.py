import logging

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

logger = logging.getLogger("errors")


def _error_response(code: str, message: str, status_code: int) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"success": False, "error": {"code": code, "message": message}})


def register_exception_handlers(app: FastAPI):
    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        code = {400: "BAD_REQUEST", 401: "UNAUTHORIZED", 403: "FORBIDDEN", 404: "NOT_FOUND",
                409: "CONFLICT", 422: "UNPROCESSABLE_ENTITY"}.get(exc.status_code, "ERROR")
        return _error_response(code, str(exc.detail), exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        return _error_response("VALIDATION_ERROR", "Request validation failed", status.HTTP_422_UNPROCESSABLE_ENTITY)

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        logger.error("Unhandled exception on %s: %s", request.url.path, exc, exc_info=True)
        return _error_response("INTERNAL_SERVER_ERROR", "An unexpected error occurred", status.HTTP_500_INTERNAL_SERVER_ERROR)
