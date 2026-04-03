import { useState, useEffect, useRef } from 'react'
import { List, Input, Button, Space, Drawer, Popconfirm, Switch, Typography, message, Spin } from 'antd'
import { PlusOutlined, DeleteOutlined, SendOutlined, MenuOutlined, LoadingOutlined } from '@ant-design/icons'
import { chatApi, streamChat, type ChatSession, type ChatMessage } from '../api/chat'
import SafeMarkdown from './SafeMarkdown'

const { Text } = Typography
const { TextArea } = Input
const streamingIcon = <LoadingOutlined style={{ fontSize: 16 }} spin />

interface Props {
  paperId: string
  sourceType?: string
  sourceText?: string
  askAiRequest?: {
    selectedText: string
    question: string
    counter: number
  }
}

export default function ChatPanel({ paperId, sourceType, sourceText, askAiRequest }: Props) {
  const [sessions, setSessions] = useState<ChatSession[]>([])
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [input, setInput] = useState('')
  const [streaming, setStreaming] = useState(false)
  const [streamContent, setStreamContent] = useState('')
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [includeReport, setIncludeReport] = useState(false)
  const [clearing, setClearing] = useState(false)
  const abortRef = useRef<AbortController | null>(null)
  const messageListRef = useRef<HTMLDivElement>(null)
  const shouldAutoScrollRef = useRef(true)
  const BOTTOM_LOCK_THRESHOLD = 8

  const isNearBottom = () => {
    const el = messageListRef.current
    if (!el) return true
    return el.scrollHeight - el.scrollTop - el.clientHeight <= BOTTOM_LOCK_THRESHOLD
  }

  useEffect(() => {
    setActiveSessionId(null)
    setMessages([])
    setStreamContent('')
    setInput('')
    abortRef.current?.abort()
    setStreaming(false)
    shouldAutoScrollRef.current = true
    loadSessions()
  }, [paperId])

  useEffect(() => {
    if (activeSessionId) loadMessages(activeSessionId)
  }, [activeSessionId])

  useEffect(() => {
    return () => {
      abortRef.current?.abort()
    }
  }, [])

  useEffect(() => {
    if (!shouldAutoScrollRef.current) return
    const el = messageListRef.current
    if (!el) return
    el.scrollTop = el.scrollHeight
  }, [messages, streamContent, streaming])

  const sendMessage = (sessionId: string, rawContent: string) => {
    const content = rawContent.trim()
    if (!content || streaming) return

    shouldAutoScrollRef.current = true
    setStreaming(true)
    setStreamContent('')

    const tempUserMsg: ChatMessage = {
      id: `temp-${Date.now()}`,
      session_id: sessionId,
      role: 'user',
      content,
      context_chunks: null,
      created_at: new Date().toISOString(),
    }
    setMessages((prev) => [...prev, tempUserMsg])

    let fullResponse = ''
    abortRef.current = streamChat(
      sessionId, paperId, content, includeReport,
      (chunk) => {
        fullResponse += chunk
        setStreamContent(fullResponse)
      },
      () => {
        setStreaming(false)
        setStreamContent('')
        loadMessages(sessionId)
        loadSessions()
      },
      (err) => {
        setStreaming(false)
        setStreamContent('')
        loadMessages(sessionId)
        loadSessions()
        message.error(err)
      },
    )
  }

  const buildAskAiMessage = (selectedText: string, question: string) => {
    return [
      '下面是我在论文中划选的一段内容，请结合该段内容回答我的问题。',
      '',
      '【划词内容】',
      selectedText,
      '',
      '【我的问题】',
      question,
    ].join('\n')
  }

  // Auto-create ask_ai session and send first question
  useEffect(() => {
    if (!askAiRequest || !askAiRequest.counter) return
    if (!askAiRequest.selectedText?.trim() || !askAiRequest.question?.trim()) return

    const createAskAiSession = async () => {
      if (streaming) {
        message.warning('当前正在生成回复，请稍后再提问')
        return
      }
      try {
        const res = await chatApi.createSession(paperId, 'ask_ai', askAiRequest.selectedText)
        setSessions((prev) => [res.data, ...prev])
        setActiveSessionId(res.data.id)
        setMessages([])
        sendMessage(res.data.id, buildAskAiMessage(askAiRequest.selectedText, askAiRequest.question))
      } catch {
        message.error('创建划词问AI会话失败')
      }
    }
    createAskAiSession()
  }, [askAiRequest?.counter])

  const loadSessions = async () => {
    try {
      const res = await chatApi.getSessions(paperId)
      setSessions(res.data)
      setActiveSessionId((current) => {
        if (current && res.data.some((session) => session.id === current)) {
          return current
        }
        return res.data[0]?.id || null
      })
    } catch { /* ignore */ }
  }

  const loadMessages = async (sessionId: string) => {
    try {
      const res = await chatApi.getMessages(sessionId)
      setMessages(res.data)
    } catch { /* ignore */ }
  }

  const handleNewSession = async () => {
    try {
      const res = await chatApi.createSession(paperId, sourceType || 'normal', sourceText)
      setSessions((prev) => [res.data, ...prev])
      setActiveSessionId(res.data.id)
      setMessages([])
    } catch (err: any) {
      message.error('创建会话失败')
    }
  }

  const handleDeleteSession = async (sessionId: string) => {
    try {
      await chatApi.deleteSession(sessionId)
      setSessions((prev) => {
        const next = prev.filter((s) => s.id !== sessionId)
        if (activeSessionId === sessionId) {
          setActiveSessionId(next[0]?.id || null)
          setMessages([])
        }
        return next
      })
    } catch { /* ignore */ }
  }

  const handleClearSessions = async () => {
    if (streaming) {
      message.warning('当前正在生成回复，请稍后再清空')
      return
    }
    setClearing(true)
    try {
      await chatApi.clearSessionsByPaper(paperId)
      setSessions([])
      setActiveSessionId(null)
      setMessages([])
      setStreamContent('')
      setDrawerOpen(false)
      shouldAutoScrollRef.current = true
      message.success('聊天记录已清空')
    } catch (err: any) {
      message.error(err.response?.data?.detail || '清空失败')
    } finally {
      setClearing(false)
    }
  }

  const handleSend = async () => {
    if (!input.trim() || !activeSessionId || streaming) return
    const content = input
    const sessionId = activeSessionId
    setInput('')
    sendMessage(sessionId, content)
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '8px 0' }}>
        <Space>
          <Button size="small" icon={<MenuOutlined />} onClick={() => setDrawerOpen(true)}>会话列表</Button>
          <Button size="small" icon={<PlusOutlined />} onClick={handleNewSession}>新建会话</Button>
          <Popconfirm
            title="确定清空当前论文的全部聊天记录吗？"
            okText="清空"
            cancelText="取消"
            okButtonProps={{ danger: true, loading: clearing }}
            onConfirm={handleClearSessions}
            disabled={sessions.length === 0 || streaming}
          >
            <Button size="small" danger icon={<DeleteOutlined />} disabled={sessions.length === 0 || streaming}>
              清空会话
            </Button>
          </Popconfirm>
        </Space>
        <Space>
          <Text style={{ fontSize: 12 }}>附加报告</Text>
          <Switch size="small" checked={includeReport} onChange={setIncludeReport} />
        </Space>
      </div>

      <div
        ref={messageListRef}
        style={{ flex: 1, overflow: 'auto', padding: '8px 0', minHeight: 200, overscrollBehavior: 'contain' }}
        onScroll={() => { shouldAutoScrollRef.current = isNearBottom() }}
        onWheel={(e) => {
          // User explicitly scrolls up: stop sticky-bottom auto-follow immediately.
          if (e.deltaY < 0) shouldAutoScrollRef.current = false
        }}
      >
        {messages.map((m) => (
          <div key={m.id} style={{
            marginBottom: 12, padding: 8, borderRadius: 6,
            background: m.role === 'user' ? '#e6f7ff' : '#f6ffed',
          }}>
            <Text type="secondary" style={{ fontSize: 11 }}>{m.role === 'user' ? '你' : 'AI'}</Text>
            <div style={{ marginTop: 4 }} className="md-content">
              <SafeMarkdown content={m.content} />
            </div>
          </div>
        ))}
        {streaming && streamContent && (
          <div style={{ marginBottom: 12, padding: 8, borderRadius: 6, background: '#f6ffed' }}>
            <Space size={6} align="center">
              <Text type="secondary" style={{ fontSize: 11 }}>AI</Text>
              <Spin indicator={streamingIcon} size="small" />
              <Text type="secondary" style={{ fontSize: 11 }}>正在生成回复</Text>
            </Space>
            <div style={{ marginTop: 4 }} className="md-content">
              <SafeMarkdown content={streamContent} />
            </div>
          </div>
        )}
        {streaming && !streamContent && (
          <div style={{ marginBottom: 12, padding: 12, borderRadius: 6, background: '#f6ffed' }}>
            <Space size={8} align="center">
              <Spin indicator={streamingIcon} size="small" />
              <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                <Text type="secondary" style={{ fontSize: 11 }}>AI</Text>
                <Text style={{ fontSize: 13 }}>正在检索论文内容并生成回复...</Text>
              </div>
            </Space>
          </div>
        )}
      </div>

      <div style={{ padding: '8px 0' }}>
        {streaming && (
          <div style={{ marginBottom: 8 }}>
            <Space size={8} align="center">
              <Spin indicator={streamingIcon} size="small" />
              <Text type="secondary" style={{ fontSize: 12 }}>
                AI 正在思考中，请稍候
              </Text>
            </Space>
          </div>
        )}
        <Space.Compact style={{ width: '100%' }}>
          <TextArea
            rows={2}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onPressEnter={(e) => { if (!e.shiftKey) { e.preventDefault(); handleSend() } }}
            placeholder={activeSessionId ? '输入消息...' : '请先创建或选择会话'}
            disabled={!activeSessionId || streaming}
          />
          <Button
            type="primary"
            icon={<SendOutlined />}
            onClick={handleSend}
            disabled={!activeSessionId || streaming || !input.trim()}
            style={{ height: 'auto' }}
          >发送</Button>
        </Space.Compact>
      </div>

      <Drawer
        title="会话列表"
        placement="left"
        onClose={() => setDrawerOpen(false)}
        open={drawerOpen}
        width={280}
      >
        <List
          dataSource={sessions}
          renderItem={(s) => (
            <List.Item
              style={{ cursor: 'pointer', background: s.id === activeSessionId ? '#e6f7ff' : undefined }}
              onClick={() => { setActiveSessionId(s.id); setDrawerOpen(false) }}
              actions={[
                <Button
                  type="text"
                  danger
                  size="small"
                  icon={<DeleteOutlined />}
                  onClick={(e) => {
                    e.stopPropagation()
                    handleDeleteSession(s.id)
                  }}
                />,
              ]}
            >
              <List.Item.Meta
                title={<span>{s.title || '新会话'} {s.source_type === 'ask_ai' ? '(划词)' : ''}</span>}
              />
            </List.Item>
          )}
        />
      </Drawer>
    </div>
  )
}
