import { useState } from 'react'
import { useNavigate, Link } from 'react-router-dom'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL

function Register() {
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [role, setRole] = useState('TECHNICIAN')
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [loading, setLoading] = useState(false)

  const navigate = useNavigate()

  const handleSubmit = async (e) => {
    e.preventDefault()
    setError('')
    setSuccess('')
    setLoading(true)

    try {
      const response = await fetch(`${API_BASE_URL}/api/v1/auth/register`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          email,
          password,
          full_name: name,
          role,
        }),
      })

      const data = await response.json()

      if (!response.ok) {
        throw new Error(
          data?.detail || data?.error?.message || 'Registration failed.'
        )
      }

      setSuccess('Account created successfully! Redirecting to login...')

      setTimeout(() => {
        navigate('/login')
      }, 1000)
    } catch (error) {
      setError(error.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-slate-900 flex items-center justify-center">
      <form
        onSubmit={handleSubmit}
        className="bg-white rounded-xl shadow-lg p-8 w-80 space-y-4"
      >
        <h1 className="text-xl font-bold text-slate-800">
          Create Account
        </h1>

        {error && (
          <p className="text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg p-2">
            {error}
          </p>
        )}

        {success && (
          <p className="text-sm text-green-600 bg-green-50 border border-green-200 rounded-lg p-2">
            {success}
          </p>
        )}

        <div>
          <label className="block text-sm text-slate-600 mb-1">
            Name
          </label>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="w-full border border-slate-300 rounded-lg px-3 py-2"
            placeholder="Your name"
            required
          />
        </div>

        <div>
          <label className="block text-sm text-slate-600 mb-1">
            Email
          </label>
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="w-full border border-slate-300 rounded-lg px-3 py-2"
            placeholder="you@example.com"
            required
          />
        </div>

        <div>
          <label className="block text-sm text-slate-600 mb-1">
            Password
          </label>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="w-full border border-slate-300 rounded-lg px-3 py-2"
            placeholder="••••••••"
            minLength={8}
            required
          />
        </div>

        <div>
          <label className="block text-sm text-slate-600 mb-1">
            Role
          </label>
          <select
            value={role}
            onChange={(e) => setRole(e.target.value)}
            className="w-full border border-slate-300 rounded-lg px-3 py-2"
          >
            <option value="FACILITY_MANAGER">Facility Manager</option>
            <option value="TECHNICIAN">Technician</option>
          </select>
        </div>

        <button
          type="submit"
          disabled={loading}
          className="w-full bg-blue-600 text-white font-medium rounded-lg py-2 hover:bg-blue-700 disabled:opacity-50"
        >
          {loading ? 'Creating Account...' : 'Register'}
        </button>

        <p className="text-sm text-center text-slate-500">
          Already have an account?{' '}
          <Link
            to="/login"
            className="text-blue-600 hover:underline"
          >
            Log in
          </Link>
        </p>
      </form>
    </div>
  )
}

export default Register