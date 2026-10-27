import io
from datetime import datetime, timezone

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.services.alert_service import list_alerts
from app.services.hvac_service import get_hvac_unit


async def generate_hvac_report(hvac_id: str, hours: int = 24) -> bytes:
    hvac_unit = await get_hvac_unit(hvac_id)
    alerts = await list_alerts(hvac_id=hvac_id)

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=2 * cm, bottomMargin=2 * cm)
    styles = getSampleStyleSheet()
    story = [
        Paragraph("HVAC Monitoring Report", styles["Title"]),
        Paragraph("Academic prototype output - not a certified regulatory compliance document.", styles["Italic"]),
        Spacer(1, 12),
        Paragraph(f"<b>HVAC Unit:</b> {hvac_unit['hvac_id']} - {hvac_unit['name']}", styles["Normal"]),
        Paragraph(f"<b>Refrigerant Type:</b> {hvac_unit.get('refrigerant_type') or 'TBD'}", styles["Normal"]),
        Paragraph(f"<b>Reporting Period:</b> last {hours} hours", styles["Normal"]),
        Paragraph(f"<b>Generated:</b> {datetime.now(timezone.utc).isoformat()}", styles["Normal"]),
        Spacer(1, 12),
        Paragraph("Alerts (real AI pipeline output)", styles["Heading2"]),
    ]

    if alerts:
        table_data = [["Severity", "RF Severity", "RF Confidence", "Status", "Created At"]]
        for a in alerts:
            table_data.append([
                a["severity"], a.get("rf_severity", "-"), str(a.get("rf_confidence", "-")),
                a["status"], str(a["created_at"]),
            ])
        table = Table(table_data, colWidths=[2.5 * cm, 2.5 * cm, 2.5 * cm, 2.5 * cm, 5 * cm])
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), "#dddddd"),
            ("GRID", (0, 0), (-1, -1), 0.5, "#999999"),
            ("FONTSIZE", (0, 0), (-1, -1), 7),
        ]))
        story.append(table)
    else:
        story.append(Paragraph("No alerts recorded in this period.", styles["Normal"]))

    doc.build(story)
    buffer.seek(0)
    return buffer.read()
