const severityStyles = {
  WARNING: 'bg-yellow-100 text-yellow-800 border-yellow-400',
  PREDICTIVE: 'bg-orange-100 text-orange-800 border-orange-400',
  CRITICAL: 'bg-red-100 text-red-800 border-red-400',
}

function AlertPanel({ alerts }) {
  if (alerts.length === 0) {
    return (
      <div className="bg-white rounded-xl shadow p-4">
        <h3 className="text-sm font-semibold text-slate-600 mb-2">
          Active Alerts
        </h3>
        <p className="text-sm text-slate-400">
          No alerts right now.
        </p>
      </div>
    )
  }

  return (
    <div className="bg-white rounded-xl shadow p-4">
      <h3 className="text-sm font-semibold text-slate-600 mb-2">
        Active Alerts
      </h3>

      <div className="space-y-2">
        {alerts.map((alert) => {
          const severity = alert.severity?.toUpperCase() || 'WARNING'

          const isTemp = alert.alertType === 'temperature' || alert.message?.toLowerCase().includes('temperature')
          const isGas = alert.alertType === 'gas' || alert.message?.toLowerCase().includes('gas')

          return (
            <div
              key={alert.id}
              className={`border-l-4 p-2.5 rounded ${
                severityStyles[severity] ||
                'bg-slate-100 text-slate-800 border-slate-400'
              }`}
            >
              <div className="flex items-center justify-between mb-0.5">
                <p className="text-sm font-semibold">
                  {severity} — Unit {alert.unitId}
                </p>
                {isTemp && (
                  <span className="text-[10px] uppercase font-bold px-1.5 py-0.5 rounded bg-amber-200/70 text-amber-900 border border-amber-300">
                    🌡️ Temperature
                  </span>
                )}
                {isGas && (
                  <span className="text-[10px] uppercase font-bold px-1.5 py-0.5 rounded bg-red-200/70 text-red-900 border border-red-300">
                    ⚠️ Gas Leak
                  </span>
                )}
              </div>

              <p className="text-xs font-medium">
                {alert.message}
              </p>
            </div>
          )
        })}
      </div>
    </div>
  )
}

export default AlertPanel