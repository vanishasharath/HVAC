import { useState, useEffect, useRef } from 'react'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000'

function SimulatorControlPanel({ hvacId = 'HVAC_SIM_01', onSimulatorStep }) {
  const [isOpen, setIsOpen] = useState(true)
  const [sensorLocation, setSensorLocation] = useState('suction_line')
  const [humidityContext, setHumidityContext] = useState('stable')
  const [leakRate, setLeakRate] = useState('slow')
  const [demoPacing, setDemoPacing] = useState('slow') // 'slow' (3.2s), 'normal' (1.8s), 'fast' (0.9s)
  const [stepCount, setStepCount] = useState(0)
  const [isRunning, setIsRunning] = useState(false)
  const [loading, setLoading] = useState(false)
  const [lastStepMeta, setLastStepMeta] = useState(null)
  const [lastCritEst, setLastCritEst] = useState(null)
  const [repairSuccessMsg, setRepairSuccessMsg] = useState('')

  const autoRunTimer = useRef(null)

  const locations = [
    {
      id: 'suction_line',
      name: 'Suction Line (Low-Side / Evap Outlet)',
      desc: '165 psi baseline. Suction pressure drops progressively towards ≤ 105 psi as charge depletes.',
    },
    {
      id: 'discharge_line',
      name: 'Discharge Line (High-Side / Compressor Exit)',
      desc: '395 psi baseline. Initial thermal superheat surge (+18 psi), followed by head pressure decline.',
    },
    {
      id: 'liquid_line',
      name: 'Liquid Line (Condenser Exit)',
      desc: '375 psi baseline. Subcooling loss creates vapor bubbles and pressure flutter.',
    },
    {
      id: 'indoor_ambient_plenum',
      name: 'Indoor Supply Duct / Plenum',
      desc: '14.7 psi (101.3 kPa). Atmospheric pressure stays steady while gas ppm escalates.',
    },
  ]

  const humidityModes = [
    { id: 'stable', name: 'Stable Ambient (55%)', tag: 'Standard Climate' },
    { id: 'humid', name: 'Humid Monsoon (75%)', tag: 'High Ambient' },
    { id: 'dry', name: 'Dry Winter (35%)', tag: 'Low Ambient' },
    { id: 'fluctuating', name: 'Diurnal Drift', tag: 'Cyclic Weather' },
    { id: 'random_walk', name: 'Stochastic Walk', tag: 'Brownian Context' },
  ]

  const leakRates = [
    {
      id: 'ultra_slow',
      name: 'Ultra-Slow Micro-Leak (~36 - 48 Hours to Critical)',
      tag: 'Best for Slow Presentation',
    },
    {
      id: 'slow',
      name: 'Slow Pinhole Leak (~24 - 36 Hours to Critical)',
      tag: 'Real-World Standard (Recommended)',
    },
    {
      id: 'medium',
      name: 'Medium Flare Joint Leak (~12 - 18 Hours to Critical)',
      tag: 'Vibration Loosening',
    },
    {
      id: 'fast',
      name: 'Fast Line Rupture (~4 - 6 Hours to Critical)',
      tag: 'Rapid Starvation',
    },
  ]

  const handleStep = async (isLeak = true, customStepIncrement = 1) => {
    setLoading(true)
    setRepairSuccessMsg('')
    const nextStep = isLeak ? stepCount + customStepIncrement : 0
    try {
      const response = await fetch(`${API_BASE_URL}/api/v1/simulator/step`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          hvac_id: hvacId,
          sensor_location: sensorLocation,
          humidity_context: humidityContext,
          leak_rate: leakRate,
          step: nextStep,
          is_leak: isLeak,
        }),
      })

      const data = await response.json()
      if (response.ok) {
        if (isLeak) setStepCount(nextStep)
        setLastStepMeta(data.location_metadata)
        if (data.critical_estimation) {
          setLastCritEst(data.critical_estimation)
        }
        if (onSimulatorStep) onSimulatorStep(data)
      } else {
        console.error('Simulator step error:', data)
      }
    } catch (err) {
      console.error('Failed to trigger simulator step:', err)
    } finally {
      setLoading(false)
    }
  }

  // Technician Maintenance / Repair Action
  const handleRepair = async () => {
    setLoading(true)
    setIsRunning(false)
    if (autoRunTimer.current) clearInterval(autoRunTimer.current)
    setStepCount(0)

    try {
      const response = await fetch(`${API_BASE_URL}/api/v1/simulator/repair`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          hvac_id: hvacId,
          sensor_location: sensorLocation,
          humidity_context: humidityContext,
        }),
      })

      const data = await response.json()
      if (response.ok) {
        setRepairSuccessMsg('✓ Leak successfully repaired! Refrigerant recharged, supply cooling restored to 7.0°C nominal. Critical condition averted.')
        setLastStepMeta(data.location_metadata)
        if (data.critical_estimation) {
          setLastCritEst(data.critical_estimation)
        }
        if (onSimulatorStep) onSimulatorStep(data)
      }
    } catch (err) {
      console.error('Failed to simulate repair:', err)
    } finally {
      setLoading(false)
    }
  }

  const handleReset = async () => {
    setIsRunning(false)
    if (autoRunTimer.current) clearInterval(autoRunTimer.current)
    setStepCount(0)
    setLastStepMeta(null)
    setLastCritEst(null)
    setRepairSuccessMsg('')

    try {
      await fetch(`${API_BASE_URL}/api/v1/simulator/reset/${hvacId}`, {
        method: 'POST',
      })
      await handleStep(false)
    } catch (err) {
      console.error('Failed to reset simulator state:', err)
    }
  }

  // Toggle continuous simulation loop
  const toggleAutoSim = () => {
    if (isRunning) {
      setIsRunning(false)
      if (autoRunTimer.current) clearInterval(autoRunTimer.current)
    } else {
      setRepairSuccessMsg('')
      setIsRunning(true)
    }
  }

  // Simulation timer with selectable pacing
  useEffect(() => {
    if (isRunning) {
      const paceMs = demoPacing === 'slow' ? 3200 : demoPacing === 'fast' ? 900 : 1800
      autoRunTimer.current = setInterval(() => {
        handleStep(true, 1)
      }, paceMs)
    } else {
      if (autoRunTimer.current) clearInterval(autoRunTimer.current)
    }
    return () => {
      if (autoRunTimer.current) clearInterval(autoRunTimer.current)
    }
  }, [isRunning, stepCount, sensorLocation, humidityContext, leakRate, demoPacing])

  const simulatedOperatingHours = (stepCount * 0.25).toFixed(1)
  const isCritical = lastCritEst?.critical_reached === true
  const isRepairWindowActive = stepCount > 0 && !isCritical && lastCritEst?.is_repaired !== true

  return (
    <div className="bg-white rounded-2xl shadow-lg border border-slate-200 p-5 mb-5 transition-all">
      {/* Header */}
      <div className="flex justify-between items-center cursor-pointer" onClick={() => setIsOpen(!isOpen)}>
        <div className="flex items-center gap-2.5">
          <span className="text-xl">🎛️</span>
          <div>
            <div className="flex items-center gap-2">
              <h3 className="text-base font-bold text-slate-800">
                Live HVAC Simulator (Slow Leakage & Real-World Hours Scale)
              </h3>
              {isRepairWindowActive && (
                <span className="px-2 py-0.5 text-[10px] font-extrabold uppercase rounded-full bg-emerald-100 text-emerald-800 border border-emerald-300 animate-pulse">
                  Repair Window Open
                </span>
              )}
              {isCritical && (
                <span className="px-2 py-0.5 text-[10px] font-extrabold uppercase rounded-full bg-red-100 text-red-800 border border-red-300">
                  Critical Breach
                </span>
              )}
            </div>
            <p className="text-xs text-slate-500 mt-0.5">
              Simulates slow pinhole micro-leaks unfolding over realistic HVAC hours. Demonstrates early warning detection, AI predictive modeling, and technician maintenance before reaching critical thresholds.
            </p>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <span className="text-xs font-semibold px-2.5 py-1 rounded bg-blue-50 text-blue-700 border border-blue-200">
            Simulated HVAC Time: <strong className="text-blue-900">{simulatedOperatingHours} Hours</strong> (Step {stepCount})
          </span>
          <button
            type="button"
            className="text-slate-400 hover:text-slate-600 text-sm font-bold"
          >
            {isOpen ? '▲ Hide' : '▼ Expand'}
          </button>
        </div>
      </div>

      {/* Repair Success Notification Banner */}
      {repairSuccessMsg && (
        <div className="mt-3 p-3 bg-emerald-50 border border-emerald-300 rounded-xl flex items-center justify-between text-emerald-800 text-xs font-semibold animate-fadeIn shadow-sm">
          <div className="flex items-center gap-2">
            <span className="text-base">🛠️</span>
            <span>{repairSuccessMsg}</span>
          </div>
          <button
            onClick={() => setRepairSuccessMsg('')}
            className="text-emerald-600 hover:text-emerald-900 font-bold ml-2 text-sm"
          >
            ✕
          </button>
        </div>
      )}

      {/* Actionable Repair Window Callout */}
      {isRepairWindowActive && !repairSuccessMsg && (
        <div className="mt-3 p-3 bg-gradient-to-r from-emerald-50 to-teal-50 border border-emerald-300 rounded-xl flex items-center justify-between text-emerald-900 text-xs font-medium shadow-sm animate-fadeIn">
          <div className="flex items-center gap-2">
            <span className="text-lg">⏱️</span>
            <div>
              <strong className="text-emerald-800 font-bold">Actionable Repair Window Active (T+{simulatedOperatingHours}h): </strong>
              <span>
                Refrigerant drift detected early. Service the unit now with the green <strong>"Repair / Service Leak"</strong> button to restore full charge and prevent critical cooling loss.
              </span>
            </div>
          </div>
          <button
            onClick={handleRepair}
            disabled={loading}
            className="px-3 py-1 bg-emerald-600 hover:bg-emerald-700 text-white rounded-lg font-bold text-xs shadow-sm transition-all whitespace-nowrap ml-3"
          >
            🔧 Repair Unit Now
          </button>
        </div>
      )}

      {isOpen && (
        <div className="mt-4 pt-4 border-t border-slate-100">
          <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-4">
            {/* Sensor Location Selector */}
            <div>
              <label className="block text-xs font-semibold text-slate-700 mb-1">
                📍 Pressure Sensor Location:
              </label>
              <select
                value={sensorLocation}
                onChange={(e) => setSensorLocation(e.target.value)}
                className="w-full text-xs bg-slate-50 border border-slate-300 rounded-lg p-2 font-medium text-slate-800 focus:ring-2 focus:ring-blue-500"
              >
                {locations.map((loc) => (
                  <option key={loc.id} value={loc.id}>
                    {loc.name}
                  </option>
                ))}
              </select>
              <p className="text-[11px] text-slate-500 mt-1 italic">
                {locations.find((l) => l.id === sensorLocation)?.desc}
              </p>
            </div>

            {/* Contextual Humidity Selector */}
            <div>
              <label className="block text-xs font-semibold text-slate-700 mb-1">
                💧 Contextual Humidity Mode:
              </label>
              <select
                value={humidityContext}
                onChange={(e) => setHumidityContext(e.target.value)}
                className="w-full text-xs bg-slate-50 border border-slate-300 rounded-lg p-2 font-medium text-slate-800 focus:ring-2 focus:ring-blue-500"
              >
                {humidityModes.map((h) => (
                  <option key={h.id} value={h.id}>
                    {h.name} — {h.tag}
                  </option>
                ))}
              </select>
              <p className="text-[11px] text-slate-500 mt-1">
                Humidity is an independent ambient context, decoupled from leak progression.
              </p>
            </div>

            {/* Leak Progression Rate */}
            <div>
              <label className="block text-xs font-semibold text-slate-700 mb-1">
                ⚡ Leak Progression Rate (Hours Timeline):
              </label>
              <select
                value={leakRate}
                onChange={(e) => setLeakRate(e.target.value)}
                className="w-full text-xs bg-slate-50 border border-slate-300 rounded-lg p-2 font-medium text-slate-800 focus:ring-2 focus:ring-blue-500"
              >
                {leakRates.map((lr) => (
                  <option key={lr.id} value={lr.id}>
                    {lr.name}
                  </option>
                ))}
              </select>
              <p className="text-[11px] text-slate-500 mt-1">
                Calibrated to physical HVAC hours. 1 step = 15 min operating progression.
              </p>
            </div>

            {/* Demonstration Speed / Pacing */}
            <div>
              <label className="block text-xs font-semibold text-slate-700 mb-1">
                ⏱️ Demonstration Pacing (Speed):
              </label>
              <select
                value={demoPacing}
                onChange={(e) => setDemoPacing(e.target.value)}
                className="w-full text-xs bg-slate-50 border border-slate-300 rounded-lg p-2 font-medium text-slate-800 focus:ring-2 focus:ring-blue-500"
              >
                <option value="slow">Slow Pace (3.2s / step — Calm, easy to demonstrate)</option>
                <option value="normal">Normal Demo (1.8s / step)</option>
                <option value="fast">Rapid Preview (0.9s / step)</option>
              </select>
              <p className="text-[11px] text-slate-500 mt-1">
                Controls continuous auto-sim interval to allow plenty of demonstration time.
              </p>
            </div>
          </div>

          {/* Action Buttons */}
          <div className="flex flex-wrap items-center justify-between gap-3 pt-3 border-t border-slate-100">
            <div className="flex flex-wrap items-center gap-2">
              <button
                onClick={() => handleStep(true, 1)}
                disabled={loading || isRunning}
                className="px-3 py-1.5 text-xs font-bold text-white bg-red-600 hover:bg-red-700 rounded-lg transition-colors shadow-sm disabled:opacity-50"
                title="Advance simulation by 1 step (+15 minutes)"
              >
                + Step (+15m)
              </button>

              <button
                onClick={() => handleStep(true, 4)}
                disabled={loading || isRunning}
                className="px-3 py-1.5 text-xs font-bold text-amber-900 bg-amber-100 hover:bg-amber-200 border border-amber-300 rounded-lg transition-colors shadow-sm disabled:opacity-50"
                title="Advance simulation by 4 steps (+1.0 hour of HVAC operating time)"
              >
                + Advance (+1 Hour)
              </button>

              <button
                onClick={toggleAutoSim}
                className={`px-4 py-1.5 text-xs font-bold text-white rounded-lg transition-colors shadow-sm ${
                  isRunning
                    ? 'bg-amber-600 hover:bg-amber-700 animate-pulse'
                    : 'bg-blue-600 hover:bg-blue-700'
                }`}
              >
                {isRunning ? '⏹ Stop Auto-Sim' : `▶ Continuous Demo (${demoPacing === 'slow' ? 'Slow 3.2s' : demoPacing === 'normal' ? '1.8s' : '0.9s'})`}
              </button>

              {/* Maintenance / Repair Button */}
              <button
                onClick={handleRepair}
                disabled={loading}
                className={`px-4 py-1.5 text-xs font-bold text-white rounded-lg transition-all shadow-md flex items-center gap-1.5 ${
                  isRepairWindowActive
                    ? 'bg-emerald-600 hover:bg-emerald-700 ring-2 ring-emerald-400 ring-offset-1 animate-pulse'
                    : 'bg-emerald-600 hover:bg-emerald-700'
                }`}
                title="Simulate technician repairing the leak and recharging refrigerant before critical limit is breached"
              >
                <span>🔧</span>
                <span>Repair / Service Leak (Avert Critical)</span>
              </button>

              <button
                onClick={() => handleStep(false)}
                disabled={loading || isRunning}
                className="px-3 py-1.5 text-xs font-semibold text-slate-700 bg-slate-100 hover:bg-slate-200 rounded-lg transition-colors disabled:opacity-50"
              >
                ✓ Healthy Step
              </button>
            </div>

            <div className="flex items-center gap-3">
              {lastStepMeta && (
                <span className="text-xs text-slate-500">
                  Circuit Press: <strong className="text-slate-800">{lastStepMeta.location_pressure} {lastStepMeta.location_unit}</strong>
                </span>
              )}
              <button
                onClick={handleReset}
                className="px-3 py-1.5 text-xs font-semibold text-slate-600 hover:text-red-600 hover:bg-red-50 rounded-lg transition-colors border border-slate-200"
              >
                ↺ Reset State
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default SimulatorControlPanel

