import { useEffect, useRef, type ReactNode } from 'react'
import { Navigate, useLocation } from 'react-router-dom'
import { Spin } from 'antd'
import { useAuthStore } from '../stores/authStore'

interface Props {
  children: ReactNode
  requiredRole?: 'admin' | 'user'
}

export default function ProtectedRoute({ children, requiredRole }: Props) {
  const { user, loading, fetchUser } = useAuthStore()
  const location = useLocation()
  const token = localStorage.getItem('access_token')
  const requestedRef = useRef(false)

  useEffect(() => {
    if (!token) {
      requestedRef.current = false
      return
    }

    if (user) {
      requestedRef.current = false
      return
    }

    if (!requestedRef.current) {
      requestedRef.current = true
      fetchUser()
    }
  }, [token, user, fetchUser])

  if (!token) {
    const target = requiredRole === 'admin' ? '/admin/login' : '/login'
    return <Navigate to={target} state={{ from: location }} replace />
  }

  if (loading || !user) {
    return <div style={{ display: 'flex', justifyContent: 'center', paddingTop: 200 }}><Spin size="large" /></div>
  }

  if (requiredRole && user.role !== requiredRole) {
    return <Navigate to={user.role === 'admin' ? '/admin/dashboard' : '/papers/my'} replace />
  }

  return <>{children}</>
}
