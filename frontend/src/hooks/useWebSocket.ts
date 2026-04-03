import { useEffect, useRef, useCallback } from 'react'
import { useNotifyStore } from '../stores/notifyStore'

export function useWebSocket() {
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const shouldReconnectRef = useRef(true)
  const addNotification = useNotifyStore((s) => s.addNotification)

  const connect = useCallback(() => {
    if (!shouldReconnectRef.current) return
    const token = localStorage.getItem('access_token')
    if (!token) return

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const ws = new WebSocket(`${protocol}//${window.location.host}/api/notify/ws?token=${token}`)

    ws.onopen = () => {
      // Send ping every 30s to keep alive
      const pingInterval = setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) ws.send('ping')
      }, 30000)
      ws.addEventListener('close', () => clearInterval(pingInterval))
    }

    ws.onmessage = (event) => {
      if (event.data === 'pong') return
      try {
        const data = JSON.parse(event.data)
        addNotification({
          id: data.id || `ws-${Date.now()}`,
          user_id: data.user_id,
          type: data.type,
          content: data.content || JSON.stringify(data),
          is_read: false,
          created_at: new Date().toISOString(),
        })
      } catch { /* ignore */ }
    }

    ws.onclose = () => {
      wsRef.current = null
      if (!shouldReconnectRef.current) return
      // Auto reconnect after 3s
      reconnectTimer.current = setTimeout(connect, 3000)
    }

    ws.onerror = () => {
      ws.close()
    }

    wsRef.current = ws
  }, [addNotification])

  useEffect(() => {
    shouldReconnectRef.current = true
    connect()
    return () => {
      shouldReconnectRef.current = false
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current)
      if (wsRef.current) wsRef.current.close()
    }
  }, [connect])

  return wsRef
}
