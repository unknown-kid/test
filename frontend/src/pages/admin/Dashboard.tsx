import { useEffect, useState } from 'react'
import { Card, Col, Row, Statistic, Spin, Table, Tag } from 'antd'
import { UserOutlined, FileOutlined, TeamOutlined, ShareAltOutlined } from '@ant-design/icons'
import { adminApi, type AdminStats } from '../../api/admin'

export default function Dashboard() {
  const [stats, setStats] = useState<AdminStats | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    adminApi.getStats().then((res) => setStats(res.data)).finally(() => setLoading(false))
  }, [])

  if (loading) return <div style={{ textAlign: 'center', padding: 80 }}><Spin size="large" /></div>

  return (
    <div style={{ padding: 24 }}>
      <Row gutter={16}>
        <Col span={6}>
          <Card><Statistic title="总用户数" value={stats?.total_users || 0} prefix={<TeamOutlined />} /></Card>
        </Col>
        <Col span={6}>
          <Card><Statistic title="待审批用户" value={stats?.pending_users || 0} prefix={<UserOutlined />} valueStyle={stats?.pending_users ? { color: '#cf1322' } : undefined} /></Card>
        </Col>
        <Col span={6}>
          <Card><Statistic title="总论文数" value={stats?.total_papers || 0} prefix={<FileOutlined />} /></Card>
        </Col>
        <Col span={6}>
          <Card><Statistic title="共享区论文" value={stats?.shared_papers || 0} prefix={<ShareAltOutlined />} /></Card>
        </Col>
      </Row>
      <Card title="用户论文数量统计" style={{ marginTop: 16 }}>
        <Table
          rowKey="user_id"
          pagination={false}
          dataSource={stats?.user_paper_counts || []}
          columns={[
            { title: '用户名', dataIndex: 'username', key: 'username' },
            { title: '论文总数', dataIndex: 'total_papers', key: 'total_papers', sorter: (a, b) => a.total_papers - b.total_papers, defaultSortOrder: 'descend' },
            { title: '个人区论文', dataIndex: 'personal_papers', key: 'personal_papers' },
            {
              title: '失败论文',
              dataIndex: 'failed_papers',
              key: 'failed_papers',
              render: (value: number) => value > 0 ? <Tag color="error">{value}</Tag> : <Tag>{value}</Tag>,
            },
          ]}
        />
      </Card>
    </div>
  )
}
