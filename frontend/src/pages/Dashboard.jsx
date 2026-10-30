import { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import SensorChart from '../components/SensorChart'
import AlertPanel from '../components/AlertPanel'
import AICriticalPredictor from '../components/AICriticalPredictor'
import { exportDashboardPdf } from '../utils/exportPdf'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000'
const WS_BASE_URL = API_BASE_URL.replace(/^http/, 'ws')

function Dashboard() {
  const { user, token, logout } = useAuth()

  const isTechnician = user?.role === 'TECHNICIAN'
  const isAdmin = user?.role === 'ADMIN'

  const [selectedUnit, setSelectedUnit] = useState('HVAC_TEST_01')
  const [readings, setReadings] = useState([])
  const [alerts, setAlerts] = useState([])
  const [connectionStatus, setConnectionStatus] = useState('Connecting...')
  const [lastReading, setLastReading] = useState(null)
  const [criticalEstimation, setCriticalEstimation] = useState(null)
  const [aiResult, setAiResult] = useState(null)

  // Repair operation states
  const [isRepairing, setIsRepairing] = useState(false)
  const [repairNotice, setRepairNotice] = useState(null)
  const [simStepLoading, setSimStepLoading] = useState(false)

  // Fetch active alerts for the selected HVAC unit
  useEffect(() => {
    if (!token) return

    const fetchAlerts = async () => {
      try {
        const response = await fetch(
          `${API_BASE_URL}/api/v1/alerts?hvac_id=${selectedUnit}&status=ACTIVE`,
          {
            headers: {
              Authorization: `Bearer ${token}`,
            },
          }
        )

        const result = await response.json()
        if (!response.ok) {
          console.error('Failed to fetch alerts:', result)
          return
        }

        const backendAlerts = result.data || []
        const formattedAlerts = backendAlerts.map((alert) => ({
          id: alert.id || alert._id,
          severity: alert.severity,
          unitId: alert.hvac_id || selectedUnit,
          message:
            alert.message ||
            alert.description ||
            `Alert detected for ${selectedUnit}`,
        }))

        setAlerts(formattedAlerts)
      } catch (error) {
        console.error('Error fetching alerts:', error)
      }
    }

    fetchAlerts()
    const interval = setInterval(fetchAlerts, 10000)
    return () => clearInterval(interval)
  }, [token, selectedUnit])

  // Connect to live WebSocket stream for selected HVAC unit
  useEffect(() => {
    let websocket
    let reconnectTimer
    let stopped = false

    const connect = () => {
      if (stopped) return

      setConnectionStatus('Connecting...')

      websocket = new WebSocket(`${WS_BASE_URL}/ws/hvac/${selectedUnit}`)

      websocket.onopen = () => {
        setConnectionStatus('Live')
      }

      websocket.onmessage = (event) => {
        try {
          const message = JSON.parse(event.data)

          // Handle real-time alert creation
          if (message.event === 'alert_created') {
            const alertData = message.data
            if (alertData && (alertData.hvac_id === selectedUnit || !alertData.hvac_id)) {
              const alertId = alertData.id || alertData._id
              const formattedAlert = {
                id: alertId,
                severity: alertData.severity || 'WARNING',
                unitId: alertData.hvac_id || selectedUnit,
                message:
                  alertData.message ||
                  alertData.description ||
                  `Alert detected for ${selectedUnit}`,
              }
              setAlerts((prev) => {
                if (prev.some((a) => a.id === alertId)) return prev
                return [formattedAlert, ...prev]
              })
            }
            return
          }

          // Handle real-time alert resolution
          if (message.event === 'alert_resolved') {
            const resolvedId = message.data?.id || message.data?._id
            if (resolvedId) {
              setAlerts((prev) => prev.filter((a) => a.id !== resolvedId))
            }
            return
          }

          if (message.event !== 'sensor_reading') return
          if (message.hvac_id && message.hvac_id !== selectedUnit) return

          const sensorData = message.data || {}
          const sensors = sensorData.sensors || {}

          const timestamp = sensorData.timestamp
            ? new Date(sensorData.timestamp)
            : new Date()

          const newReading = {
            time: timestamp.toLocaleTimeString().slice(0, 8),
            gasPpm: sensors.gas_ppm != null ? Number(sensors.gas_ppm) : 0,
            temperature: sensors.temperature != null ? Number(sensors.temperature) : 0,
            pressure: sensors.pressure != null ? Number(sensors.pressure) : 0,
            current: sensors.compressor_current != null ? Number(sensors.compressor_current) : 0,
          }

          setLastReading(sensorData)

          if (sensorData.critical_estimation) {
            setCriticalEstimation(sensorData.critical_estimation)
          }
          if (sensorData.ai_result) {
            setAiResult(sensorData.ai_result)
          }

          // If a repair event was broadcast, update the technician repair notice across all users
          if (sensorData.is_repair) {
            const tech = sensorData.repaired_by || 'Field Technician'
            setRepairNotice({
              technician: tech,
              time: timestamp.toLocaleTimeString(),
              message: `Unit ${selectedUnit} was serviced & repaired by Technician ${tech}. Refrigerant recharge certified and safety baseline restored.`,
            })
            // Clear any lingering active alerts
            setAlerts([])
          }

          setReadings((prev) => [
            ...prev.slice(-29),
            newReading,
          ])
          setConnectionStatus('Live')
        } catch (error) {
          console.error('Failed to process WebSocket message:', error)
        }
      }

      websocket.onerror = (error) => {
        console.error('WebSocket error:', error)
        setConnectionStatus('Connection Error')
      }

      websocket.onclose = () => {
        if (stopped) return
        setConnectionStatus('Disconnected')
        reconnectTimer = setTimeout(connect, 3000)
      }
    }

    connect()

    return () => {
      stopped = true
      clearTimeout(reconnectTimer)
      if (websocket) {
        websocket.onclose = null
        websocket.close()
      }
    }
  }, [selectedUnit])

  const sensors = lastReading?.sensors || {}
  const gasVal = sensors.gas_ppm != null ? Number(sensors.gas_ppm) : 0
  const tempVal = sensors.temperature != null ? Number(sensors.temperature) : 0
  const isGasAlert = Boolean(lastReading?.gas_alert === true || gasVal >= 50.0)
  const isTempAlert = Boolean(lastReading?.temperature_alert === true || tempVal >= 35.0)
  const isEdgeAlert = Boolean(lastReading?.gas_alert === true || lastReading?.event === 'CRITICAL' || lastReading?.event === 'GAS ALERT')

  // AI & Critical Condition Evaluation
  const crit = criticalEstimation || lastReading?.critical_estimation || aiResult?.critical_estimation || {}
  const status = crit.status || 'HEALTHY_STABLE'
  const isRepaired = Boolean(crit.is_repaired || lastReading?.is_repair || status === 'REPAIRED')

  // A condition is strictly CRITICAL ONLY when live sensor metrics show an active breach:
  // 1. Gas concentration >= 50.0 ppm
  // 2. OR hardware reported gas_alert or CRITICAL event
  // 3. OR temperature reaches emergency cutoff >= 35.0 °C
  // 4. OR AI critical reached AND gas concentration is elevated (>= 25.0 ppm)
  // When values are 5.0 ppm gas and 29.5°C temp, isCritical is guaranteed FALSE (Normal).
  const isCritical = Boolean(
    !isRepaired && (
      gasVal >= 50.0 ||
      isEdgeAlert ||
      tempVal >= 35.0 ||
      (crit.critical_reached === true && (gasVal >= 25.0 || tempVal >= 35.0))
    )
  )

  // Execute Technician Repair Handler
  const handleExecuteRepair = async () => {
    if (!isTechnician) {
      alert('Access Denied: Only certified Field Technicians have authorization to execute physical repairs.')
      return
    }

    if (!isCritical) {
      alert('Action Restricted: Repair protocol can only be initiated once a Critical Condition has been reached.')
      return
    }

    setIsRepairing(true)
    try {
      const technicianName = user?.full_name || user?.email || 'Field Technician'
      const response = await fetch(`${API_BASE_URL}/api/v1/simulator/repair`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({
          hvac_id: selectedUnit,
          sensor_location: 'suction_line',
          humidity_context: 'stable',
          technician_name: technicianName,
          technician_email: user?.email,
        }),
      })

      const data = await response.json()
      if (!response.ok) {
        throw new Error(data.message || 'Failed to execute repair.')
      }

      // Update local state immediately
      if (data.sensors) {
        const now = new Date()
        const repairedReading = {
          time: now.toLocaleTimeString().slice(0, 8),
          gasPpm: Number(data.sensors.gas_ppm || 5.0),
          temperature: Number(data.sensors.temperature || 7.0),
          pressure: Number(data.sensors.pressure || 165.0),
          current: 0.0,
        }
        setReadings((prev) => [...prev.slice(-29), repairedReading])
        setLastReading((prev) => ({
          ...(prev || {}),
          sensors: data.sensors,
          is_repair: true,
          repaired_by: technicianName,
          gas_alert: false,
          temperature_alert: false,
          event: 'NORMAL',
        }))
      }

      if (data.critical_estimation) {
        setCriticalEstimation(data.critical_estimation)
      }
      if (data.ai_result) {
        setAiResult(data.ai_result)
      }

      // Clear all active alerts
      setAlerts([])

      setRepairNotice({
        technician: technicianName,
        time: new Date().toLocaleTimeString(),
        message: `Repair Successfully Executed: Leak sealed, refrigerant recharged, and certified healthy baseline broadcast to all Administrator dashboards.`,
      })
    } catch (err) {
      console.error('Repair execution failed:', err)
      alert(`Repair failed: ${err.message}`)
    } finally {
      setIsRepairing(false)
    }
  }

  // Quick helper to simulate a critical condition for testing
  const handleTriggerTestCritical = async () => {
    setSimStepLoading(true)
    try {
      const response = await fetch(`${API_BASE_URL}/api/v1/simulator/step`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({
          hvac_id: selectedUnit,
          sensor_location: 'suction_line',
          humidity_context: 'stable',
          leak_rate: 'fast',
          step: 8,
          is_leak: true,
        }),
      })

      const data = await response.json()
      if (data.sensors) {
        const now = new Date()
        const critReading = {
          time: now.toLocaleTimeString().slice(0, 8),
          gasPpm: Number(data.sensors.gas_ppm || 85.0),
          temperature: Number(data.sensors.temperature || 38.0),
          pressure: Number(data.sensors.pressure || 95.0),
          current: Number(data.sensors.compressor_current || 4.2),
        }
        setReadings((prev) => [...prev.slice(-29), critReading])
        setLastReading({
          device_id: 'SIM_CRITICAL',
          hvac_id: selectedUnit,
          sensors: data.sensors,
          gas_alert: true,
          temperature_alert: true,
          event: 'CRITICAL',
          source: 'simulator',
          critical_estimation: data.critical_estimation,
          ai_result: data.ai_result,
        })
      }
      if (data.critical_estimation) setCriticalEstimation(data.critical_estimation)
      if (data.ai_result) setAiResult(data.ai_result)
      setRepairNotice(null)
    } catch (err) {
      console.error('Failed to trigger critical test:', err)
    } finally {
      setSimStepLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-slate-100 p-6">
      {/* Header */}
      <div className="flex flex-wrap justify-between items-center gap-4 mb-6">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-bold text-slate-800">
              HVAC Monitoring & AI Predictive Dashboard
            </h1>
            <span className="px-2.5 py-0.5 text-xs font-semibold rounded-full bg-blue-100 text-blue-800 border border-blue-200">
              v2.0 AI Core
            </span>
          </div>

          <div className="flex items-center gap-3 mt-1.5">
            <span className="text-sm text-slate-500">Monitored Unit:</span>
            <div className="inline-flex rounded-lg border border-slate-300 bg-white p-0.5 shadow-sm text-xs font-medium">
              <button
                onClick={() => { setSelectedUnit('HVAC_TEST_01'); setReadings([]); setRepairNotice(null) }}
                className={`px-3 py-1 rounded-md transition ${
                  selectedUnit === 'HVAC_TEST_01'
                    ? 'bg-blue-600 text-white font-semibold shadow-sm'
                    : 'text-slate-600 hover:text-slate-900'
                }`}
              >
                HVAC_TEST_01 (Hardware Node)
              </button>
              <button
                onClick={() => { setSelectedUnit('HVAC_SIM_01'); setReadings([]); setRepairNotice(null) }}
                className={`px-3 py-1 rounded-md transition ${
                  selectedUnit === 'HVAC_SIM_01'
                    ? 'bg-indigo-600 text-white font-semibold shadow-sm'
                    : 'text-slate-600 hover:text-slate-900'
                }`}
              >
                HVAC_SIM_01 (Virtual Simulator)
              </button>
            </div>
          </div>
        </div>

        <div className="flex items-center gap-3">
          {/* User Role Badge */}
          <div className="flex items-center gap-2 bg-white px-3 py-1.5 rounded-lg border border-slate-200 shadow-sm text-sm">
            <span className="text-slate-600">{user?.email || 'User'}</span>
            <span
              className={`px-2 py-0.5 rounded text-xs font-extrabold uppercase ${
                isTechnician
                  ? 'bg-amber-100 text-amber-800 border border-amber-300'
                  : isAdmin
                  ? 'bg-purple-100 text-purple-800 border border-purple-300'
                  : 'bg-slate-100 text-slate-700'
              }`}
            >
              {user?.role || 'OPERATOR'}
            </span>
          </div>

          {user?.role === 'ADMIN' && (
            <Link
              to="/admin"
              className="text-sm font-semibold text-blue-600 hover:underline px-2.5 py-1.5 rounded-lg border border-blue-200 bg-white shadow-sm"
            >
              Admin Panel
            </Link>
          )}

          {/* Launch Full AI Simulator Button */}
          <Link
            to="/simulator"
            className="bg-indigo-600 text-white text-sm font-semibold px-3.5 py-1.5 rounded-lg hover:bg-indigo-700 transition shadow-sm flex items-center gap-1.5"
            title="Launch full HVAC Simulation Lab"
          >
            <span>AI Simulation Lab</span>
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
            </svg>
          </Link>

          <button
            onClick={() =>
              exportDashboardPdf({
                readings,
                alerts,
                hvacId: selectedUnit,
                lastReading,
                criticalEstimation,
                aiResult,
                repairNotice,
                isRepaired,
                isCritical,
                user,
              })
            }
            className="bg-blue-600 text-white text-sm font-semibold px-3.5 py-1.5 rounded-lg hover:bg-blue-700 transition shadow-sm"
          >
            Export Report
          </button>

          {logout && (
            <button
              onClick={logout}
              className="bg-red-500 text-white text-sm font-semibold px-3.5 py-1.5 rounded-lg hover:bg-red-600 transition shadow-sm"
            >
              Log Out
            </button>
          )}
        </div>
      </div>

      {/* Dynamic Condition Banner */}
      {isCritical ? (
        /* 1. CRITICAL STATE: ONLY SHOWN WHEN CRITICAL CONDITION IS REACHED */
        <div className="bg-red-50 border-2 border-red-500 rounded-xl shadow-lg p-5 mb-5 ring-4 ring-red-400/20 animate-fade-in">
          <div className="flex flex-wrap justify-between items-center gap-4">
            <div className="max-w-2xl">
              <div className="flex items-center gap-2.5">
                <span className="w-3.5 h-3.5 rounded-full bg-red-600 animate-ping" />
                <h2 className="text-base font-extrabold text-red-950 tracking-wide uppercase">
                  🚨 CRITICAL LEAK CONDITION DETECTED — REPAIR REQUIRED
                </h2>
              </div>
              <p className="text-xs text-red-800 mt-1.5 leading-relaxed">
                Critical safety limits breached. Immediate physical intervention required to seal the leak and normalize refrigerant pressure.
                {isTechnician ? (
                  <strong className="block mt-1 text-red-900 font-bold">
                    Technician Action Authorized: You are authorized to execute on-site physical repair, seal the leak, and restore the baseline charge.
                  </strong>
                ) : (
                  <strong className="block mt-1 text-amber-900 font-bold">
                    Administrator View: Critical condition detected. Awaiting certified Field Technician to perform on-site service. Live telemetry will update here automatically once certified.
                  </strong>
                )}
              </p>
            </div>

            <div className="flex items-center gap-3">
              {isTechnician ? (
                /* TECHNICIAN: Active Repair Button */
                <button
                  onClick={handleExecuteRepair}
                  disabled={isRepairing}
                  className="bg-red-600 hover:bg-red-700 text-white font-extrabold text-sm px-6 py-3 rounded-lg shadow-lg hover:shadow-red-300 transition flex items-center gap-2 cursor-pointer animate-pulse"
                >
                  {isRepairing ? (
                    <>
                      <svg className="animate-spin h-4 w-4 text-white" viewBox="0 0 24 24">
                        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
                        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
                      </svg>
                      <span>Executing Repair...</span>
                    </>
                  ) : (
                    <>
                      <span>🔧</span>
                      <span>Execute Technician Repair</span>
                    </>
                  )}
                </button>
              ) : (
                /* ADMIN: Read-Only Notice */
                <div className="bg-amber-100 border border-amber-300 text-amber-900 px-4 py-2.5 rounded-lg text-xs font-bold flex items-center gap-2 shadow-sm">
                  <span>🔒</span>
                  <span>Awaiting Technician Repair</span>
                </div>
              )}
            </div>
          </div>
        </div>
      ) : isRepaired ? (
        /* 2. REPAIR COMPLETION BANNER: SHOWN AFTER TECHNICIAN COMPLETES REPAIR */
        <div className="bg-emerald-50 border border-emerald-300 rounded-xl p-4 mb-5 shadow-sm flex flex-wrap items-center justify-between gap-3 animate-fade-in">
          <div className="flex items-center gap-3">
            <span className="w-8 h-8 rounded-full bg-emerald-500 text-white flex items-center justify-center font-bold">✓</span>
            <div>
              <h3 className="font-bold text-emerald-900 text-sm">
                System Serviced & Certified by Technician {lastReading?.repaired_by || 'Field Technician'}
              </h3>
              <p className="text-xs text-emerald-700 mt-0.5">
                Refrigerant leak sealed, charge normalized to 165 psi, and healthy baseline confirmed across all dashboards.
              </p>
            </div>
          </div>
          <span className="text-xs font-bold text-emerald-800 bg-emerald-100 px-3 py-1 rounded-full border border-emerald-300">
            SYSTEM HEALTHY
          </span>
        </div>
      ) : (
        /* 3. NORMAL OPERATING STATE: NO REPAIR BUTTON OR REPAIR PROMPT SHOWN */
        <div className="bg-white border border-slate-200 rounded-xl p-4 mb-5 shadow-sm flex flex-wrap justify-between items-center gap-3">
          <div className="flex items-center gap-3">
            <span className="w-3 h-3 rounded-full bg-emerald-500" />
            <div>
              <h2 className="text-sm font-bold text-slate-800">
                System Status: Normal & Healthy
              </h2>
              <p className="text-xs text-slate-500 mt-0.5">
                All operating telemetry and AI projections are within nominal safety limits. No service required.
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <span className="px-3 py-1 rounded-full text-xs font-semibold bg-emerald-50 text-emerald-700 border border-emerald-200">
              ● All Parameters Nominal
            </span>
            {selectedUnit === 'HVAC_SIM_01' && (
              <button
                onClick={handleTriggerTestCritical}
                disabled={simStepLoading}
                className="bg-slate-100 hover:bg-slate-200 text-slate-600 text-xs font-semibold px-2.5 py-1 rounded-lg border border-slate-300 transition"
                title="Test simulated leak progression"
              >
                {simStepLoading ? 'Testing...' : '⚡ Simulate Leak Test'}
              </button>
            )}
          </div>
        </div>
      )}

      {/* Telemetry Stream Connection Status */}
      <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-4 mb-5">
        <div className="flex flex-wrap justify-between items-center gap-3">
          <div className="flex items-center gap-3">
            <div className={`w-3.5 h-3.5 rounded-full ${
              connectionStatus === 'Live' ? 'bg-emerald-500 animate-pulse' : 'bg-amber-400'
            }`} />
            <div>
              <h2 className="text-sm font-semibold text-slate-700">
                Live Sensor Telemetry: {selectedUnit}
              </h2>
              <p className="text-xs text-slate-500 mt-0.5">
                WebSocket: <span className="font-mono text-slate-600">{connectionStatus}</span>
                {lastReading ? (
                  <span>
                    {' '}| Device: <span className="font-semibold text-slate-700">{lastReading.device_id || 'ESP32_01'}</span>
                    {' '}| Source: <span className="font-semibold uppercase text-slate-700">{lastReading.source || 'Hardware'}</span>
                    {' '}| Event: <span className={`font-bold ${isGasAlert ? 'text-red-600' : 'text-emerald-600'}`}>{lastReading.event || 'NORMAL'}</span>
                  </span>
                ) : (
                  <span> — Waiting for telemetry packets...</span>
                )}
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            {isGasAlert && (
              <span className="px-3 py-1 rounded-full text-xs font-bold bg-red-100 text-red-700 border border-red-300 animate-pulse">
                GAS LEAK ALERT ACTIVE
              </span>
            )}
            {isTempAlert && (
              <span className="px-3 py-1 rounded-full text-xs font-bold bg-amber-100 text-amber-700 border border-amber-300">
                HIGH TEMP WARNING
              </span>
            )}
            <div
              className={`px-3 py-1 rounded-full text-xs font-bold ${
                lastReading
                  ? 'bg-emerald-100 text-emerald-700 border border-emerald-300'
                  : 'bg-amber-100 text-amber-700 border border-amber-300'
              }`}
            >
              {lastReading ? 'Streaming Data' : connectionStatus}
            </div>
          </div>
        </div>
      </div>

      {/* 5 Real-Time Sensor Telemetry Cards */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-4 mb-5">
        {/* Gas Sensor Card */}
        <div className={`bg-white rounded-xl shadow-sm border p-4 transition ${
          isGasAlert ? 'border-red-400 bg-red-50/30' : 'border-slate-200'
        }`}>
          <div className="flex justify-between items-start">
            <p className="text-xs font-semibold text-slate-500">Refrigerant Gas (MQ-5)</p>
            {sensors.mq5_adc != null && (
              <span className="text-[10px] bg-slate-100 text-slate-600 font-mono px-1.5 py-0.5 rounded">
                ADC: {sensors.mq5_adc}
              </span>
            )}
          </div>
          <p className={`text-2xl font-black mt-2 ${
            isGasAlert ? 'text-red-600 animate-pulse' : 'text-slate-800'
          }`}>
            {sensors.gas_ppm != null ? `${Number(sensors.gas_ppm).toFixed(1)} ppm` : '-- ppm'}
          </p>
          <p className="text-[11px] text-slate-400 mt-1">Threshold: 50.0 ppm</p>
        </div>

        {/* Pressure Card */}
        <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-4">
          <p className="text-xs font-semibold text-slate-500">System Pressure (PR2010)</p>
          <p className="text-2xl font-black text-slate-800 mt-2">
            {sensors.pressure != null
              ? (String(sensors.pressure).includes('kPa')
                  ? sensors.pressure
                  : `${Number(sensors.pressure).toFixed(1)} kPa`)
              : '-- kPa'}
          </p>
          <p className="text-[11px] text-slate-400 mt-1">
            {sensors.pressure != null
              ? `${(Number(sensors.pressure) / 1000.0).toFixed(3)} MPa`
              : 'Nominal Range: 800 - 1000 kPa'}
          </p>
        </div>

        {/* Temperature Card */}
        <div className={`bg-white rounded-xl shadow-sm border p-4 transition ${
          isTempAlert ? 'border-amber-400 bg-amber-50/30' : 'border-slate-200'
        }`}>
          <p className="text-xs font-semibold text-slate-500">Temperature (DHT22)</p>
          <p className={`text-2xl font-black mt-2 ${
            isTempAlert ? 'text-amber-600' : 'text-slate-800'
          }`}>
            {sensors.temperature != null ? `${Number(sensors.temperature).toFixed(1)} °C` : '-- °C'}
          </p>
          <p className="text-[11px] text-slate-400 mt-1">Limit: 35.0 °C</p>
        </div>

        {/* Humidity Card */}
        <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-4">
          <p className="text-xs font-semibold text-slate-500">Humidity (DHT22)</p>
          <p className="text-2xl font-black text-slate-800 mt-2">
            {sensors.humidity != null ? `${Number(sensors.humidity).toFixed(1)} %` : '-- %'}
          </p>
          <p className="text-[11px] text-slate-400 mt-1">Relative Humidity</p>
        </div>

        {/* Current Sensor Card */}
        <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-4">
          <p className="text-xs font-semibold text-slate-500">Compressor Current (ACS712)</p>
          <p className="text-2xl font-black text-slate-800 mt-2">
            {sensors.compressor_current != null
              ? `${Number(sensors.compressor_current).toFixed(2)} A`
              : '-- A'}
          </p>
          <p className="text-[11px] text-slate-400 mt-1">AC RMS Load</p>
        </div>
      </div>

      {/* AI Critical Condition Predictor & Models Evaluation */}
      <div className="mb-5">
        <AICriticalPredictor
          criticalEstimation={criticalEstimation}
          aiResult={aiResult}
          lastReading={lastReading}
        />
      </div>

      {/* 4 Sensor Live Historical Charts */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-5">
        <SensorChart
          data={readings}
          dataKey="gasPpm"
          label="Refrigerant Gas Concentration"
          unit="ppm"
          color="#dc2626"
          criticalThreshold={50}
          thresholdLabel="Critical Gas Limit (50 ppm)"
        />

        <SensorChart
          data={readings}
          dataKey="temperature"
          label="Chiller Temperature"
          unit="°C"
          color="#2563eb"
          criticalThreshold={35}
          thresholdLabel="Max Operating Temp (35°C)"
        />

        <SensorChart
          data={readings}
          dataKey="pressure"
          label="Suction Line Pressure"
          unit="kPa"
          color="#059669"
        />

        <SensorChart
          data={readings}
          dataKey="current"
          label="Compressor Current Load"
          unit="A"
          color="#d97706"
        />
      </div>

      {/* Real Backend Active Alerts */}
      <AlertPanel alerts={alerts} />
    </div>
  )
}

export default Dashboard