import { Routes, Route, Navigate } from 'react-router-dom'
import ProtectedRoute from './components/ProtectedRoute'
import Login from './pages/Login'
import Register from './pages/Register'
import AdminLogin from './pages/admin/AdminLogin'
import Papers from './pages/Papers'
import PaperDetail from './pages/PaperDetail'
import AdminLayout from './pages/admin/AdminLayout'
import Dashboard from './pages/admin/Dashboard'
import SharedPapers from './pages/admin/SharedPapers'
import AdminPaperDetail from './pages/admin/AdminPaperDetail'
import Config from './pages/admin/Config'
import Models from './pages/admin/Models'
import Users from './pages/admin/Users'
import Tasks from './pages/admin/Tasks'
import Password from './pages/admin/Password'
import Maintenance from './pages/admin/Maintenance'

const Placeholder = ({ name }: { name: string }) => (
  <div style={{ padding: 40, textAlign: 'center' }}>
    <h2>{name}</h2>
    <p>页面开发中...</p>
  </div>
)

export default function App() {
  return (
    <Routes>
      {/* Auth - public */}
      <Route path="/login" element={<Login />} />
      <Route path="/register" element={<Register />} />
      <Route path="/admin/login" element={<AdminLogin />} />

      {/* User pages - protected */}
      <Route path="/papers" element={<ProtectedRoute requiredRole="user"><Papers /></ProtectedRoute>} />
      <Route path="/papers/shared" element={<ProtectedRoute requiredRole="user"><Papers /></ProtectedRoute>} />
      <Route path="/papers/my" element={<ProtectedRoute requiredRole="user"><Papers /></ProtectedRoute>} />
      <Route path="/paper/:id" element={<ProtectedRoute requiredRole="user"><PaperDetail /></ProtectedRoute>} />
      <Route path="/settings" element={<ProtectedRoute requiredRole="user"><Placeholder name="用户设置" /></ProtectedRoute>} />

      {/* Admin pages - nested layout */}
      <Route path="/admin" element={<ProtectedRoute requiredRole="admin"><AdminLayout /></ProtectedRoute>}>
        <Route path="dashboard" element={<Dashboard />} />
        <Route path="papers" element={<SharedPapers />} />
        <Route path="papers/:id" element={<AdminPaperDetail />} />
        <Route path="config" element={<Config />} />
        <Route path="models" element={<Models />} />
        <Route path="users" element={<Users />} />
        <Route path="tasks" element={<Tasks />} />
        <Route path="password" element={<Password />} />
        <Route path="maintenance" element={<Maintenance />} />
        <Route index element={<Navigate to="dashboard" replace />} />
      </Route>

      {/* Default redirect */}
      <Route path="/" element={<Navigate to="/login" replace />} />
      <Route path="*" element={<Navigate to="/login" replace />} />
    </Routes>
  )
}
