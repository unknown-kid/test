import client from './client'

export interface NotificationInfo {
  id: string
  user_id: string
  type: string
  content: string
  is_read: boolean
  created_at: string
}

export const notifyApi = {
  getNotifications: (unreadOnly: boolean = false) =>
    client.get<NotificationInfo[]>('/notify/', { params: { unread_only: unreadOnly } }),

  markAsRead: (notificationId: string) =>
    client.post(`/notify/${notificationId}/read`),

  markAllRead: () =>
    client.post('/notify/read-all'),

  deleteNotification: (notificationId: string) =>
    client.delete(`/notify/${notificationId}`),
}
