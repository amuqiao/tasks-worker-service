from fastapi import APIRouter, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from app.core.context import get_request_id, get_trace_id
from app.core.lifecycle import run_health_checks
from app.schemas.envelope import error_envelope, success_envelope

router = APIRouter(tags=["health"])


@router.get("/health", operation_id="health")
async def health() -> object:
    return success_envelope(
        {"status": "ok"},
        request_id=get_request_id(),
        trace_id=get_trace_id(),
    )


@router.get("/ready", operation_id="ready")
async def ready(request: Request) -> object:
    result = await run_health_checks(request.app.state.health_checks)
    if result["status"] == "failed":
        status_code, body = error_envelope(
            "DEPENDENCY_UNAVAILABLE",
            request_id=get_request_id(),
            trace_id=get_trace_id(),
            details=result,
        )
        return JSONResponse(status_code=status_code, content=jsonable_encoder(body))
    return success_envelope(
        result,
        request_id=get_request_id(),
        trace_id=get_trace_id(),
    )
