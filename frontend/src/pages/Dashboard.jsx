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
    let websocket;
    let reconnectTimer;
    let stopped = false;

    const connect = () => {
      if (stopped) return;

      setConnectionStatus('Connecting...');

      websocket = new WebSocket(
        `${WS_BASE_URL}/ws/hvac/${HVAC_ID}`
      );

      websocket.onopen = () => {
        console.log('WebSocket connected');
        // Connected does not necessarily mean sensor data is arriving.
        setConnectionStatus('Connected — waiting for data');
      };

      websocket.onmessage = (event) => {
        try {
          const message = JSON.parse(event.data);
          console.log('WebSocket message:', message);

          // Handle real-time alert creation
          if (message.event === 'alert_created') {
            const alertData = message.data;
            if (alertData && (alertData.hvac_id === HVAC_ID || !alertData.hvac_id)) {
              const alertId = alertData.id || alertData._id;
              const formattedAlert = {
                id: alertId,
                severity: alertData.severity || 'WARNING',
                unitId: alertData.hvac_id || HVAC_ID,
                message:
                  alertData.message ||
                  alertData.description ||
                  `Gas alert detected for ${HVAC_ID}`,
              };
              setAlerts((prev) => {
                if (prev.some((a) => a.id === alertId)) return prev;
                return [formattedAlert, ...prev];
              });
            }
            return;
          }

          // Handle real-time alert resolution
          if (message.event === 'alert_resolved') {
            const resolvedId = message.data?.id || message.data?._id;
            if (resolvedId) {
              setAlerts((prev) => prev.filter((a) => a.id !== resolvedId));
            }
            return;
          }

          // Ignore heartbeat messages such as {"type":"ping"}.
          if (message.event !== 'sensor_reading') return;

          if (message.hvac_id !== HVAC_ID) {
            console.warn('Ignoring reading for another HVAC unit');
            return;
          }

          const sensorData = message.data;
          const sensors = sensorData?.sensors;

          if (!sensors) {
            console.warn('Sensor message has no sensors field:', message);
            return;
          }

          const timestamp = sensorData.timestamp
            ? new Date(sensorData.timestamp)
            : new Date();

          const gasVal = sensors.gas_ppm != null ? Number(sensors.gas_ppm) : null;
          const tempVal = sensors.temperature != null ? Number(sensors.temperature) : null;

          const newReading = {
            time: timestamp.toLocaleTimeString().slice(0, 8),
            gasPpm: gasVal,
            temperature: tempVal,
          };

          setLastReading(sensorData);

          // If reading indicates gas alert or risk condition, show in active alerts
          if (sensorData.gas_alert || (sensorData.event && ['WARNING', 'HIGH RISK', 'CRITICAL'].includes(String(sensorData.event).toUpperCase()))) {
            setAlerts((prev) => {
              const edgeId = `edge_${sensorData.hvac_id || HVAC_ID}`;
              if (prev.some((a) => a.id === edgeId || a.severity === (sensorData.event || 'WARNING'))) {
                return prev;
              }
              return [
                {
                  id: edgeId,
                  severity: sensorData.event || 'WARNING',
                  unitId: sensorData.hvac_id || HVAC_ID,
                  message: `Gas leak alert (${sensorData.event || 'WARNING'}) active on sensor node`,
                },
                ...prev,
              ];
            });
          }

          setReadings((previous) => [
            ...previous.slice(-19),
            newReading,
          ]);

          setConnectionStatus('Live');
        } catch (error) {
          console.error('Failed to process WebSocket message:', error);
        }
      };

      websocket.onerror = (error) => {
        console.error('WebSocket error:', error);
      };

      websocket.onclose = () => {
        if (stopped) return;

        console.warn('WebSocket disconnected; retrying in 3 seconds');
        setConnectionStatus('Disconnected — reconnecting...');

        reconnectTimer = setTimeout(connect, 3000);
      };
    };

    connect();

    return () => {
      stopped = true;
      clearTimeout(reconnectTimer);

      if (websocket) {
        websocket.onclose = null;
        websocket.close();
      }
    };
  }, []);

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
            className={`px-3 py-1 rounded-full text-sm font-semibold ${connectionStatus === 'Live'
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

            <p className={`text-2xl font-bold ${
              (lastReading.sensors?.gas_ppm > 50 || lastReading.event === 'WARNING' || lastReading.gas_alert)
                ? 'text-red-600'
                : 'text-slate-800'
            }`}>
              {lastReading.sensors?.gas_ppm != null
                ? `${Number(lastReading.sensors.gas_ppm).toFixed(1)} ppm`
                : '-- ppm'}
            </p>
          </div>

          <div className="bg-white rounded-xl shadow p-4">
            <p className="text-xs text-slate-500">
              Pressure
            </p>

            <p className="text-2xl font-bold text-slate-800">
              {lastReading.sensors?.pressure != null
                ? `${Number(lastReading.sensors.pressure).toFixed(1)} kPa`
                : '--'}
            </p>
          </div>

          <div className="bg-white rounded-xl shadow p-4">
            <p className="text-xs text-slate-500">
              Temperature
            </p>

            <p className="text-2xl font-bold text-slate-800">
              {lastReading.sensors?.temperature != null
                ? `${Number(lastReading.sensors.temperature).toFixed(1)} °C`
                : '-- °C'}
            </p>
          </div>

          <div className="bg-white rounded-xl shadow p-4">
            <p className="text-xs text-slate-500">
              Humidity
            </p>

            <p className="text-2xl font-bold text-slate-800">
              {lastReading.sensors?.humidity != null
                ? `${Number(lastReading.sensors.humidity).toFixed(1)} %`
                : '-- %'}
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