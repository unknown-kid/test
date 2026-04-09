import client from './client'

export interface ChatSession {
  id: string
  paper_id: string
  user_id: string
  title: string | null
  source_type: string
  source_text: string | null
  created_at: string
  updated_at: string
}

export interface ChatMessage {
  id: string
  session_id: string
  role: string
  content: string
  context_chunks: Record<string, any> | null
  created_at: string
}

export const chatApi = {
  createSession: (paper_id: string, source_type: string = 'normal', source_text?: string) =>
    client.post<ChatSession>('/chat/sessions', { paper_id, source_type, source_text }),

  getSessions: (paperId: string) =>
    client.get<ChatSession[]>(`/chat/sessions/${paperId}`),

  getMessages: (sessionId: string) =>
    client.get<ChatMessage[]>(`/chat/messages/${sessionId}`),

  deleteSession: (sessionId: string) =>
    client.delete(`/chat/sessions/${sessionId}`),

  clearSessionsByPaper: (paperId: string) =>
    client.delete(`/chat/sessions/paper/${paperId}`),
}

function extractText(value: any): string {
  if (typeof value === 'string') return value
  if (Array.isArray(value)) return value.map(extractText).join('')
  if (value && typeof value === 'object') {
    if (typeof value.text === 'string') return value.text
    if (typeof value.content === 'string') return value.content
    if (Array.isArray(value.content)) return value.content.map(extractText).join('')
  }
  return ''
}

function extractContent(payload: any): string {
  if (!payload || typeof payload !== 'object') return ''
  if (payload.content !== undefined) return extractText(payload.content)

  const choice = payload.choices?.[0]
  if (choice) {
    if (choice.delta?.content !== undefined) return extractText(choice.delta.content)
    if (choice.message?.content !== undefined) return extractText(choice.message.content)
    if (choice.text !== undefined) return extractText(choice.text)
  }

  if (payload.text !== undefined) return extractText(payload.text)
  return ''
}

function parseErrorMessage(raw: string): string {
  const text = raw?.trim()
  if (!text) return '请求失败'

  try {
    const parsed = JSON.parse(text)
    if (parsed?.detail) return String(parsed.detail)
    if (parsed?.message) return String(parsed.message)
    if (parsed?.error?.message) return String(parsed.error.message)
  } catch {
    // ignore
  }
  return text
}

async function refreshAccessToken(): Promise<string | null> {
  const refreshToken = localStorage.getItem('refresh_token')
  if (!refreshToken) return null

  const response = await fetch('/api/auth/refresh', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ refresh_token: refreshToken }),
  })

  if (!response.ok) return null

  const data = await response.json()
  const accessToken = data?.access_token
  const newRefreshToken = data?.refresh_token
  const role = data?.role
  if (!accessToken || !newRefreshToken) return null

  localStorage.setItem('access_token', accessToken)
  localStorage.setItem('refresh_token', newRefreshToken)
  if (role) localStorage.setItem('role', role)
  return accessToken
}

export function streamChat(
  sessionId: string, paperId: string, content: string,
  includeReport: boolean,
  onChunk: (text: string) => void,
  onDone: () => void,
  onError: (err: string) => void,
): AbortController {
  const controller = new AbortController()
  const endpoint = `/api/chat/sessions/${sessionId}/chat?paper_id=${encodeURIComponent(paperId)}&include_report=${includeReport}`

  const run = async () => {
    const sendWithToken = (token: string | null) => fetch(endpoint, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify({ content }),
      signal: controller.signal,
    })

    let token = localStorage.getItem('access_token')
    let response = await sendWithToken(token)
    if (response.status === 401) {
      token = await refreshAccessToken()
      if (!token) {
        localStorage.clear()
        window.location.href = '/login'
        onError('登录已过期，请重新登录')
        return
      }
      response = await sendWithToken(token)
    }

    if (!response.ok) {
      const errText = parseErrorMessage(await response.text())
      onError(errText || `请求失败 (${response.status})`)
      return
    }

    const reader = response.body?.getReader()
    if (!reader) {
      onError('聊天响应为空')
      return
    }

    const decoder = new TextDecoder()
    let buffer = ''
    let finished = false

    const handleData = (data: string) => {
      const payload = data.replace(/\r$/, '')
      const controlPayload = payload.trim()
      if (!controlPayload) return

      if (controlPayload === '[DONE]') {
        finished = true
        onDone()
        return
      }
      if (controlPayload.startsWith('[ERROR]')) {
        const msg = controlPayload.replace(/^\[ERROR\]\s*/, '') || '聊天失败'
        finished = true
        onError(msg)
        return
      }
      if (controlPayload.startsWith('[WARNING]')) {
        const msg = controlPayload.replace(/^\[WARNING\]\s*/, '')
        onChunk(`\n\n> ${msg}\n\n`)
        return
      }

      try {
        const parsed = JSON.parse(payload)
        const text = extractContent(parsed)
        if (text) onChunk(text)
      } catch {
        onChunk(payload)
      }
    }

    const processBuffer = (flush: boolean = false) => {
      let newlineIndex = buffer.indexOf('\n')
      while (newlineIndex >= 0) {
        const rawLine = buffer.slice(0, newlineIndex).replace(/\r$/, '')
        buffer = buffer.slice(newlineIndex + 1)

        if (rawLine.startsWith('data:')) {
          handleData(rawLine.slice(5))
        } else if (rawLine.trim().startsWith('{') || rawLine.trim().startsWith('[')) {
          handleData(rawLine)
        }
        if (finished) return
        newlineIndex = buffer.indexOf('\n')
      }

      if (flush && buffer.trim() && !finished) {
        const line = buffer.replace(/\r$/, '')
        if (line.startsWith('data:')) {
          handleData(line.slice(5))
        } else {
          handleData(line)
        }
        buffer = ''
      }
    }

    while (!finished) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      processBuffer()
    }

    if (!finished) {
      buffer += decoder.decode()
      processBuffer(true)
      if (!finished) onDone()
    }
  }

  run().catch((err: any) => {
    if (err?.name !== 'AbortError') onError(String(err))
  })

  return controller
}
