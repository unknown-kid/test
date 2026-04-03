import { useState, useEffect, useRef } from 'react'
import { createPortal } from 'react-dom'
import { Button, Input, Space } from 'antd'
import {
  CopyOutlined, HighlightOutlined, FormOutlined,
  TranslationOutlined, RobotOutlined, CheckOutlined,
} from '@ant-design/icons'

interface SelectionPopoverProps {
  visible: boolean
  position: { top: number; left: number }
  selectedText: string
  onCopy: () => void
  onHighlight: () => void
  onAnnotate: (comment: string) => void
  onTranslate: () => void
  onAskAI: () => void
  onClose: () => void
}

export default function SelectionPopover({
  visible, position, selectedText, onCopy, onHighlight, onAnnotate, onTranslate, onAskAI, onClose,
}: SelectionPopoverProps) {
  const [annotateMode, setAnnotateMode] = useState(false)
  const [comment, setComment] = useState('')
  const popoverRef = useRef<HTMLDivElement>(null)

  // Reset on close
  useEffect(() => {
    if (!visible) {
      setAnnotateMode(false)
      setComment('')
    }
  }, [visible])

  // Dismiss on click outside, scroll, escape
  useEffect(() => {
    if (!visible) return

    const handleClickOutside = (e: MouseEvent) => {
      if (popoverRef.current && !popoverRef.current.contains(e.target as Node)) {
        onClose()
      }
    }
    const handleScroll = () => onClose()
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }

    // Delay to avoid immediate dismiss from the mouseup that triggered the popover
    const timer = setTimeout(() => {
      document.addEventListener('mousedown', handleClickOutside)
      document.addEventListener('keydown', handleKeyDown)
    }, 100)

    // Listen for scroll on the PDF container
    const pdfContainer = document.querySelector('[data-pdf-container]')
    pdfContainer?.addEventListener('scroll', handleScroll)

    return () => {
      clearTimeout(timer)
      document.removeEventListener('mousedown', handleClickOutside)
      document.removeEventListener('keydown', handleKeyDown)
      pdfContainer?.removeEventListener('scroll', handleScroll)
    }
  }, [visible, onClose])

  if (!visible) return null

  const style: React.CSSProperties = {
    position: 'fixed',
    top: position.top - 48,
    left: Math.max(8, position.left),
    zIndex: 1000,
    background: '#fff',
    borderRadius: 8,
    boxShadow: '0 4px 16px rgba(0,0,0,0.2)',
    padding: annotateMode ? '8px 12px' : '4px 8px',
    display: 'flex',
    flexDirection: 'column',
    gap: 6,
  }

  const handleAnnotateConfirm = () => {
    if (comment.trim()) {
      onAnnotate(comment.trim())
      setAnnotateMode(false)
      setComment('')
    }
  }

  return createPortal(
    <div ref={popoverRef} style={style}>
      <Space size={2}>
        <Button type="text" size="small" icon={<CopyOutlined />} onClick={onCopy} title="复制" />
        <Button type="text" size="small" icon={<HighlightOutlined />} onClick={onHighlight} title="高亮"
          style={{ color: '#f5a623' }} />
        <Button type="text" size="small" icon={<FormOutlined />} onClick={() => setAnnotateMode(!annotateMode)}
          title="批注" style={{ color: '#2196f3' }} />
        <Button type="text" size="small" icon={<TranslationOutlined />} onClick={onTranslate} title="翻译" />
        <Button type="text" size="small" icon={<RobotOutlined />} onClick={onAskAI} title="问AI"
          style={{ color: '#52c41a' }} />
      </Space>
      {annotateMode && (
        <div style={{ display: 'flex', gap: 4, marginTop: 2 }}>
          <Input
            size="small"
            placeholder="输入批注内容..."
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            onPressEnter={handleAnnotateConfirm}
            autoFocus
            style={{ width: 180 }}
          />
          <Button size="small" type="primary" icon={<CheckOutlined />} onClick={handleAnnotateConfirm} />
        </div>
      )}
    </div>,
    document.body
  )
}
