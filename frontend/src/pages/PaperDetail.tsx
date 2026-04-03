import { useEffect, useState, useRef, useCallback } from 'react'
import { useParams } from 'react-router-dom'
import { Tabs, Spin, message, Typography, Button, Input, Descriptions, Tag, Select, Modal, TreeSelect } from 'antd'
import { CopyOutlined } from '@ant-design/icons'
import { filesApi, type PaperInfo, type FolderTreeNode } from '../api/files'
import { annotationsApi, type NoteInfo, type HighlightInfo, type AnnotationInfo } from '../api/annotations'
import { useAuthStore } from '../stores/authStore'
import SafeMarkdown from '../components/SafeMarkdown'
import client from '../api/client'
import ChatPanel from '../components/ChatPanel'
import TranslateDialog from '../components/TranslateDialog'
import AskAIDialog from '../components/AskAIDialog'
import ReportPanel from '../components/ReportPanel'
import PdfViewer, { type SelectionInfo } from '../components/PdfViewer'
import SelectionPopover from '../components/SelectionPopover'

const { TextArea } = Input
const { Text } = Typography

interface ReportInfo {
  id: string
  content: string | null
  status: string
  report_type: string
}

interface AskAIRequest {
  selectedText: string
  question: string
  counter: number
}

const ROOT_KEY = '__root__'

function buildFolderOptions(nodes: FolderTreeNode[]): any[] {
  return nodes.map((node) => ({
    title: `${node.name} (${node.paper_count})`,
    value: node.id,
    key: node.id,
    children: buildFolderOptions(node.children),
  }))
}

function ResizableLayout({ left, right, defaultWidth = 420, minWidth = 280, maxWidth = 700 }: {
  left: React.ReactNode; right: React.ReactNode
  defaultWidth?: number; minWidth?: number; maxWidth?: number
}) {
  const [siderWidth, setSiderWidth] = useState(defaultWidth)
  const dragging = useRef(false)
  const startX = useRef(0)
  const startW = useRef(defaultWidth)

  const onMouseDown = useCallback((e: React.MouseEvent) => {
    dragging.current = true
    startX.current = e.clientX
    startW.current = siderWidth
    document.body.style.cursor = 'col-resize'
    document.body.style.userSelect = 'none'

    const onMouseMove = (ev: MouseEvent) => {
      if (!dragging.current) return
      const delta = startX.current - ev.clientX
      const newW = Math.min(maxWidth, Math.max(minWidth, startW.current + delta))
      setSiderWidth(newW)
    }
    const onMouseUp = () => {
      dragging.current = false
      document.body.style.cursor = ''
      document.body.style.userSelect = ''
      document.removeEventListener('mousemove', onMouseMove)
      document.removeEventListener('mouseup', onMouseUp)
    }
    document.addEventListener('mousemove', onMouseMove)
    document.addEventListener('mouseup', onMouseUp)
  }, [siderWidth, minWidth, maxWidth])

  return (
    <div className="paper-detail-page" style={{ display: 'flex', height: '100%', overflow: 'hidden' }}>
      <div style={{ flex: 1, minWidth: 0, overflow: 'hidden' }}>{left}</div>
      <div
        onMouseDown={onMouseDown}
        style={{
          width: 5, cursor: 'col-resize', background: '#e8e8e8', flexShrink: 0,
          transition: 'background 0.2s',
        }}
        onMouseEnter={(e) => (e.currentTarget.style.background = '#bbb')}
        onMouseLeave={(e) => { if (!dragging.current) e.currentTarget.style.background = '#e8e8e8' }}
      />
      <div style={{ width: siderWidth, flexShrink: 0, background: '#fff', overflow: 'hidden', minHeight: 0 }}>{right}</div>
    </div>
  )
}

