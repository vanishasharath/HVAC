import { useState } from 'react'
import { useAuth } from '../auth/AuthContext'

const initialUsers = [
  { id: 1, name: 'Dhruvi V', email: 'dhruvi@example.com', role: 'Admin' },
  { id: 2, name: 'Rishika C Datta', email: 'rishika@example.com', role: 'Technician' },
  { id: 3, name: 'Swetha R', email: 'swetha@example.com', role: 'Facility Manager' },
  { id: 4, name: 'Vanisha Sharath', email: 'vanisha@example.com', role: 'Technician' },
]

const initialUnits = [
  { id: 1, name: 'HVAC-01', location: 'Rooftop A', gasThreshold: 30 },
  { id: 2, name: 'HVAC-02', location: 'Basement Plant Room', gasThreshold: 25 },
]

function AdminUsers() {
  const { user, logout } = useAuth()
  const [users, setUsers] = useState(initialUsers)
  const [units, setUnits] = useState(initialUnits)

  const removeUser = (id) => {
    setUsers((prev) => prev.filter((u) => u.id !== id))
  }

  return (
    <div className="min-h-screen bg-slate-100 p-6">
      <div className="flex justify-between items-center mb-6">
        <h1 className="text-2xl font-bold text-slate-800">Admin Panel</h1>
        <div className="flex items-center gap-4">
          <span className="text-sm text-slate-600">
            {user?.email} — {user?.role}
          </span>
          <button
            onClick={logout}
            className="bg-red-500 text-white text-sm px-3 py-1.5 rounded-lg hover:bg-red-600"
          >
            Log Out
          </button>
        </div>
      </div>

      <div className="bg-white rounded-xl shadow p-4 mb-4">
        <h2 className="text-sm font-semibold text-slate-600 mb-3">Manage Users</h2>
        <table className="w-full text-sm text-left">
          <thead>
            <tr className="text-slate-500 border-b">
              <th className="py-2">Name</th>
              <th className="py-2">Email</th>
              <th className="py-2">Role</th>
              <th className="py-2"></th>
            </tr>
          </thead>
          <tbody>
            {users.map((u) => (
              <tr key={u.id} className="border-b last:border-0">
                <td className="py-2">{u.name}</td>
                <td className="py-2">{u.email}</td>
                <td className="py-2">{u.role}</td>
                <td className="py-2">
                  <button
                    onClick={() => removeUser(u.id)}
                    className="text-red-500 text-xs hover:underline"
                  >
                    Remove
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="bg-white rounded-xl shadow p-4">
        <h2 className="text-sm font-semibold text-slate-600 mb-3">Configure HVAC Units</h2>
        <table className="w-full text-sm text-left">
          <thead>
            <tr className="text-slate-500 border-b">
              <th className="py-2">Unit</th>
              <th className="py-2">Location</th>
              <th className="py-2">Gas Threshold (ppm)</th>
            </tr>
          </thead>
          <tbody>
            {units.map((unit) => (
              <tr key={unit.id} className="border-b last:border-0">
                <td className="py-2">{unit.name}</td>
                <td className="py-2">{unit.location}</td>
                <td className="py-2">{unit.gasThreshold}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

export default AdminUsers