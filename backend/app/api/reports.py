from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response

from app.security.dependencies import get_current_user
from app.services.report_service import generate_hvac_report

router = APIRouter(prefix="/api/v1/reports", tags=["reports"])


@router.get("/{hvac_id}")
async def get_report(hvac_id: str, hours: int = Query(default=24, ge=1, le=8760), current_user: dict = Depends(get_current_user)):
    pdf_bytes = await generate_hvac_report(hvac_id, hours=hours)
    return Response(content=pdf_bytes, media_type="application/pdf",
                     headers={"Content-Disposition": f'attachment; filename="report_{hvac_id}.pdf"'})
