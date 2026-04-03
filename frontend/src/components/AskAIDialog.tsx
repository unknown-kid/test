import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Input, Typography, Button } from 'antd'
import { DeleteOutlined, SendOutlined } from '@ant-design/icons'

const { TextArea } = Input
const { Text } = Typography

interface Props {
  open: boolean
  selectedText: string
  question: string
  onQuestionChange: (value: string) => void
  onAsk: () => void
  onClose: () => void
}

export default function AskAIDialog({
  open,
  selectedText,
  question,
  onQuestionChange,
  onAsk,
  onClose,
}: Props) {
  const [position, setPosition] = useState({ x: 468, y: 84 })
  const draggingRef = useRef(false)
  const dragStartRef = useRef({ x: 0, y: 0 })
  const panelStartRef = useRef({ x: 0, y: 0 })

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
        <Text strong>划词问AI</Text>
        <Button size="small" type="text" icon={<DeleteOutlined />} onClick={onClose} title="关闭" />
      </div>

      <div style={{ padding: 10 }}>
        <div style={{ marginBottom: 10 }}>
          <Text type="secondary" style={{ fontSize: 12 }}>划词内容</Text>
          <TextArea rows={4} value={selectedText} readOnly style={{ marginTop: 4 }} />
        </div>

        <div style={{ marginBottom: 10 }}>
          <Text type="secondary" style={{ fontSize: 12 }}>你的问题</Text>
          <TextArea
            rows={4}
            value={question}
            onChange={(e) => onQuestionChange(e.target.value)}
            placeholder="请输入你对这段内容的疑问..."
            style={{ marginTop: 4 }}
            onPressEnter={(e) => {
              if (!e.shiftKey) {
                e.preventDefault()
                onAsk()
              }
            }}
          />
        </div>

        <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
          <Button type="primary" icon={<SendOutlined />} onClick={onAsk}>
            提问
          </Button>
        </div>
      </div>
    </div>,
    document.body,
  )
}

