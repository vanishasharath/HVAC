function AICriticalPredictor({ criticalEstimation, aiResult, lastReading }) {
  const crit = criticalEstimation || lastReading?.critical_estimation || aiResult?.critical_estimation || {}
  const status = crit.status || 'HEALTHY_STABLE'
  const isCritical = crit.critical_reached || status === 'CRITICAL_REACHED'
  const isProgressing = status === 'LEAK_PROGRESSING'
  const isRepaired = crit.is_repaired || lastReading?.is_repaired || false

  const progressPct = crit.progress_to_critical_pct != null ? Number(crit.progress_to_critical_pct) : 0
  const ettcFormatted = crit.time_to_critical_formatted || '> 24 Hours (Normal Operation)'
  
  // Elapsed operating time in hours
  const elapsedHours = crit.elapsed_time_hours != null
    ? `${crit.elapsed_time_hours.toFixed(1)} Hours`
    : crit.elapsed_time_seconds != null && crit.elapsed_time_seconds > 0
    ? `${(crit.elapsed_time_seconds / 3600.0).toFixed(1)} Hours`
    : '0.0 Hours (Nominal)'

  const projectedCriticalTime = crit.projected_critical_time || (
    isRepaired
      ? 'Critical Condition Averted — Unit Serviced'
      : isCritical
      ? 'Critical Limit Already Exceeded'
      : 'No Critical Breach Expected (Nominal)'
  )

  const primaryDriver = crit.primary_driver_display || 'Healthy Baseline (Normal Operation)'

  const trends = crit.trends || {}
  const gasRateHr = trends.gas_ppm_per_hour != null
    ? trends.gas_ppm_per_hour
    : (trends.gas_ppm_per_min ? trends.gas_ppm_per_min * 60.0 : 0.0)
  const tempRateHr = trends.temp_per_hour != null
    ? trends.temp_per_hour
    : (trends.temp_per_min ? trends.temp_per_min * 60.0 : 0.0)
  const pressRateHr = trends.pressure_per_hour != null
    ? trends.pressure_per_hour
    : (trends.pressure_per_min ? trends.pressure_per_min * 60.0 : 0.0)
  const humRate = trends.humidity_per_min != null ? trends.humidity_per_min : 0

  const rfSeverity = isRepaired ? 'Low' : (aiResult?.severity || crit.rf_severity || 'Low')
  const rfConfidence = aiResult?.severity_confidence != null ? Math.round(aiResult.severity_confidence * 100) : 99
  const lstm24 = isRepaired ? '0.0' : (aiResult?.lstm_prob_24hr != null ? (aiResult.lstm_prob_24hr * 100).toFixed(1) : '0.0')
  const lstm48 = isRepaired ? '0.0' : (aiResult?.lstm_prob_48hr != null ? (aiResult.lstm_prob_48hr * 100).toFixed(1) : '0.0')

  const getStatusBadge = () => {
    if (isRepaired) {
      return (
        <span className="px-3 py-1 text-xs font-bold rounded-full bg-emerald-500 text-white shadow-sm flex items-center gap-1.5 animate-pulse">
          <span>✓</span>
          <span>SYSTEM SERVICED & REPAIRED</span>
        </span>
      )
    }
    if (isCritical) {
      return (
        <span className="px-3 py-1 text-xs font-bold rounded-full bg-red-600 text-white animate-pulse shadow-sm">
          CRITICAL CONDITION REACHED
        </span>
      )
    }
    if (isProgressing) {
      return (
        <span className="px-3 py-1 text-xs font-bold rounded-full bg-amber-500 text-white shadow-sm flex items-center gap-1.5">
          <span className="animate-ping w-2 h-2 rounded-full bg-amber-200"></span>
          <span>SLOW LEAK PROGRESSING (HOURS ESTIMATION)</span>
        </span>
      )
    }
    return (
      <span className="px-3 py-1 text-xs font-bold rounded-full bg-emerald-600 text-white shadow-sm">
        HEALTHY / STABLE (NORMAL OPERATING RANGE)
      </span>
    )
  }

  const getProgressBarColor = () => {
    if (isRepaired) return 'from-emerald-400 to-teal-500'
    if (progressPct >= 80) return 'from-amber-500 to-red-600'
    if (progressPct >= 40) return 'from-yellow-400 to-amber-500'
    return 'from-emerald-400 to-teal-500'
  }

  return (
    <div className="bg-gradient-to-br from-slate-900 to-slate-800 text-white rounded-2xl shadow-xl p-5 mb-5 border border-slate-700/60">
      {/* Top Banner */}
      <div className="flex flex-wrap justify-between items-center gap-3 pb-4 border-b border-slate-700/60">
        <div>
          <div className="flex items-center gap-2">
            <span className="text-xl">⏱️</span>
            <h2 className="text-lg font-bold text-white tracking-wide">
              AI Critical Condition & Trend Estimation (Hours Timeline)
            </h2>
          </div>
          <p className="text-xs text-slate-300 mt-0.5">
            Predictive physical extrapolation based on elapsed operating time and temporal rate-of-change trends.
          </p>
        </div>
        <div>{getStatusBadge()}</div>
      </div>

      {/* Technician Repair Success Notification */}
      {isRepaired && (
        <div className="mt-4 p-3.5 bg-emerald-950/80 border border-emerald-500/70 rounded-xl flex items-center justify-between text-emerald-200 text-xs shadow-lg animate-fadeIn">
          <div className="flex items-center gap-2.5">
            <span className="text-xl">🛠️</span>
            <div>
              <p className="font-bold text-emerald-300 text-sm">
                Technician Maintenance Complete: Critical Condition Averted!
              </p>
              <p className="text-emerald-400/90 text-xs mt-0.5">
                Refrigerant circuit sealed, full charge restored (165 psi), supply cooling restored to 7.0°C nominal. All active alerts resolved.
              </p>
            </div>
          </div>
          <span className="bg-emerald-500/20 text-emerald-300 text-[11px] font-bold px-2.5 py-1 rounded-full border border-emerald-500/30 whitespace-nowrap">
            SAFE / NOMINAL
          </span>
        </div>
      )}

      {/* Actionable Early Repair Window in Real-World Hours */}
      {isProgressing && !isCritical && !isRepaired && (
        <div className="mt-4 p-3 bg-gradient-to-r from-blue-950/80 to-slate-900 border border-blue-500/60 rounded-xl flex items-center justify-between text-blue-200 text-xs shadow-md animate-fadeIn">
          <div className="flex items-center gap-2.5">
            <span className="text-lg">🛡️</span>
            <div>
              <p className="font-bold text-blue-300 text-xs">
                Real-World Actionable Repair Window: Maintenance Recommended
              </p>
              <p className="text-slate-300 text-[11px] mt-0.5">
                Early micro-leak detected in slow hours timeline. Servicing the HVAC unit now prevents evaporator freeze-up, compressor starvation, and critical cooling failure.
              </p>
            </div>
          </div>
          <span className="bg-blue-500/20 text-blue-300 text-[11px] font-bold px-2.5 py-1 rounded-full border border-blue-500/30 whitespace-nowrap">
            REPAIR WINDOW OPEN
          </span>
        </div>
      )}

      {/* Main Metric Spotlight */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 my-4">
        {/* Estimated Time To Critical */}
        <div className="bg-slate-800/80 rounded-xl p-4 border border-slate-700/80 flex flex-col justify-between">
          <div>
            <div className="flex justify-between items-center">
              <p className="text-xs uppercase font-semibold text-slate-400 tracking-wider">
                Estimated Time to Critical (ETTC)
              </p>
              {isProgressing && (
                <span className="text-[10px] font-bold px-1.5 py-0.5 rounded bg-amber-500/20 text-amber-300 border border-amber-500/30">
                  HOURS TIMELINE
                </span>
              )}
            </div>
            <p className={`text-2xl font-black mt-1.5 ${
              isCritical ? 'text-red-400 animate-pulse' :
              isRepaired ? 'text-emerald-400' :
              isProgressing ? 'text-amber-400' : 'text-emerald-400'
            }`}>
              {ettcFormatted}
            </p>

            {/* Projected Breach Clock Time */}
            <div className="mt-2 text-xs flex items-center gap-1.5 bg-slate-900/60 p-2 rounded-lg border border-slate-700/50">
              <span className="text-slate-400">🕒 Projected Breach:</span>
              <strong className={
                isCritical ? 'text-red-300 font-bold' :
                isRepaired ? 'text-emerald-300 font-bold' :
                'text-amber-200 font-bold'
              }>
                {projectedCriticalTime}
              </strong>
            </div>
          </div>
          <p className="text-xs text-slate-400 mt-2.5 pt-2 border-t border-slate-700/50">
            Elapsed Operating Time: <strong className="text-slate-200">{elapsedHours}</strong>
          </p>
        </div>

        {/* Primary Critical Driver */}
        <div className="bg-slate-800/80 rounded-xl p-4 border border-slate-700/80 flex flex-col justify-between">
          <div>
            <p className="text-xs uppercase font-semibold text-slate-400 tracking-wider">
              Primary Governing Driver
            </p>
            <p className="text-sm font-bold text-slate-100 mt-1 line-clamp-2" title={primaryDriver}>
              {primaryDriver}
            </p>
          </div>
          <p className="text-xs text-slate-400 mt-2">
            Defined Limits: <span className="text-slate-300">Gas ≥ 400 ppm | Temp ≥ 22°C | Press ≤ 105 psi</span>
          </p>
        </div>

        {/* AI Model Multi-Stage Output */}
        <div className="bg-slate-800/80 rounded-xl p-4 border border-slate-700/80 flex flex-col justify-between">
          <div>
            <p className="text-xs uppercase font-semibold text-slate-400 tracking-wider">
              AI Severity Classifier
            </p>
            <div className="flex items-center justify-between mt-1">
              <span className={`text-lg font-bold ${
                isRepaired ? 'text-emerald-400' :
                rfSeverity === 'Critical' ? 'text-red-400' :
                rfSeverity === 'High' ? 'text-orange-400' :
                rfSeverity === 'Medium' ? 'text-amber-400' : 'text-emerald-400'
              }`}>
                {rfSeverity}
              </span>
              <span className="text-xs text-slate-400">
                Confidence: <strong className="text-slate-200">{rfConfidence}%</strong>
              </span>
            </div>
          </div>
          <div className="flex gap-3 text-[11px] text-slate-400 mt-2 pt-1.5 border-t border-slate-700/50">
            <span>LSTM 24h: <strong className="text-slate-300">{lstm24}%</strong></span>
            <span>LSTM 48h: <strong className="text-slate-300">{lstm48}%</strong></span>
          </div>
        </div>
      </div>

      {/* Progress Toward Defined Simulated Critical Condition */}
      <div className="mb-4 bg-slate-800/50 p-3 rounded-xl border border-slate-700/40">
        <div className="flex justify-between items-center text-xs mb-1.5 font-medium">
          <span className="text-slate-300">
            Critical Threshold Progression: <strong className="text-slate-100">{primaryDriver}</strong>
          </span>
          <span className="font-bold text-slate-200">{progressPct.toFixed(1)}%</span>
        </div>
        <div className="w-full bg-slate-700/80 rounded-full h-3 overflow-hidden p-0.5">
          <div
            className={`h-full rounded-full transition-all duration-500 bg-gradient-to-r ${getProgressBarColor()}`}
            style={{ width: `${Math.min(100, Math.max(0, progressPct))}%` }}
          />
        </div>
      </div>

      {/* Multi-Parameter Trend Rates of Change (Per Hour & Ambient Context) */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs">
        <div className="bg-slate-950/40 p-2.5 rounded-lg border border-slate-800">
          <span className="text-slate-400 block mb-0.5">Refrigerant Leak Rate</span>
          <span className={`font-semibold ${gasRateHr > 1.0 ? 'text-red-400' : 'text-slate-200'}`}>
            {gasRateHr >= 0 ? `+${gasRateHr.toFixed(1)}` : gasRateHr.toFixed(1)} ppm/hr
          </span>
        </div>

        <div className="bg-slate-950/40 p-2.5 rounded-lg border border-slate-800">
          <span className="text-slate-400 block mb-0.5">Supply-Air Warming Rate</span>
          <span className={`font-semibold ${tempRateHr > 0.1 ? 'text-amber-400' : 'text-slate-200'}`}>
            {tempRateHr >= 0 ? `+${tempRateHr.toFixed(2)}` : tempRateHr.toFixed(2)} °C/hr
          </span>
        </div>

        <div className="bg-slate-950/40 p-2.5 rounded-lg border border-slate-800">
          <span className="text-slate-400 block mb-0.5">Circuit Pressure Rate</span>
          <span className={`font-semibold ${pressRateHr < -0.1 ? 'text-sky-400' : 'text-slate-200'}`}>
            {pressRateHr >= 0 ? `+${pressRateHr.toFixed(2)}` : pressRateHr.toFixed(2)} psi/hr
          </span>
        </div>

        <div className="bg-slate-950/40 p-2.5 rounded-lg border border-slate-800">
          <span className="text-slate-400 block mb-0.5">Contextual Humidity</span>
          <span className="font-semibold text-slate-300">
            {humRate >= 0 ? `+${(humRate * 60.0).toFixed(1)}` : (humRate * 60.0).toFixed(1)} %/hr (ambient)
          </span>
        </div>
      </div>
    </div>
  )
}

export default AICriticalPredictor
