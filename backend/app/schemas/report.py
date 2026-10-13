from pydantic import BaseModel


class ReportRequest(BaseModel):
    hours: int = 24
