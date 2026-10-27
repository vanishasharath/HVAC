import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
} from 'recharts'

function SensorChart({
  data,
  dataKey,
  label,
  color = '#2563eb',
  unit = '',
  criticalThreshold = null,
  thresholdLabel = 'Critical Limit',
  xAxisKey = 'time',
}) {
  const effectiveXKey =
    xAxisKey === 'simTime' && data && data.length > 0 && data[data.length - 1]?.simTime
      ? 'simTime'
      : 'time'

  return (
    <div className="bg-white rounded-xl shadow p-4">
      <div className="flex justify-between items-center mb-2">
        <h3 className="text-sm font-semibold text-slate-600">{label}</h3>
        {unit && (
          <span className="text-[11px] font-medium text-slate-400 bg-slate-100 px-2 py-0.5 rounded">
            Unit: {unit}
          </span>
        )}
      </div>

      <ResponsiveContainer width="100%" height={220}>
        <LineChart data={data} margin={{ top: 10, right: 10, left: -15, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis
            dataKey={effectiveXKey}
            tick={{ fontSize: 10 }}
            interval="preserveStartEnd"
          />
          <YAxis tick={{ fontSize: 10 }} domain={['auto', 'auto']} />
          <Tooltip
            contentStyle={{
              backgroundColor: '#1e293b',
              borderRadius: '8px',
              border: 'none',
              color: '#fff',
              fontSize: '12px',
            }}
            formatter={(val) => [`${Number(val).toFixed(1)} ${unit}`.trim(), label]}
            labelFormatter={(labelVal, items) => {
              const payload = items?.[0]?.payload
              if (payload?.fullTime) return payload.fullTime
              return `Time: ${labelVal}`
            }}
          />
          {criticalThreshold != null && (
            <ReferenceLine
              y={criticalThreshold}
              stroke="#ef4444"
              strokeDasharray="4 4"
              label={{
                value: thresholdLabel,
                position: 'top',
                fill: '#ef4444',
                fontSize: 10,
                fontWeight: 600,
              }}
            />
          )}
          <Line
            type="monotone"
            dataKey={dataKey}
            stroke={color}
            dot={false}
            strokeWidth={2}
            isAnimationActive={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}

export default SensorChart