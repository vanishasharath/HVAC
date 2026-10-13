import { createContext, useContext, useState } from 'react'

const AuthContext = createContext(null)

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL

export function AuthProvider({ children }) {
  const [user, setUser] = useState(() => {
    const savedUser = localStorage.getItem('hvac_user')
    return savedUser ? JSON.parse(savedUser) : null
  })

  const [token, setToken] = useState(() => {
    return localStorage.getItem('hvac_token')
  })

  const login = async (email, password) => {
    const formData = new URLSearchParams()
    formData.append('username', email)
    formData.append('password', password)

    const response = await fetch(`${API_BASE_URL}/api/v1/auth/login`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/x-www-form-urlencoded',
      },
      body: formData,
    })

    const data = await response.json()

    if (!response.ok) {
      throw new Error(
        data?.error?.message || data?.detail || 'Login failed'
      )
    }

    const accessToken = data.access_token

    const meResponse = await fetch(`${API_BASE_URL}/api/v1/auth/me`, {
      headers: {
        Authorization: `Bearer ${accessToken}`,
      },
    })

    const meData = await meResponse.json()

    if (!meResponse.ok) {
      throw new Error(
        meData?.error?.message || meData?.detail || 'Could not get user information'
      )
    }

    setToken(accessToken)
    setUser(meData)

    localStorage.setItem('hvac_token', accessToken)
    localStorage.setItem('hvac_user', JSON.stringify(meData))
  }

  const logout = () => {
    setUser(null)
    setToken(null)
    localStorage.removeItem('hvac_token')
    localStorage.removeItem('hvac_user')
  }

  return (
    <AuthContext.Provider value={{ user, token, login, logout }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  return useContext(AuthContext)
}