import { useEffect, useState } from 'react'
import { Table, Button, Space, Tag, Popconfirm, message, Select } from 'antd'
import { CheckOutlined, CloseOutlined, DeleteOutlined } from '@ant-design/icons'
import { adminApi, type UserListItem } from '../../api/admin'
import dayjs from 'dayjs'

export default function Users() {
  const [users, setUsers] = useState<UserListItem[]>([])
  const [loading, setLoading] = useState(false)
  const [filter, setFilter] = useState<string | undefined>(undefined)

  const loadUsers = async () => {
    setLoading(true)
    try {
      const res = await adminApi.getUsers(filter)
      setUsers(res.data)
    } catch { /* ignore */ }
    finally { setLoading(false) }
  }

  useEffect(() => { loadUsers() }, [filter])

  const handleApprove = async (userId: string, action: string) => {
    try {
      await adminApi.approveUser(userId, action)
      message.success(action === 'approve' ? '已审批通过' : '已拒绝')
      loadUsers()
    } catch (err: any) {
      message.error(err.response?.data?.detail || '操作失败')
    }
  }

  const handleRemove = async (userId: string) => {
    try {
      await adminApi.removeUser(userId)
      message.success('用户已移除')
      loadUsers()
    } catch (err: any) {
      message.error(err.response?.data?.detail || '移除失败')
    }
  }

  const columns = [
    { title: '用户名', dataIndex: 'username', key: 'username' },
    {
      title: '状态', dataIndex: 'status', key: 'status',
      render: (s: string) => <Tag color={s === 'approved' ? 'green' : 'orange'}>{s === 'approved' ? '已审批' : '待审批'}</Tag>,
    },
    {
      title: '注册时间', dataIndex: 'created_at', key: 'created_at',
      render: (t: string) => dayjs(t).format('YYYY-MM-DD HH:mm'),
    },
    {
      title: '最后登录', dataIndex: 'last_login', key: 'last_login',
      render: (t: string | null) => t ? dayjs(t).format('YYYY-MM-DD HH:mm') : '-',
    },
    {
      title: '操作', key: 'actions',
      render: (_: any, record: UserListItem) => (
        <Space>
          {record.status === 'pending' && (
            <>
              <Button size="small" type="primary" icon={<CheckOutlined />} onClick={() => handleApprove(record.id, 'approve')}>通过</Button>
              <Popconfirm title="拒绝将删除该用户，确定？" onConfirm={() => handleApprove(record.id, 'reject')}>
                <Button size="small" danger icon={<CloseOutlined />}>拒绝</Button>
              </Popconfirm>
            </>
          )}
          {record.status === 'approved' && (
            <Popconfirm
              title={`确定移除用户“${record.username}”？`}
              description="将同时删除该用户的个人区论文、报告、笔记、高亮、标注、聊天记录和通知数据，此操作不可恢复。"
              okText="确认移除"
              cancelText="取消"
              okButtonProps={{ danger: true }}
              onConfirm={() => handleRemove(record.id)}
            >
              <Button size="small" danger icon={<DeleteOutlined />}>移除</Button>
            </Popconfirm>
          )}
        </Space>
      ),
    },
  ]

  return (
    <div style={{ padding: 24 }}>
      <div style={{ marginBottom: 16 }}>
        <Select
          style={{ width: 150 }}
          placeholder="筛选状态"
          allowClear
          value={filter}
          onChange={setFilter}
          options={[
            { value: 'pending', label: '待审批' },
            { value: 'approved', label: '已审批' },
          ]}
        />
      </div>
      <Table dataSource={users} columns={columns} rowKey="id" loading={loading} pagination={{ pageSize: 20 }} />
    </div>
  )
}
