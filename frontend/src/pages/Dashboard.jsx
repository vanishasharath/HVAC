import { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import SensorChart from '../components/SensorChart'
import AlertPanel from '../components/AlertPanel'
import { exportDashboardPdf } from '../utils/exportPdf'

const HVAC_ID = 'HVAC_TEST_01'
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000'
const WS_BASE_URL = 'ws://127.0.0.1:8000'

function Dashboard() {
  const { user, token, logout } = useAuth()

  const [readings, setReadings] = useState([])
  const [alerts, setAlerts] = useState([])
  const [connectionStatus, setConnectionStatus] = useState('Connecting...')
  const [lastReading, setLastReading] = useState(null)

  // Fetch active alerts from the real backend
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

    // Refresh alerts every 10 seconds
    const interval = setInterval(fetchAlerts, 10000)

    return () => clearInterval(interval)
  }, [token])

  // Connect to live WebSocket sensor stream
  useEffect(() => {
    let websocket
    let reconnectTimer
    let stopped = false

    const connect = () => {
      if (stopped) return

      setConnectionStatus('Connecting...')

      websocket = new WebSocket(`${WS_BASE_URL}/ws/hvac/${HVAC_ID}`)

      websocket.onopen = () => {
        console.log('WebSocket connected')
        setConnectionStatus('Live')
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
          if (message.hvac_id !== HVAC_ID) return

          const sensorData = message.data

          // STRICT FILTER: Only incorporate values from physical Arduino / ESP32 hardware
          const isHardwareReading = (
            sensorData.source === 'esp32' ||
            sensorData.source === 'arduino' ||
            sensorData.source === 'hardware' ||
            (sensorData.device_id && sensorData.device_id.startsWith('ESP32'))
          ) && (
            sensorData.source !== 'simulator' &&
            sensorData.source !== 'technician_repair' &&
            sensorData.mode !== 'demo' &&
            (!sensorData.device_id || !sensorData.device_id.startsWith('SIM_'))
          )

          if (!isHardwareReading) {
            console.log('Skipping simulated data on normal Arduino dashboard:', sensorData)
            return
          }

          const sensors = sensorData.sensors || {}

          const timestamp = sensorData.timestamp
            ? new Date(sensorData.timestamp)
            : new Date()

          const newReading = {
            time: timestamp.toLocaleTimeString().slice(0, 8),
            gasPpm: sensors.gas_ppm != null ? Number(sensors.gas_ppm) : 0,
            temperature: sensors.temperature != null ? Number(sensors.temperature) : 0,
          }

          setLastReading(sensorData)

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
        console.log('WebSocket disconnected')
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
  }, [])

  return (
    <div className="min-h-screen bg-slate-100 p-6">
      {/* Header */}
      <div className="flex justify-between items-center mb-6">
        <div>
          <h1 className="text-2xl font-bold text-slate-800">
            HVAC Monitoring Dashboard
          </h1>

          <p className="text-sm text-slate-500 mt-1">
            HVAC Unit: {HVAC_ID}
          </p>
        </div>

        <div className="flex items-center gap-4">
          <span className="text-sm text-slate-600">
            {user?.email || 'Demo Operator'} — {user?.role || 'TECHNICIAN'}
          </span>

          {user?.role === 'ADMIN' && (
            <Link
              to="/admin"
              className="text-sm text-blue-600 hover:underline"
            >
              Admin Panel
            </Link>
          )}

          {/* Dedicated Button to Launch Simulator in New Window */}
          <a
            href="/simulator"
            target="_blank"
            rel="noopener noreferrer"
            className="bg-indigo-600 text-white text-sm font-semibold px-3.5 py-1.5 rounded-lg hover:bg-indigo-700 transition shadow-sm flex items-center gap-1.5"
            title="Launch AI Simulation & Predictive Lab in a new window"
          >
            <span>Launch AI Simulator</span>
            <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
            </svg>
          </a>

          <button
            onClick={() => exportDashboardPdf(readings, alerts)}
            className="bg-blue-600 text-white text-sm px-3.5 py-1.5 rounded-lg hover:bg-blue-700 transition"
          >
            Export Report
          </button>

          {logout && (
            <button
              onClick={logout}
              className="bg-red-500 text-white text-sm px-3.5 py-1.5 rounded-lg hover:bg-red-600 transition"
            >
              Log Out
            </button>
          )}
        </div>
      </div>

      {/* WebSocket Status */}
      <div className="bg-white rounded-xl shadow p-4 mb-4">
        <div className="flex justify-between items-center">
          <div>
            <h2 className="text-sm font-semibold text-slate-600">
              Live Sensor Connection (Arduino / ESP32 Node)
            </h2>

            <p className="text-sm text-slate-500 mt-1">
              WebSocket: {connectionStatus} {lastReading ? `— Receiving telemetry from ${lastReading.device_id || 'ESP32_01'}` : '— Waiting for Arduino packets'}
            </p>
          </div>

          <div
            className={`px-3 py-1 rounded-full text-sm font-semibold ${
              lastReading
                ? 'bg-green-100 text-green-700'
                : 'bg-yellow-100 text-yellow-700'
            }`}
          >
            {lastReading ? 'Arduino Live' : connectionStatus}
          </div>
        </div>
      </div>

      {/* Latest Sensor Values */}
      <div className="grid grid-cols-4 gap-4 mb-4">
        <div className="bg-white rounded-xl shadow p-4">
          <p className="text-xs text-slate-500">
            Gas Concentration
          </p>

          <p className="text-2xl font-bold text-slate-800 mt-1">
            {lastReading?.sensors?.gas_ppm != null
              ? `${Number(lastReading.sensors.gas_ppm).toFixed(1)} ppm`
              : '-- ppm'}
          </p>
        </div>

        <div className="bg-white rounded-xl shadow p-4">
          <p className="text-xs text-slate-500">
            Pressure
          </p>

          <p className="text-2xl font-bold text-slate-800 mt-1">
            {lastReading?.sensors?.pressure != null
              ? (String(lastReading.sensors.pressure).includes('kPa')
                  ? lastReading.sensors.pressure
                  : `${Number(lastReading.sensors.pressure).toFixed(1)} kPa`)
              : '-- kPa'}
          </p>
        </div>

        <div className="bg-white rounded-xl shadow p-4">
          <p className="text-xs text-slate-500">
            Temperature
          </p>

          <p className="text-2xl font-bold text-slate-800 mt-1">
            {lastReading?.sensors?.temperature != null
              ? `${Number(lastReading.sensors.temperature).toFixed(1)} °C`
              : '-- °C'}
          </p>
        </div>

        <div className="bg-white rounded-xl shadow p-4">
          <p className="text-xs text-slate-500">
            Humidity
          </p>

          <p className="text-2xl font-bold text-slate-800 mt-1">
            {lastReading?.sensors?.humidity != null
              ? `${Number(lastReading.sensors.humidity).toFixed(1)} %`
              : '-- %'}
          </p>
        </div>
      </div>

      {/* Sensor Charts */}
      <div className="grid grid-cols-2 gap-4 mb-4">
        <SensorChart
          data={readings}
          dataKey="gasPpm"
          label="Refrigerant Gas (ppm)"
          color="#dc2626"
        />

        <SensorChart
          data={readings}
          dataKey="temperature"
          label="Temperature (°C)"
          color="#2563eb"
        />
      </div>

      {/* Real Backend Alerts */}
      <AlertPanel alerts={alerts} />
    </div>
  )
}

export default Dashboard