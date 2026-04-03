import React, { Component } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import rehypeKatex from 'rehype-katex'

function sanitizeContent(content: string): string {
  if (!content) return ''
  let cleaned = content

  // Remove upstream stream noise leaked by some providers (e.g. OpenRouter SSE comments).
  cleaned = cleaned.replace(/:?\s*OPENROUTER PROCESSING\s*/gi, '')

  // Some models wrap the entire response in ```markdown fences; unwrap for real rendering.
  const wrapped = cleaned.match(/^\s*```(?:markdown|md)\s*\n([\s\S]*?)\n```\s*$/i)
  if (wrapped) cleaned = wrapped[1]

  // Recover markdown structure when providers return escaped newlines in payload.
  const escapedNewlineCount = (cleaned.match(/\\n/g) || []).length
  const realNewlineCount = (cleaned.match(/\n/g) || []).length
  if (escapedNewlineCount >= 3 && escapedNewlineCount > realNewlineCount * 2) {
    cleaned = cleaned
      .replace(/\\r\\n/g, '\n')
      .replace(/\\n(?=(?:\s|[#>*`\-\|0-9]))/g, '\n')
  }

  // Unescape table pipes in markdown table rows (common LLM output style).
  if (/(^|\n)\s*\\?\|.+\\?\|/m.test(cleaned)) {
    cleaned = cleaned.replace(/\\\|/g, '|')
  }

  return cleaned
}

// Convert LLM-style math delimiters to standard ones
// \(...\) → $...$  and  \[...\] → $$...$$
function preprocessMath(content: string): string {
  if (!content) return ''
  return content
    .replace(/\\\((.+?)\\\)/gs, (_, m) => `$${m}$`)
    .replace(/\\\[(.+?)\\\]/gs, (_, m) => `$$${m}$$`)
}

class MarkdownErrorBoundary extends Component<
  { children: React.ReactNode; fallback: string },
  { hasError: boolean }
> {
  state = { hasError: false }
  static getDerivedStateFromError() {
    return { hasError: true }
  }
  componentDidCatch(error: any) {
    console.warn('Markdown render error:', error)
  }
  render() {
    if (this.state.hasError) {
      return <pre style={{ whiteSpace: 'pre-wrap', margin: 0 }}>{this.props.fallback}</pre>
    }
    return this.props.children
  }
}

export default function SafeMarkdown({ content }: { content: string }) {
  const processed = preprocessMath(sanitizeContent(content || ''))
  return (
    <MarkdownErrorBoundary fallback={content || ''}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkMath]}
        rehypePlugins={[[rehypeKatex, { throwOnError: false, strict: false }]]}
      >
        {processed}
      </ReactMarkdown>
    </MarkdownErrorBoundary>
  )
}
