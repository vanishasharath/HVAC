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

          return (
            <div
              key={alert.id}
              className={`border-l-4 p-2 rounded ${
                severityStyles[severity] ||
                'bg-slate-100 text-slate-800 border-slate-400'
              }`}
            >
              <p className="text-sm font-medium">
                {severity} — Unit {alert.unitId}
              </p>

              <p className="text-xs">
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