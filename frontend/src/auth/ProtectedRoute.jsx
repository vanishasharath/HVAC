import { Navigate } from 'react-router-dom'
import { useAuth } from './AuthContext'

function ProtectedRoute({ children, allowedRoles }) {
  const { user } = useAuth()

  if (!user) {
    return <Navigate to="/login" replace />
  }

  if (allowedRoles && !allowedRoles.includes(user.role)) {
    return <Navigate to="/dashboard" replace />
  }

  return children
}

export default ProtectedRoute