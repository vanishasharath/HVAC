import jsPDF from 'jspdf'
import autoTable from 'jspdf-autotable'

export function exportDashboardPdf(readings, alerts) {
  const doc = new jsPDF()

  doc.setFontSize(16)
  doc.text('HVAC Compliance Report', 14, 18)

  doc.setFontSize(10)
  doc.text(`Generated: ${new Date().toLocaleString()}`, 14, 26)

  autoTable(doc, {
    startY: 32,
    head: [['Time', 'Gas (ppm)', 'Temperature (°C)']],
    body: readings.map((r) => [r.time, r.gasPpm, r.temperature]),
  })

  autoTable(doc, {
    startY: doc.lastAutoTable.finalY + 10,
    head: [['Severity', 'Unit', 'Message']],
    body: alerts.map((a) => [a.severity, a.unitId, a.message]),
  })

  doc.save(`hvac-report-${Date.now()}.pdf`)
}