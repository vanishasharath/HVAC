import { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import SensorChart from '../components/SensorChart'
import AlertPanel from '../components/AlertPanel'
import AICriticalPredictor from '../components/AICriticalPredictor'
import SimulatorControlPanel from '../components/SimulatorControlPanel'
import { exportDashboardPdf } from '../utils/exportPdf'

const HVAC_ID = 'HVAC_SIM_01'
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000'
const WS_BASE_URL = 'ws://127.0.0.1:8000'

function SimulatorDashboard() {
  const { user, token, logout } = useAuth()

  const [readings, setReadings] = useState([])
  const [alerts, setAlerts] = useState([])
  const [connectionStatus, setConnectionStatus] = useState('Connecting...')
  const [lastReading, setLastReading] = useState(null)
  const [criticalEstimation, setCriticalEstimation] = useState(null)
  const [aiResult, setAiResult] = useState(null)

  // Fetch active alerts from the backend
  useEffect(() => {
    if (!token) return

    const fetchAlerts = async () => {
      try {
        const response = await fetch(
          `${API_BASE_URL}/api/v1/alerts?hvac_id=${HVAC_ID}&status=ACTIVE`,
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
          unitId: alert.hvac_id || HVAC_ID,
          message:
            alert.message ||
            alert.description ||
            `Alert detected for ${HVAC_ID}`,
        }))

        setAlerts(formattedAlerts)
      } catch (error) {
        console.error('Error fetching alerts:', error)
      }
    }

    fetchAlerts()

    const interval = setInterval(fetchAlerts, 10000)
    return () => clearInterval(interval)
  }, [token])

  // Connect to live WebSocket stream
  useEffect(() => {
    let websocket
    let reconnectTimer
    let stopped = false

    const connect = () => {
      if (stopped) return

      setConnectionStatus('Connecting...')

      websocket = new WebSocket(`${WS_BASE_URL}/ws/hvac/${HVAC_ID}`)

      websocket.onopen = () => {
        setConnectionStatus('Live Telemetry Ready')
      }

      websocket.onmessage = (event) => {
        try {
          const message = JSON.parse(event.data)

          // Handle real-time alert creation
          if (message.event === 'alert_created') {
            const alertData = message.data
            if (alertData && (alertData.hvac_id === HVAC_ID || !alertData.hvac_id)) {
              const alertId = alertData.id || alertData._id
              const formattedAlert = {
                id: alertId,
                severity: alertData.severity || 'WARNING',
                unitId: alertData.hvac_id || HVAC_ID,
                message:
                  alertData.message ||
                  alertData.description ||
                  `Gas alert detected for ${HVAC_ID}`,
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

          if (message.hvac_id !== HVAC_ID) {
            return
          }

          const sensorData = message.data
          const sensors = sensorData?.sensors

          if (!sensors) return

          const timestamp = sensorData.timestamp
            ? new Date(sensorData.timestamp)
            : new Date()

          const gasVal = sensors.gas_ppm != null ? Number(sensors.gas_ppm) : null
          const tempVal = sensors.temperature != null ? Number(sensors.temperature) : null
          const pressVal = sensors.location_pressure != null
            ? Number(sensors.location_pressure)
            : (sensors.pressure != null ? Number(sensors.pressure) : null)
          const humVal = sensors.humidity != null ? Number(sensors.humidity) : null

          const critHours = (
            sensorData.critical_estimation?.elapsed_time_hours ??
            sensorData.ai_result?.critical_estimation?.elapsed_time_hours
          )
          const simTimeLabel = critHours != null && critHours > 0
            ? `+${Number(critHours).toFixed(1)}h`
            : timestamp.toLocaleTimeString().slice(0, 5)

          const newReading = {
            time: timestamp.toLocaleTimeString().slice(0, 8),
            simTime: simTimeLabel,
            fullTime: critHours != null
              ? `Simulated Operating Time: +${Number(critHours).toFixed(1)} Hours (${timestamp.toLocaleTimeString()})`
              : timestamp.toLocaleTimeString(),
            gasPpm: gasVal,
            temperature: tempVal,
            pressure: pressVal,
            humidity: humVal,
          }

          setLastReading(sensorData)

          if (sensorData.ai_result) {
            setAiResult(sensorData.ai_result)
          }

          if (sensorData.critical_estimation) {
            setCriticalEstimation(sensorData.critical_estimation)
          } else if (sensorData.ai_result?.critical_estimation) {
            setCriticalEstimation(sensorData.ai_result.critical_estimation)
          }

          setReadings((previous) => [
            ...previous.slice(-120),
            newReading,
          ])

          setConnectionStatus('Live')
        } catch (error) {
          console.error('Failed to process WebSocket message:', error)
        }
      }

      websocket.onerror = (error) => {
        console.error('WebSocket error:', error)
      }

      websocket.onclose = () => {
        if (stopped) return
        setConnectionStatus('Disconnected — reconnecting...')
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
  }, [])

  // Callback from SimulatorControlPanel to instantly update UI on manual step
  const handleSimulatorStep = (stepData) => {
    if (!stepData) return
    const sensors = stepData.sensors
    if (!sensors) return

    const isRepair = Boolean(
      stepData.is_repair ||
      stepData.critical_estimation?.is_repaired ||
      stepData.message?.includes('serviced and repaired') ||
      stepData.message?.includes('repaired')
    )

    if (isRepair) {
      setAlerts([])
    }

    const now = new Date()
    const gasVal = sensors.gas_ppm != null ? Number(sensors.gas_ppm) : null
    const tempVal = sensors.temperature != null ? Number(sensors.temperature) : null
    const pressVal = sensors.location_pressure != null
      ? Number(sensors.location_pressure)
      : (sensors.pressure != null ? Number(sensors.pressure) : null)
    const humVal = sensors.humidity != null ? Number(sensors.humidity) : null
    const elapsedH = (
      stepData.simulated_operating_hours ??
      stepData.critical_estimation?.elapsed_time_hours ??
      0.0
    )
    const simTimeLabel = `+${Number(elapsedH).toFixed(1)}h`

    const newReading = {
      time: now.toLocaleTimeString().slice(0, 8),
      simTime: simTimeLabel,
      fullTime: `Simulated Operating Time: +${Number(elapsedH).toFixed(1)} Hours (${now.toLocaleTimeString()})`,
      gasPpm: gasVal,
      temperature: tempVal,
      pressure: pressVal,
      humidity: humVal,
    }

    setReadings((previous) => [...previous.slice(-120), newReading])

    setLastReading({
      hvac_id: HVAC_ID,
      sensors: sensors,
      sensor_location: stepData.sensor_location,
      humidity_context: stepData.humidity_context,
      ai_result: stepData.ai_result,
      critical_estimation: stepData.critical_estimation,
      is_repaired: isRepair,
    })

    if (stepData.ai_result) setAiResult(stepData.ai_result)
    if (stepData.critical_estimation) setCriticalEstimation(stepData.critical_estimation)
  }

  const sensorLoc = lastReading?.sensor_location || lastReading?.sensors?.sensor_location || 'suction_line'
  const locationLabelMap = {
    suction_line: 'Suction Line (Low-Side)',
    discharge_line: 'Discharge Line (High-Side)',
    liquid_line: 'Liquid Line (Condenser Exit)',
    indoor_ambient_plenum: 'Indoor Supply Duct / Plenum',
  }
  const displayLocation = locationLabelMap[sensorLoc] || sensorLoc

  const gasValue = lastReading?.sensors?.gas_ppm != null ? Number(lastReading.sensors.gas_ppm) : null
  const tempValue = lastReading?.sensors?.temperature != null ? Number(lastReading.sensors.temperature) : null
  const pressValue = lastReading?.sensors?.location_pressure != null
    ? Number(lastReading.sensors.location_pressure)
    : (lastReading?.sensors?.pressure != null ? Number(lastReading.sensors.pressure) : null)
  const humValue = lastReading?.sensors?.humidity != null ? Number(lastReading.sensors.humidity) : null

  return (
    <div className="min-h-screen bg-slate-100 p-6">
      {/* Header */}
      <div className="flex flex-wrap justify-between items-center gap-4 mb-6">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-2xl font-black text-slate-800 tracking-tight">
              HVAC Predictive Leak Detection & Simulator
            </h1>
            <span className="text-xs font-bold px-2.5 py-0.5 rounded-full bg-blue-100 text-blue-700">
              R-32 Split AC
            </span>
          </div>

          <p className="text-sm text-slate-500 mt-1">
            Monitored Unit: <strong className="text-slate-700">{HVAC_ID}</strong> | Transducer Location:{' '}
            <strong className="text-blue-600">{displayLocation}</strong>
          </p>
        </div>

        <div className="flex items-center gap-3">
          <Link
            to="/dashboard"
            className="text-sm font-semibold bg-white border border-slate-300 text-slate-700 px-3.5 py-1.5 rounded-lg hover:bg-slate-50 transition shadow-sm flex items-center gap-1.5"
            title="Go to standard live sensor monitor"
          >
            <span>← Live Monitor</span>
          </Link>

          <span className="text-sm text-slate-600 bg-white px-3 py-1.5 rounded-lg shadow-sm border border-slate-200">
            {user?.email || 'Demo Operator'} — <strong className="text-slate-800">{user?.role || 'TECHNICIAN'}</strong>
          </span>

          {user?.role === 'ADMIN' && (
            <Link to="/admin" className="text-sm font-semibold text-blue-600 hover:underline">
              Admin Panel
            </Link>
          )}

          <button
            onClick={() => exportDashboardPdf(readings, alerts)}
            className="bg-blue-600 text-white text-sm font-semibold px-3.5 py-1.5 rounded-lg hover:bg-blue-700 transition shadow-sm"
          >
            Export Report
          </button>

          {logout && (
            <button
              onClick={logout}
              className="bg-red-500 text-white text-sm font-semibold px-3 py-1.5 rounded-lg hover:bg-red-600 transition shadow-sm"
            >
              Log Out
            </button>
          )}
        </div>
      </div>

      {/* Connection & Telemetry Status Bar */}
      <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-4 mb-5 flex flex-wrap justify-between items-center gap-3">
        <div className="flex items-center gap-3">
          <div className={`w-3 h-3 rounded-full ${connectionStatus.includes('Live') ? 'bg-green-500 animate-pulse' : 'bg-amber-500'}`} />
          <div>
            <span className="text-xs font-semibold text-slate-500 uppercase tracking-wider block">
              Simulation Telemetry Stream
            </span>
            <span className="text-sm font-bold text-slate-800">
              WebSocket: {connectionStatus}
            </span>
          </div>
        </div>

        <div className="flex items-center gap-2 text-xs">
          <span className="px-2.5 py-1 rounded bg-slate-100 text-slate-700 font-medium">
            Time Scale: <strong>1 step = 15 operating mins</strong>
          </span>
          <span className="px-2.5 py-1 rounded bg-blue-50 text-blue-700 font-medium border border-blue-200">
            AI Pipeline: <strong>IsoForest + LSTM + Random Forest</strong>
          </span>
        </div>
      </div>

      {/* Star Feature: AI Critical Condition & Trend Estimation Panel */}
      <AICriticalPredictor
        criticalEstimation={criticalEstimation}
        aiResult={aiResult}
        lastReading={lastReading}
      />

      {/* Interactive Live Simulator Controller */}
      <SimulatorControlPanel
        hvacId={HVAC_ID}
        onSimulatorStep={handleSimulatorStep}
      />

      {/* Latest Sensor Value Tiles */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-5">
        {/* 1. Refrigerant Gas Concentration */}
        <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-4 relative overflow-hidden">
          <div className="flex justify-between items-start">
            <p className="text-xs font-semibold text-slate-500 uppercase tracking-wider">
              Refrigerant Gas
            </p>
            {gasValue != null && gasValue >= 400.0 ? (
              <span className="text-[10px] font-bold px-1.5 py-0.5 rounded bg-red-100 text-red-700 animate-pulse">
                CRITICAL
              </span>
            ) : gasValue != null && gasValue >= 50.0 ? (
              <span className="text-[10px] font-bold px-1.5 py-0.5 rounded bg-amber-100 text-amber-700">
                WARNING
              </span>
            ) : (
              <span className="text-[10px] font-bold px-1.5 py-0.5 rounded bg-emerald-100 text-emerald-700">
                NORMAL
              </span>
            )}
          </div>

          <p className={`text-2xl font-black mt-1 ${
            gasValue != null && gasValue >= 50.0 ? 'text-red-600' : 'text-slate-800'
          }`}>
            {gasValue != null ? `${gasValue.toFixed(1)} ppm` : '-- ppm'}
          </p>

          <p className="text-[11px] text-slate-400 mt-1">
            Critical Threshold: <strong>≥ 400.0 ppm</strong> (Baseline: 5.0)
          </p>
        </div>

        {/* 2. Physical Pressure (Based on Sensor Location) */}
        <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-4">
          <div className="flex justify-between items-start">
            <p className="text-xs font-semibold text-slate-500 uppercase tracking-wider">
              Circuit Pressure
            </p>
            <span className="text-[10px] font-bold px-1.5 py-0.5 rounded bg-sky-100 text-sky-800 line-clamp-1 max-w-[130px]" title={displayLocation}>
              {displayLocation.split(' ')[0]}
            </span>
          </div>

          <p className="text-2xl font-black text-slate-800 mt-1">
            {pressValue != null ? `${pressValue.toFixed(1)} psi` : '-- psi'}
          </p>

          <p className="text-[11px] text-slate-400 mt-1">
            {sensorLoc === 'suction_line'
              ? 'Low-side drop to ≤ 105 psi is critical'
              : sensorLoc === 'indoor_ambient_plenum'
              ? 'Atmospheric air pressure (~14.7 psi)'
              : 'High-side pressure behavior'}
          </p>
        </div>

        {/* 3. Supply-Air Temperature Rise */}
        <div className={`bg-white rounded-xl shadow-sm border p-4 transition-all ${
          tempValue != null && tempValue >= 22.0
            ? 'border-red-500 bg-red-50/40'
            : tempValue != null && tempValue >= 14.0
            ? 'border-amber-400 bg-amber-50/30'
            : 'border-slate-200'
        }`}>
          <div className="flex justify-between items-start">
            <p className="text-xs font-semibold text-slate-500 uppercase tracking-wider">
              Supply-Air Temp
            </p>
            {tempValue != null && tempValue >= 22.0 ? (
              <span className="text-[10px] font-bold px-1.5 py-0.5 rounded bg-red-100 text-red-700 animate-pulse">
                COOLING FAILURE
              </span>
            ) : tempValue != null && tempValue >= 14.0 ? (
              <span className="text-[10px] font-bold px-1.5 py-0.5 rounded bg-amber-100 text-amber-700">
                DEGRADING
              </span>
            ) : (
              <span className="text-[10px] font-bold px-1.5 py-0.5 rounded bg-emerald-100 text-emerald-700">
                OPTIMAL
              </span>
            )}
          </div>

          <p className={`text-2xl font-black mt-1 ${
            tempValue != null && tempValue >= 18.0 ? 'text-red-600' : 'text-slate-800'
          }`}>
            {tempValue != null ? `${tempValue.toFixed(1)} °C` : '-- °C'}
          </p>

          <p className="text-[11px] text-slate-400 mt-1">
            Gradual rise from 7°C; <strong>≥ 22.0°C</strong> = total failure
          </p>
        </div>

        {/* 4. Contextual Humidity (Independent Variable) */}
        <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-4">
          <div className="flex justify-between items-start">
            <p className="text-xs font-semibold text-slate-500 uppercase tracking-wider">
              Contextual Humidity
            </p>
            <span className="text-[10px] font-bold px-1.5 py-0.5 rounded bg-indigo-100 text-indigo-700">
              CONTEXT
            </span>
          </div>

          <p className="text-2xl font-black text-slate-800 mt-1">
            {humValue != null ? `${humValue.toFixed(1)} %` : '-- %'}
          </p>

          <p className="text-[11px] text-slate-400 mt-1">
            Independent ambient context (not forced to track leak)
          </p>
        </div>
      </div>

      {/* 4 Multi-Parameter Real-Time Trend Charts */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-5">
        <SensorChart
          data={readings}
          dataKey="gasPpm"
          label="Refrigerant Gas Concentration (ppm)"
          color="#dc2626"
          unit="ppm"
          criticalThreshold={400.0}
          thresholdLabel="Critical Safety Limit (400 ppm)"
          xAxisKey="simTime"
        />

        <SensorChart
          data={readings}
          dataKey="temperature"
          label="Supply-Air Temperature Rise (°C)"
          color="#ea580c"
          unit="°C"
          criticalThreshold={22.0}
          thresholdLabel="Critical Cooling Failure (22.0°C)"
          xAxisKey="simTime"
        />

        <SensorChart
          data={readings}
          dataKey="pressure"
          label={`Cycle Pressure [${displayLocation}]`}
          color="#0284c7"
          unit="psi"
          criticalThreshold={sensorLoc === 'suction_line' ? 105.0 : null}
          thresholdLabel="Suction Starvation (105 psi)"
          xAxisKey="simTime"
        />

        <SensorChart
          data={readings}
          dataKey="humidity"
          label="Contextual Relative Humidity (% RH - Ambient Environment)"
          color="#6366f1"
          unit="%"
          xAxisKey="simTime"
        />
      </div>

      {/* Active Backend Alerts */}
      <AlertPanel alerts={alerts} />
    </div>
  )
}

export default SimulatorDashboard
