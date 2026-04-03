import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { Button, Descriptions, Spin, Tag, Typography, message } from 'antd'
import { ArrowLeftOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import { filesApi, type PaperInfo } from '../../api/files'
import { adminApi } from '../../api/admin'
import type { ReportInfo } from '../../api/reports'
import PdfViewer from '../../components/PdfViewer'
import SafeMarkdown from '../../components/SafeMarkdown'

const { Text } = Typography

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

export default function AdminPaperDetail() {
  const { id: paperId } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const [paper, setPaper] = useState<PaperInfo | null>(null)
  const [reports, setReports] = useState<ReportInfo[]>([])
  const [pdfUrl, setPdfUrl] = useState('')
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    // Route-level scroll lock to avoid any outer-page blank scrolling.
    document.body.classList.add('admin-paper-detail-lock')
    document.documentElement.classList.add('admin-paper-detail-lock')

    return () => {
      document.body.classList.remove('admin-paper-detail-lock')
      document.documentElement.classList.remove('admin-paper-detail-lock')
    }
  }, [])

  useEffect(() => {
    if (!paperId) return
    const load = async () => {
      setLoading(true)
      try {
        const [paperRes, reportsRes] = await Promise.all([
          filesApi.getPaper(paperId),
          adminApi.getPaperReports(paperId),
        ])
        setPaper(paperRes.data)
        setReports(reportsRes.data)
        const token = localStorage.getItem('access_token') || ''
        setPdfUrl(`/api/papers/${paperId}/pdf?token=${encodeURIComponent(token)}`)
      } catch (err: any) {
        message.error(err.response?.data?.detail || '加载论文失败')
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [paperId])

  if (loading) {
    return <div style={{ display: 'flex', justifyContent: 'center', paddingTop: 160 }}><Spin size="large" /></div>
  }

  if (!paper || !paperId) {
    return (
      <div style={{ padding: 24 }}>
        <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/admin/papers')}>返回共享区论文</Button>
        <div style={{ marginTop: 16 }}>论文不存在</div>
      </div>
    )
  }

  const systemReport = reports.find((r) => r.report_type === 'system')

  return (
    <div className="admin-paper-detail-page" style={{ width: '100%', height: '100%', minHeight: 0, display: 'flex', overflow: 'hidden' }}>
      <div style={{ flex: 1, minWidth: 0, overflow: 'hidden', borderRight: '1px solid #f0f0f0' }}>
        {pdfUrl ? (
          <PdfViewer url={pdfUrl} highlights={[]} annotations={[]} readOnly />
        ) : null}
      </div>
      <div className="admin-paper-detail-side" style={{ width: 460, flexShrink: 0, padding: 16, overflowY: 'auto', overflowX: 'hidden', overscrollBehavior: 'contain' }}>
        <div style={{ marginBottom: 16 }}>
          <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/admin/papers')}>返回共享区论文</Button>
        </div>

        <Text strong style={{ fontSize: 16 }}>论文信息（只读）</Text>
        <Descriptions column={1} size="small" bordered style={{ marginTop: 8 }}>
          <Descriptions.Item label="标题"><div>{paper.title || '未知'}</div></Descriptions.Item>
          <Descriptions.Item label="原文件名"><div>{paper.original_filename || '-'}</div></Descriptions.Item>
          <Descriptions.Item label="文件大小">{formatSize(paper.file_size)}</Descriptions.Item>
          <Descriptions.Item label="摘要"><div>{paper.abstract || '-'}</div></Descriptions.Item>
          <Descriptions.Item label="关键词">
            {paper.keywords?.length ? paper.keywords.map((k) => <Tag key={k}>{k}</Tag>) : '-'}
          </Descriptions.Item>
          <Descriptions.Item label="处理状态">
            <Tag color={paper.processing_status === 'completed' ? 'success' : paper.processing_status === 'failed' ? 'error' : 'processing'}>
              {paper.processing_status}
            </Tag>
          </Descriptions.Item>
          <Descriptions.Item label="上传时间">{dayjs(paper.created_at).format('YYYY-MM-DD HH:mm')}</Descriptions.Item>
        </Descriptions>

        <div style={{ marginTop: 24 }}>
          <Text strong style={{ fontSize: 14 }}>阅读报告（只读）</Text>
          <div style={{ marginTop: 8 }} className="md-content">
            {systemReport?.status === 'completed' && systemReport.content
              ? <SafeMarkdown content={systemReport.content} />
              : <Text type="secondary">{systemReport ? `报告状态：${systemReport.status}` : '暂无系统报告'}</Text>}
          </div>
        </div>
      </div>
    </div>
  )
}
