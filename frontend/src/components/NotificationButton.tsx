import { useEffect, useState } from 'react'
import { Badge, Button, Popover, List, Typography, Space } from 'antd'
import { BellOutlined, CheckOutlined, DeleteOutlined } from '@ant-design/icons'
import { useNotifyStore } from '../stores/notifyStore'
import { useWebSocket } from '../hooks/useWebSocket'
import dayjs from 'dayjs'

const { Text } = Typography

export default function NotificationButton() {
  const { notifications, unreadCount, fetchNotifications, markAsRead, markAllRead, removeNotification } = useNotifyStore()
  const [open, setOpen] = useState(false)

  // Connect WebSocket
  useWebSocket()

  // Load notifications on mount
  useEffect(() => {
    fetchNotifications()
  }, [])

  const content = (
    <div style={{ width: 320, maxHeight: 400, overflow: 'auto' }}>
      {notifications.length > 0 && (
        <div style={{ textAlign: 'right', marginBottom: 8 }}>
          <Button type="link" size="small" onClick={markAllRead}>全部已读</Button>
        </div>
      )}
      <List
        dataSource={notifications.slice(0, 30)}
        locale={{ emptyText: '暂无通知' }}
        renderItem={(item) => (
          <List.Item
            style={{ background: item.is_read ? undefined : '#f0f5ff', padding: '8px 12px' }}
            actions={[
              !item.is_read && (
                <Button type="text" size="small" icon={<CheckOutlined />} onClick={() => markAsRead(item.id)} />
              ),
              <Button type="text" size="small" danger icon={<DeleteOutlined />} onClick={() => removeNotification(item.id)} />,
            ].filter(Boolean)}
          >
            <List.Item.Meta
              title={<Text style={{ fontSize: 13 }}>{item.content}</Text>}
              description={<Text type="secondary" style={{ fontSize: 11 }}>{dayjs(item.created_at).format('MM-DD HH:mm')}</Text>}
            />
          </List.Item>
        )}
      />
    </div>
  )

  return (
    <Popover
      content={content}
      title="通知"
      trigger="click"
      open={open}
      onOpenChange={setOpen}
      placement="bottomRight"
    >
      <Badge count={unreadCount} size="small" offset={[-2, 2]}>
        <Button type="text" icon={<BellOutlined />} />
      </Badge>
    </Popover>
  )
}
