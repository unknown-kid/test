import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Input, Spin, Typography, Button } from 'antd'
import { DeleteOutlined } from '@ant-design/icons'
import { translateApi } from '../api/translate'

const { TextArea } = Input
const { Text } = Typography

interface Props {
  open: boolean
  initialText?: string
  onClose: () => void
}

export default function TranslateDialog({ open, initialText = '', onClose }: Props) {
  const [loading, setLoading] = useState(false)
  const [translated, setTranslated] = useState('')
  const [sourceText, setSourceText] = useState('')
  const [position, setPosition] = useState({ x: 36, y: 84 })
  const draggingRef = useRef(false)
  const dragStartRef = useRef({ x: 0, y: 0 })
  const panelStartRef = useRef({ x: 0, y: 0 })
  const lastRequestedRef = useRef('')

  const normalizeSourceText = (text: string) => {
    return (text || '')
      .replace(/\r/g, ' ')
      .replace(/\n+/g, ' ')
      .replace(/\s{2,}/g, ' ')
      .trim()
  }

  const handleTranslate = async (text: string) => {
    if (!text.trim()) return
    setLoading(true)
    try {
      const res = await translateApi.translate(text)
      setTranslated(res.data.translated)
    } catch {
      setTranslated('翻译失败，请重试')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (!open) return
    const text = normalizeSourceText(initialText)
    if (!text) return
    if (text === lastRequestedRef.current) return
    lastRequestedRef.current = text
    setSourceText(text)
    setTranslated('')
    handleTranslate(text)
  }, [open, initialText])

  useEffect(() => {
    if (!open) return

    const onMouseMove = (e: MouseEvent) => {
      if (!draggingRef.current) return
      const deltaX = e.clientX - dragStartRef.current.x
      const deltaY = e.clientY - dragStartRef.current.y
      const nextX = Math.max(8, panelStartRef.current.x + deltaX)
      const nextY = Math.max(8, panelStartRef.current.y + deltaY)
      setPosition({ x: nextX, y: nextY })
    }

    const onMouseUp = () => {
      draggingRef.current = false
      document.body.style.userSelect = ''
      document.body.style.cursor = ''
    }

    document.addEventListener('mousemove', onMouseMove)
    document.addEventListener('mouseup', onMouseUp)
    return () => {
      document.removeEventListener('mousemove', onMouseMove)
      document.removeEventListener('mouseup', onMouseUp)
      document.body.style.userSelect = ''
      document.body.style.cursor = ''
    }
  }, [open])

  if (!open) return null

  return createPortal(
    <div
      style={{
        position: 'fixed',
        top: position.y,
        left: position.x,
        width: 416,
        maxWidth: 'min(416px, calc(100vw - 24px))',
        background: '#fff',
        border: '1px solid #d9d9d9',
        borderRadius: 8,
        boxShadow: '0 8px 24px rgba(0,0,0,0.15)',
        zIndex: 2100,
      }}
    >
      <div
        onMouseDown={(e) => {
          draggingRef.current = true
          dragStartRef.current = { x: e.clientX, y: e.clientY }
          panelStartRef.current = position
          document.body.style.userSelect = 'none'
          document.body.style.cursor = 'move'
        }}
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '8px 10px',
          borderBottom: '1px solid #f0f0f0',
          cursor: 'move',
        }}
      >
        <Text strong>翻译</Text>
        <Button
          size="small"
          type="text"
          icon={<DeleteOutlined />}
          onClick={onClose}
          title="关闭"
        />
      </div>
      <div style={{ padding: 10 }}>
        <div style={{ marginBottom: 10 }}>
          <Text type="secondary" style={{ fontSize: 12 }}>原文</Text>
          <TextArea rows={4} value={sourceText} readOnly style={{ marginTop: 4 }} />
        </div>
        <div>
          <Text type="secondary" style={{ fontSize: 12 }}>译文</Text>
          {loading ? (
            <div style={{ textAlign: 'center', padding: 24 }}><Spin /></div>
          ) : (
            <TextArea rows={6} value={translated} readOnly style={{ marginTop: 4 }} />
          )}
        </div>
      </div>
    </div>,
    document.body,
  )
}