export default function PaperDetail() {
  const { id: paperId } = useParams<{ id: string }>()
  const { user } = useAuthStore()
  const [paper, setPaper] = useState<PaperInfo | null>(null)
  const [loading, setLoading] = useState(true)
  const [note, setNote] = useState<NoteInfo | null>(null)
  const [noteContent, setNoteContent] = useState('')
  const [noteSaving, setNoteSaving] = useState(false)
  const [reports, setReports] = useState<ReportInfo[]>([])
  const [pdfUrl, setPdfUrl] = useState('')
  const [translateOpen, setTranslateOpen] = useState(false)
  const [translateText, setTranslateText] = useState('')
  const [highlights, setHighlights] = useState<HighlightInfo[]>([])
  const [annotations, setAnnotations] = useState<AnnotationInfo[]>([])
  const [selectionInfo, setSelectionInfo] = useState<SelectionInfo | null>(null)
  const [activeTab, setActiveTab] = useState('info')
  const [askAiDialogOpen, setAskAiDialogOpen] = useState(false)
  const [askAiSelectionText, setAskAiSelectionText] = useState('')
  const [askAiQuestion, setAskAiQuestion] = useState('')
  const [askAiRequest, setAskAiRequest] = useState<AskAIRequest | null>(null)
  const [askAiCounter, setAskAiCounter] = useState(0)
  const [keywordDraft, setKeywordDraft] = useState<string[]>([])
  const [keywordSaving, setKeywordSaving] = useState(false)
  const [copyingToPersonal, setCopyingToPersonal] = useState(false)
  const [copyModalOpen, setCopyModalOpen] = useState(false)
  const [copyTarget, setCopyTarget] = useState<string>(ROOT_KEY)
  const [personalTreeLoading, setPersonalTreeLoading] = useState(false)
  const [personalFolderTree, setPersonalFolderTree] = useState<FolderTreeNode[]>([])

  const isShared = paper?.zone === 'shared'
  const isPersonal = paper?.zone === 'personal'

  const normalizeKeywords = (keywords: string[]) => {
    const seen = new Set<string>()
    const cleaned: string[] = []
    for (const raw of keywords) {
      const keyword = String(raw || '').trim()
      if (!keyword) continue
      const dedupeKey = keyword.toLowerCase()
      if (seen.has(dedupeKey)) continue
      seen.add(dedupeKey)
      cleaned.push(keyword)
    }
    return cleaned
  }

  useEffect(() => {
    if (!paperId) return
    loadPaper()
    loadReports()
  }, [paperId])

  useEffect(() => {
    document.body.classList.add('paper-detail-lock')
    document.documentElement.classList.add('paper-detail-lock')
    return () => {
      document.body.classList.remove('paper-detail-lock')
      document.documentElement.classList.remove('paper-detail-lock')
    }
  }, [])

  useEffect(() => {
    if (paperId && isPersonal) {
      loadNote()
      loadHighlights()
      loadAnnotations()
    }
  }, [paperId, isPersonal])

  useEffect(() => {
    setKeywordDraft(normalizeKeywords(paper?.keywords || []))
  }, [paper?.id, paper?.keywords])

  const loadPaper = async () => {
    try {
      const res = await filesApi.getPaper(paperId!)
      setPaper(res.data)
      const token = localStorage.getItem('access_token') || ''
      setPdfUrl(`/api/papers/${paperId}/pdf?token=${encodeURIComponent(token)}`)
    } catch (err: any) {
      message.error(err.response?.data?.detail || '加载论文失败')
    } finally {
      setLoading(false)
    }
  }

  const loadNote = async () => {
    try {
      const res = await annotationsApi.getNote(paperId!)
      setNote(res.data)
      setNoteContent(res.data?.content || '')
    } catch {}
  }

  const loadReports = async () => {
    try {
      const res = await client.get<ReportInfo[]>(`/reports/${paperId}`)
      setReports(res.data)
    } catch {}
  }

  const loadHighlights = async () => {
    try {
      const res = await annotationsApi.getHighlights(paperId!)
      setHighlights(res.data)
    } catch {}
  }

  const loadAnnotations = async () => {
    try {
      const res = await annotationsApi.getAnnotations(paperId!)
      setAnnotations(res.data)
    } catch {}
  }

  const saveNote = async () => {
    setNoteSaving(true)
    try {
      const res = await annotationsApi.updateNote(paperId!, noteContent)
      setNote(res.data)
      message.success('笔记已保存')
    } catch {
      message.error('保存失败')
    } finally {
      setNoteSaving(false)
    }
  }

  const loadPersonalFolderTree = async () => {
    setPersonalTreeLoading(true)
    try {
      const res = await filesApi.getFolderTree('personal')
      setPersonalFolderTree(res.data || [])
    } catch (err: any) {
      message.error(err.response?.data?.detail || '加载个人区目录失败')
      setPersonalFolderTree([])
    } finally {
      setPersonalTreeLoading(false)
    }
  }

  const handleOpenCopyToPersonal = async () => {
    setCopyTarget(ROOT_KEY)
    setCopyModalOpen(true)
    await loadPersonalFolderTree()
  }

  const handleCopyToPersonal = async () => {
    if (!paperId) return
    setCopyingToPersonal(true)
    try {
      const targetFolderId = copyTarget === ROOT_KEY ? null : copyTarget
      await filesApi.copyPaper(paperId, targetFolderId)
      message.success('复制任务已提交，可在个人区查看')
      setCopyModalOpen(false)
    } catch (err: any) {
      message.error(err.response?.data?.detail || '复制失败')
    } finally {
      setCopyingToPersonal(false)
    }
  }

  const handleCopyText = () => {
    if (selectionInfo) {
      navigator.clipboard.writeText(selectionInfo.text)
      message.success('已复制')
    }
    setSelectionInfo(null)
    window.getSelection()?.removeAllRanges()
  }

  const handleHighlight = async () => {
    if (!selectionInfo || !paperId) return
    try {
      await annotationsApi.createHighlight({
        paper_id: paperId,
        page: selectionInfo.pageIndex,
        position_data: { rects: selectionInfo.rects, text: selectionInfo.text, pageIndex: selectionInfo.pageIndex },
      })
      message.success('高亮已添加')
      loadHighlights()
    } catch { message.error('添加高亮失败') }
    setSelectionInfo(null)
    window.getSelection()?.removeAllRanges()
  }

  const handleAnnotate = async (comment: string) => {
    if (!selectionInfo || !paperId) return
    try {
      await annotationsApi.createAnnotation({
        paper_id: paperId,
        page: selectionInfo.pageIndex,
        position_data: { rects: selectionInfo.rects, text: selectionInfo.text, pageIndex: selectionInfo.pageIndex },
        content: comment,
      })
      message.success('批注已添加')
      loadAnnotations()
    } catch { message.error('添加批注失败') }
    setSelectionInfo(null)
    window.getSelection()?.removeAllRanges()
  }

  const handleTranslate = () => {
    if (selectionInfo) {
      const normalized = selectionInfo.text
        .replace(/\r/g, ' ')
        .replace(/\n+/g, ' ')
        .replace(/\s{2,}/g, ' ')
        .trim()
      setTranslateText(normalized)
      setTranslateOpen(true)
    }
    setSelectionInfo(null)
    window.getSelection()?.removeAllRanges()
  }

  const handleAskAI = () => {
    if (selectionInfo) {
      setAskAiSelectionText(selectionInfo.text)
      setAskAiQuestion('')
      setAskAiDialogOpen(true)
    }
    setSelectionInfo(null)
    window.getSelection()?.removeAllRanges()
  }

  const handleAskAiSubmit = () => {
    const selected = askAiSelectionText.trim()
    const question = askAiQuestion.trim()
    if (!selected) {
      message.warning('划词内容为空，请重新选择文本')
      return
    }
    if (!question) {
      message.warning('请输入你的问题')
      return
    }
    const next = askAiCounter + 1
    setAskAiCounter(next)
    setAskAiRequest({ selectedText: selected, question, counter: next })
    setActiveTab('chat')
  }

  const handleSaveKeywords = async () => {
    if (!paperId) return
    setKeywordSaving(true)
    try {
      const normalized = normalizeKeywords(keywordDraft)
      const res = await filesApi.updatePaperKeywords(paperId, normalized)
      setPaper(res.data)
      setKeywordDraft(normalizeKeywords(res.data.keywords || []))
      message.success('关键词已更新')
    } catch (err: any) {
      message.error(err.response?.data?.detail || '关键词更新失败')
    } finally {
      setKeywordSaving(false)
    }
  }

  if (loading) {
    return <div style={{ display: 'flex', justifyContent: 'center', paddingTop: 200 }}><Spin size="large" /></div>
  }
  if (!paper) {
    return <div style={{ padding: 40, textAlign: 'center' }}>论文不存在</div>
  }

  const canEditKeywords = isPersonal || (isShared && user?.role === 'admin')
  const normalizedPaperKeywords = normalizeKeywords(paper.keywords || [])
  const normalizedDraftKeywords = normalizeKeywords(keywordDraft)
  const keywordsChanged = normalizedPaperKeywords.join('\u0001') !== normalizedDraftKeywords.join('\u0001')

  const renderKeywordValue = () => {
    if (!canEditKeywords) {
      return paper.keywords?.map((k) => <Tag key={k}>{k}</Tag>) || '-'
    }

    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        <Select
          mode="tags"
          open={false}
          value={keywordDraft}
          tokenSeparators={[',', ';', '，', '；']}
          placeholder="输入关键词后回车，可直接删除已有关键词"
          onChange={(vals) => setKeywordDraft(normalizeKeywords(vals as string[]))}
          style={{ width: '100%' }}
        />
        <div style={{ display: 'flex', gap: 8 }}>
          <Button
            size="small"
            type="primary"
            loading={keywordSaving}
            disabled={!keywordsChanged}
            onClick={handleSaveKeywords}
          >
            保存关键词
          </Button>
          <Button
            size="small"
            disabled={!keywordsChanged || keywordSaving}
            onClick={() => setKeywordDraft(normalizedPaperKeywords)}
          >
            重置
          </Button>
        </div>
      </div>
    )
  }

  const systemReport = reports.find((r) => r.report_type === 'system')

  // Shared paper
  if (isShared) {
    return (
      <>
        <ResizableLayout
          defaultWidth={400}
          left={pdfUrl ? <PdfViewer url={pdfUrl} highlights={[]} annotations={[]} readOnly /> : null}
          right={
            <div style={{ height: '100%', overflow: 'auto', overscrollBehavior: 'contain', padding: 16 }}>
              <div style={{ marginBottom: 16, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <Text strong style={{ fontSize: 16 }}>论文信息</Text>
                <Button icon={<CopyOutlined />} onClick={handleOpenCopyToPersonal} size="small">复制到个人区</Button>
              </div>
              <Descriptions column={1} size="small" bordered>
                <Descriptions.Item label="标题">{paper.title || '未知'}</Descriptions.Item>
                <Descriptions.Item label="文件大小">{(paper.file_size / 1024 / 1024).toFixed(1)} MB</Descriptions.Item>
                <Descriptions.Item label="关键词">{renderKeywordValue()}</Descriptions.Item>
              </Descriptions>
              <div style={{ marginTop: 24 }}>
                <Text strong style={{ fontSize: 14 }}>系统阅读报告</Text>
                <div style={{ marginTop: 8 }} className="md-content">
                  {systemReport?.status === 'completed' && systemReport.content
                    ? <SafeMarkdown content={systemReport.content} />
                    : <Text type="secondary">报告生成中...</Text>}
                </div>
              </div>
            </div>
          }
        />
        <Modal
          title="复制到个人区"
          open={copyModalOpen}
          onOk={handleCopyToPersonal}
          onCancel={() => setCopyModalOpen(false)}
          okText="复制"
          cancelText="取消"
          confirmLoading={copyingToPersonal}
        >
          <Spin spinning={personalTreeLoading}>
            <TreeSelect
              value={copyTarget}
              style={{ width: '100%' }}
              treeData={[
                { title: '个人区根目录', value: ROOT_KEY, key: ROOT_KEY, children: buildFolderOptions(personalFolderTree) },
              ]}
              treeDefaultExpandAll
              onChange={(value) => setCopyTarget(String(value))}
              placeholder="选择个人区目标目录"
            />
          </Spin>
        </Modal>
      </>
    )
  }

  // Personal paper
  const tabItems = [
    {
      key: 'info', label: '论文信息',
      children: (
        <div style={{ height: '100%', overflow: 'auto', paddingRight: 4 }}>
          <Descriptions column={1} size="small" bordered>
            <Descriptions.Item label="标题">{paper.title || '未知'}</Descriptions.Item>
            <Descriptions.Item label="文件大小">{(paper.file_size / 1024 / 1024).toFixed(1)} MB</Descriptions.Item>
            <Descriptions.Item label="摘要">{paper.abstract || '-'}</Descriptions.Item>
            <Descriptions.Item label="关键词">{renderKeywordValue()}</Descriptions.Item>
            <Descriptions.Item label="处理状态">
              <Tag color={paper.processing_status === 'completed' ? 'success' : paper.processing_status === 'failed' ? 'error' : 'processing'}>
                {paper.processing_status}
              </Tag>
            </Descriptions.Item>
          </Descriptions>
        </div>
      ),
    },
    {
      key: 'chat', label: 'AI对话',
      children: <div style={{ height: '100%', overflow: 'hidden' }}><ChatPanel paperId={paperId!} askAiRequest={askAiRequest || undefined} /></div>,
    },
    {
      key: 'report', label: '阅读报告',
      children: <div style={{ height: '100%', overflow: 'hidden' }}><ReportPanel paperId={paperId!} /></div>,
    },
    {
      key: 'notes', label: '笔记',
      children: (
        <div style={{ height: '100%', overflow: 'auto', padding: 8 }}>
          <TextArea rows={15} value={noteContent} onChange={(e) => setNoteContent(e.target.value)} placeholder="在此输入笔记（支持Markdown）..." />
          <Button type="primary" onClick={saveNote} loading={noteSaving} style={{ marginTop: 8 }}>保存笔记</Button>
          {noteContent && (
            <div style={{ marginTop: 16, borderTop: '1px solid #f0f0f0', paddingTop: 12 }} className="md-content">
              <Text type="secondary" style={{ fontSize: 12 }}>预览：</Text>
              <SafeMarkdown content={noteContent} />
            </div>
          )}
        </div>
      ),
    },
  ]

  return (
    <>
      <ResizableLayout
        left={
          pdfUrl ? (
            <PdfViewer
              url={pdfUrl}
              highlights={highlights}
              annotations={annotations}
              readOnly={false}
              onTextSelect={setSelectionInfo}
              onDeleteHighlight={(id) => annotationsApi.deleteHighlight(id).then(loadHighlights)}
              onDeleteAnnotation={(id) => annotationsApi.deleteAnnotation(id).then(loadAnnotations)}
            />
          ) : null
        }
        right={(
          <div style={{ height: '100%', overflow: 'hidden', padding: '0 12px' }}>
            <Tabs className="paper-detail-tabs" activeKey={activeTab} onChange={setActiveTab} items={tabItems} />
          </div>
        )}
      />
      <SelectionPopover
        visible={!!selectionInfo}
        position={selectionInfo ? { top: selectionInfo.clientRect.top, left: selectionInfo.clientRect.left + selectionInfo.clientRect.width / 2 - 100 } : { top: 0, left: 0 }}
        selectedText={selectionInfo?.text || ''}
        onCopy={handleCopyText}
        onHighlight={handleHighlight}
        onAnnotate={handleAnnotate}
        onTranslate={handleTranslate}
        onAskAI={handleAskAI}
        onClose={() => { setSelectionInfo(null); window.getSelection()?.removeAllRanges() }}
      />
      <TranslateDialog open={translateOpen} initialText={translateText} onClose={() => setTranslateOpen(false)} />
      <AskAIDialog
        open={askAiDialogOpen}
        selectedText={askAiSelectionText}
        question={askAiQuestion}
        onQuestionChange={setAskAiQuestion}
        onAsk={handleAskAiSubmit}
        onClose={() => setAskAiDialogOpen(false)}
      />
      <Modal
        title="复制到个人区"
        open={copyModalOpen}
        onOk={handleCopyToPersonal}
        onCancel={() => setCopyModalOpen(false)}
        okText="复制"
        cancelText="取消"
        confirmLoading={copyingToPersonal}
      >
        <Spin spinning={personalTreeLoading}>
          <TreeSelect
            value={copyTarget}
            style={{ width: '100%' }}
            treeData={[
              { title: '个人区根目录', value: ROOT_KEY, key: ROOT_KEY, children: buildFolderOptions(personalFolderTree) },
            ]}
            treeDefaultExpandAll
            onChange={(value) => setCopyTarget(String(value))}
            placeholder="选择个人区目标目录"
          />
        </Spin>
      </Modal>
    </>
  )
}
