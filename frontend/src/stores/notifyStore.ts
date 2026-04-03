import { create } from 'zustand'
import { notifyApi, type NotificationInfo } from '../api/notify'

interface NotifyState {
  notifications: NotificationInfo[]
  unreadCount: number
  loading: boolean
  fetchNotifications: () => Promise<void>
  addNotification: (n: NotificationInfo) => void
  markAsRead: (id: string) => Promise<void>
  markAllRead: () => Promise<void>
  removeNotification: (id: string) => Promise<void>
}

export const useNotifyStore = create<NotifyState>((set, get) => ({
  notifications: [],
  unreadCount: 0,
  loading: false,

  fetchNotifications: async () => {
    set({ loading: true })
    try {
      const res = await notifyApi.getNotifications()
      const notifications = res.data
      set({
        notifications,
        unreadCount: notifications.filter((n) => !n.is_read).length,
      })
    } catch { /* ignore */ }
    finally { set({ loading: false }) }
  },

  addNotification: (n) => {
    set((state) => {
      const existingIndex = state.notifications.findIndex((item) => item.id === n.id)
      if (existingIndex >= 0) {
        const prev = state.notifications[existingIndex]
        const nextNotifications = [...state.notifications]
        nextNotifications[existingIndex] = { ...prev, ...n }
        const unreadCount = nextNotifications.filter((item) => !item.is_read).length
        return {
          notifications: nextNotifications,
          unreadCount,
        }
      }

      return {
        notifications: [n, ...state.notifications],
        unreadCount: state.unreadCount + (n.is_read ? 0 : 1),
      }
    })
  },

  markAsRead: async (id) => {
    try {
      await notifyApi.markAsRead(id)
      set((state) => ({
        notifications: state.notifications.map((n) => n.id === id ? { ...n, is_read: true } : n),
        unreadCount: Math.max(0, state.unreadCount - 1),
      }))
    } catch { /* ignore */ }
  },

  markAllRead: async () => {
    try {
      await notifyApi.markAllRead()
      set((state) => ({
        notifications: state.notifications.map((n) => ({ ...n, is_read: true })),
        unreadCount: 0,
      }))
    } catch { /* ignore */ }
  },

  removeNotification: async (id) => {
    try {
      const n = get().notifications.find((n) => n.id === id)
      await notifyApi.deleteNotification(id)
      set((state) => ({
        notifications: state.notifications.filter((n) => n.id !== id),
        unreadCount: n && !n.is_read ? Math.max(0, state.unreadCount - 1) : state.unreadCount,
      }))
    } catch { /* ignore */ }
  },
}))
