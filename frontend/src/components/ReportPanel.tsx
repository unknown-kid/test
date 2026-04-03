import { useState, useEffect } from 'react'
import { Button, Select, Input, Spin, Typography, Space, Popconfirm, message, Tag } from 'antd'
import { ReloadOutlined, DeleteOutlined, PlusOutlined } from '@ant-design/icons'
import { reportsApi, type ReportInfo } from '../api/reports'
import SafeMarkdown from './SafeMarkdown'

const { Text } = Typography
const { TextArea } = Input

interface Props {
  paperId: string
}

export default function ReportPanel({ paperId }: Props) {
  const [reports, setReports] = useState<ReportInfo[]>([])
  const [loading, setLoading] = useState(false)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [focusPoints, setFocusPoints] = useState('')
  const [generating, setGenerating] = useState(false)
  const [showGenForm, setShowGenForm] = useState(false)

  useEffect(() => {
    setSelectedId(null)
    setShowGenForm(false)
    setFocusPoints('')
    loadReports()
  }, [paperId])

  const loadReports = async () => {
    setLoading(true)
    try {
      const res = await reportsApi.getReports(paperId)
      setReports(res.data)
      setSelectedId((current) => {
        if (current && res.data.some((report) => report.id === current)) {
          return current
        }
        const userReport = res.data.find((r) => r.report_type === 'user')
        return userReport?.id || res.data[0]?.id || null
      })
    } catch { /* ignore */ }
    finally { setLoading(false) }
  }

  const handleGenerate = async () => {
    setGenerating(true)
    try {
      const res = await reportsApi.generateReport(paperId, focusPoints || undefined)
      message.success('报告生成任务已提交')
      setShowGenForm(false)
      setFocusPoints('')
      await loadReports()
      setSelectedId(res.data.id)
    } catch (err: any) {
      message.error(err.response?.data?.detail || '生成失败')
    } finally {
      setGenerating(false)
    }
  }

  const handleDelete = async (reportId: string) => {
    try {
      await reportsApi.deleteReport(reportId)
      message.success('报告已删除')
      if (selectedId === reportId) setSelectedId(null)
      await loadReports()
    } catch (err: any) {
      message.error(err.response?.data?.detail || '删除失败')
    }
  }

  const selected = reports.find((r) => r.id === selectedId)

  const statusTag = (status: string) => {
    const map: Record<string, { color: string; text: string }> = {
      completed: { color: 'success', text: '已完成' },
      generating: { color: 'processing', text: '生成中' },
      pending: { color: 'default', text: '等待中' },
      failed: { color: 'error', text: '失败' },
    }
    const s = map[status] || { color: 'default', text: status }
    return <Tag color={s.color}>{s.text}</Tag>
  }

  if (loading) return <div style={{ textAlign: 'center', padding: 40 }}><Spin /></div>

  return (
    <div style={{ padding: 8, height: '100%', display: 'flex', flexDirection: 'column', minHeight: 0 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
        <Select
          style={{ flex: 1, marginRight: 8 }}
          value={selectedId}
          onChange={setSelectedId}
          placeholder="选择报告"
          options={reports.map((r) => ({
            value: r.id,
            label: `${r.report_type === 'system' ? '系统报告' : '个人报告'} - ${r.status === 'completed' ? '已完成' : r.status}`,
          }))}
        />
        <Space>
          <Button size="small" icon={<ReloadOutlined />} onClick={loadReports} />
          <Button size="small" icon={<PlusOutlined />} onClick={() => setShowGenForm(!showGenForm)}>
            生成个人报告
          </Button>
        </Space>
      </div>

      {showGenForm && (
        <div style={{ marginBottom: 12, padding: 12, background: '#fafafa', borderRadius: 6 }}>
          <Text style={{ fontSize: 12 }}>输入关注点（可选，帮助AI聚焦报告内容）</Text>
          <TextArea
            rows={2}
            value={focusPoints}
            onChange={(e) => setFocusPoints(e.target.value)}
            placeholder="例如：方法论创新点、实验设计、与XX方法的对比..."
            style={{ marginTop: 4, marginBottom: 8 }}
          />
          <Button type="primary" size="small" onClick={handleGenerate} loading={generating}>
            开始生成
          </Button>
        </div>
      )}

      {selected ? (
        <div style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column' }}>
          <div style={{ marginBottom: 8, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            {statusTag(selected.status)}
            {selected.report_type === 'user' && (
              <Popconfirm title="确定删除此报告？" onConfirm={() => handleDelete(selected.id)}>
                <Button type="text" danger size="small" icon={<DeleteOutlined />} />
              </Popconfirm>
            )}
          </div>
          {selected.focus_points && (
            <div style={{ marginBottom: 8 }}>
              <Text type="secondary" style={{ fontSize: 11 }}>关注点：{selected.focus_points}</Text>
            </div>
          )}
          {selected.status === 'completed' && selected.content ? (
            <div style={{ flex: 1, minHeight: 0, overflow: 'auto' }} className="md-content">
              <SafeMarkdown content={selected.content} />
            </div>
          ) : selected.status === 'generating' || selected.status === 'pending' ? (
            <div style={{ textAlign: 'center', padding: 40 }}>
              <Spin />
              <div style={{ marginTop: 8 }}><Text type="secondary">报告生成中，请稍候...</Text></div>
            </div>
          ) : selected.status === 'failed' ? (
            <Text type="danger">报告生成失败，请重试</Text>
          ) : null}
        </div>
      ) : (
        <Text type="secondary">暂无阅读报告</Text>
      )}
    </div>
  )
}
