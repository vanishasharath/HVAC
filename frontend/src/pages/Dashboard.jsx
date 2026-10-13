import { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import SensorChart from '../components/SensorChart'
import AlertPanel from '../components/AlertPanel'
import { exportDashboardPdf } from '../utils/exportPdf'

const HVAC_ID = 'HVAC_TEST_01'
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL
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
    const websocket = new WebSocket(
      `${WS_BASE_URL}/ws/hvac/${HVAC_ID}`
    )

    websocket.onopen = () => {
      console.log('WebSocket connected')
      setConnectionStatus('Live')
    }

    websocket.onmessage = (event) => {
      try {
        const message = JSON.parse(event.data)

        console.log('WebSocket message:', message)

        if (message.event !== 'sensor_reading') return

        const sensorData = message.data
        const sensors = sensorData.sensors || {}

        const timestamp = sensorData.timestamp
          ? new Date(sensorData.timestamp)
          : new Date()

        const newReading = {
          time: timestamp.toLocaleTimeString().slice(0, 8),
          gasPpm: sensors.gas_ppm ?? 0,
          temperature: sensors.temperature ?? 0,
        }

        setLastReading(sensorData)

        setReadings((prev) => [
          ...prev.slice(-19),
          newReading,
        ])
      } catch (error) {
        console.error(
          'Failed to process WebSocket message:',
          error
        )
      }
    }

    websocket.onerror = (error) => {
      console.error('WebSocket error:', error)
      setConnectionStatus('Connection Error')
    }

    websocket.onclose = () => {
      console.log('WebSocket disconnected')
      setConnectionStatus('Disconnected')
    }

    return () => {
      websocket.close()
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
            {user?.email} — {user?.role}
          </span>

          {user?.role === 'ADMIN' && (
            <Link
              to="/admin"
              className="text-sm text-blue-600 hover:underline"
            >
              Admin Panel
            </Link>
          )}

          <button
            onClick={() => exportDashboardPdf(readings, alerts)}
            className="bg-blue-600 text-white text-sm px-3 py-1.5 rounded-lg hover:bg-blue-700"
          >
            Export Report
          </button>

          <button
            onClick={logout}
            className="bg-red-500 text-white text-sm px-3 py-1.5 rounded-lg hover:bg-red-600"
          >
            Log Out
          </button>

        </div>
      </div>

      {/* WebSocket Status */}
      <div className="bg-white rounded-xl shadow p-4 mb-4">
        <div className="flex justify-between items-center">

          <div>
            <h2 className="text-sm font-semibold text-slate-600">
              Live Sensor Connection
            </h2>

            <p className="text-sm text-slate-500 mt-1">
              WebSocket: {connectionStatus}
            </p>
          </div>

          <div
            className={`px-3 py-1 rounded-full text-sm font-semibold ${
              connectionStatus === 'Live'
                ? 'bg-green-100 text-green-700'
                : 'bg-yellow-100 text-yellow-700'
            }`}
          >
            {connectionStatus}
          </div>

        </div>
      </div>

      {/* Latest Sensor Values */}
      {lastReading && (
        <div className="grid grid-cols-4 gap-4 mb-4">

          <div className="bg-white rounded-xl shadow p-4">
            <p className="text-xs text-slate-500">
              Gas Concentration
            </p>

            <p className="text-2xl font-bold text-slate-800">
              {lastReading.sensors?.gas_ppm ?? '--'} ppm
            </p>
          </div>

          <div className="bg-white rounded-xl shadow p-4">
            <p className="text-xs text-slate-500">
              Pressure
            </p>

            <p className="text-2xl font-bold text-slate-800">
              {lastReading.sensors?.pressure ?? '--'}
            </p>
          </div>

          <div className="bg-white rounded-xl shadow p-4">
            <p className="text-xs text-slate-500">
              Temperature
            </p>

            <p className="text-2xl font-bold text-slate-800">
              {lastReading.sensors?.temperature ?? '--'} °C
            </p>
          </div>

          <div className="bg-white rounded-xl shadow p-4">
            <p className="text-xs text-slate-500">
              Humidity
            </p>

            <p className="text-2xl font-bold text-slate-800">
              {lastReading.sensors?.humidity ?? '--'} %
            </p>
          </div>

        </div>
      )}

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