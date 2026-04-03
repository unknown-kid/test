import { useNavigate, useLocation, Outlet } from 'react-router-dom'
import { Layout, Menu, Button } from 'antd'
import {
  DashboardOutlined, FileOutlined, SettingOutlined, ApiOutlined,
  TeamOutlined, UnorderedListOutlined, LockOutlined, ToolOutlined, LogoutOutlined,
} from '@ant-design/icons'
import { useAuthStore } from '../../stores/authStore'

const { Sider, Content, Header } = Layout

const menuItems = [
  { key: '/admin/dashboard', icon: <DashboardOutlined />, label: '仪表盘' },
  { key: '/admin/papers', icon: <FileOutlined />, label: '共享区论文' },
  { key: '/admin/users', icon: <TeamOutlined />, label: '用户管理' },
  { key: '/admin/config', icon: <SettingOutlined />, label: '系统配置' },
  { key: '/admin/models', icon: <ApiOutlined />, label: '模型配置' },
  { key: '/admin/tasks', icon: <UnorderedListOutlined />, label: '任务看板' },
  { key: '/admin/maintenance', icon: <ToolOutlined />, label: '维护模式' },
  { key: '/admin/password', icon: <LockOutlined />, label: '修改密码' },
]

export default function AdminLayout() {
  const navigate = useNavigate()
  const location = useLocation()
  const { logout } = useAuthStore()
  const isAdminPaperDetail = location.pathname.startsWith('/admin/papers/') && location.pathname !== '/admin/papers'

  const handleLogout = async () => {
    await logout()
    navigate('/admin/login')
  }

  return (
    <Layout style={isAdminPaperDetail ? { height: '100%', overflow: 'hidden' } : { minHeight: '100vh' }}>
      <Sider width={200} style={{ background: '#001529' }}>
        <div style={{ height: 48, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#fff', fontWeight: 600, fontSize: 16 }}>
          管理后台
        </div>
        <Menu
          theme="dark"
          mode="inline"
          selectedKeys={[location.pathname]}
          items={menuItems}
          onClick={({ key }) => navigate(key)}
        />
      </Sider>
      <Layout style={isAdminPaperDetail ? { height: '100%', overflow: 'hidden' } : undefined}>
        <Header style={{ background: '#fff', padding: '0 24px', display: 'flex', justifyContent: 'flex-end', alignItems: 'center', borderBottom: '1px solid #f0f0f0' }}>
          <Button size="small" icon={<LogoutOutlined />} onClick={handleLogout}>退出</Button>
        </Header>
        <Content
          style={{
            margin: 0,
            ...(isAdminPaperDetail
              ? { flex: 1, minHeight: 0, overflow: 'hidden', overscrollBehavior: 'none' }
              : { minHeight: 280, overflow: 'auto' }),
          }}
        >
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  )
}
