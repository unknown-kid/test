import { useEffect, useState } from 'react'
import { Card, Switch, Typography, message, Spin, Alert } from 'antd'
import { adminApi } from '../../api/admin'

const { Text } = Typography

export default function Maintenance() {
  const [maintenance, setMaintenance] = useState(false)
  const [loading, setLoading] = useState(true)
  const [toggling, setToggling] = useState(false)

  useEffect(() => {
    adminApi.getMaintenanceStatus()
      .then((res) => setMaintenance(res.data.maintenance))
      .finally(() => setLoading(false))
  }, [])

  const handleToggle = async (checked: boolean) => {
    setToggling(true)
    try {
      if (checked) {
        await adminApi.enableMaintenance()
        message.success('维护模式已开启')
      } else {
        await adminApi.disableMaintenance()
        message.success('维护模式已关闭')
      }
      setMaintenance(checked)
    } catch (err: any) {
      message.error('操作失败')
    } finally {
      setToggling(false)
    }
  }

  if (loading) return <div style={{ textAlign: 'center', padding: 80 }}><Spin size="large" /></div>

  return (
    <div style={{ padding: 24, maxWidth: 500 }}>
      <Card title="维护模式">
        {maintenance && (
          <Alert type="warning" message="维护模式已开启，所有普通用户无法访问系统" style={{ marginBottom: 16 }} showIcon />
        )}
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <Text>维护模式</Text>
          <Switch checked={maintenance} onChange={handleToggle} loading={toggling} />
          <Text type="secondary" style={{ fontSize: 12 }}>
            {maintenance ? '已开启 - 用户已被强制登出' : '已关闭 - 系统正常运行'}
          </Text>
        </div>
      </Card>
    </div>
  )
}
