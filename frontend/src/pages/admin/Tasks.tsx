import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Alert, Button, Card, Col, Popconfirm, Progress, Row, Space, Statistic, Table, Tag, Typography, message } from 'antd'
import { ReloadOutlined, ThunderboltOutlined, ClockCircleOutlined, SyncOutlined, WarningOutlined } from '@ant-design/icons'
import { adminApi, type TaskBoardOverview } from '../../api/admin'

const { Text, Title } = Typography
const AUTO_REFRESH_MS = 5000

const STEP_LABELS: Record<string, string> = {
  chunking: '分块向量化',
  title: '标题提取',
  abstract: '摘要提取',
  keywords: '关键词提取',
  report: '阅读报告',
}

function formatDateTime(value?: string | null): string {
  if (!value) return '-'
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return '-'
  return d.toLocaleString('zh-CN', { hour12: false })
}

function statusColor(status: string): string {
  if (status === 'completed') return 'success'
  if (status === 'processing') return 'processing'
  if (status === 'failed') return 'error'
  return 'default'
}

export default function Tasks() {
  const [overview, setOverview] = useState<TaskBoardOverview | null>(null)
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [cleaningStuck, setCleaningStuck] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const requestInFlightRef = useRef(false)

  const loadOverview = useCallback(async (silent: boolean = false) => {
    if (requestInFlightRef.current) {
      return
    }

    requestInFlightRef.current = true
    if (silent) {
      setRefreshing(true)
    } else {
      setLoading(true)
    }
    try {
      const res = await adminApi.getTasksOverview()
      setOverview(res.data)
      setError(null)
    } catch (err: any) {
      setError(err.response?.data?.detail || '加载任务看板失败')
    } finally {
      requestInFlightRef.current = false
      if (silent) {
        setRefreshing(false)
      } else {
        setLoading(false)
      }
    }
  }, [])

  const handleCleanupStuck = useCallback(async (force = false) => {
    setCleaningStuck(true)
    try {
      const res = await adminApi.cleanupStuckProcessingTasks(force)
      const data = res.data
      const runtimeSummary = force && data.runtime_cleanup
        ? `；已撤销执行中${data.runtime_cleanup.active_revoked}，预留${data.runtime_cleanup.reserved_revoked}，计划${data.runtime_cleanup.scheduled_revoked}，清空排队${data.runtime_cleanup.purged_waiting}`
        : ''
      message.success(
        `清理完成：扫描${data.scanned_papers || 0}篇，命中${data.matched_papers}篇，置失败${data.failed_papers}篇${runtimeSummary}`
      )
      await loadOverview(true)
    } catch (err: any) {
      message.error(err.response?.data?.detail || '清理失败')
    } finally {
      setCleaningStuck(false)
    }
  }, [loadOverview])

  useEffect(() => {
    loadOverview(false)
    const timer = window.setInterval(() => {
      loadOverview(true)
    }, AUTO_REFRESH_MS)
    return () => window.clearInterval(timer)
  }, [loadOverview])

  const stepRows = useMemo(() => {
    const stepMap = overview?.processing.step_status_counts || {}
    return Object.entries(stepMap).map(([step, counts]) => ({
      key: step,
      step,
      ...counts,
    }))
  }, [overview])

  const runningPaperRows = overview?.processing.running_papers || []
  const modelConcurrencyRows = overview?.concurrency.models || []
  const modelUsageRows = overview?.model_usage_24h || []
  const userUsageRows = overview?.user_model_usage_24h || []
  const failedRows = overview?.recent_failed_tasks || []
  const taskRows = overview?.queue.task_breakdown || []
  const artifactAudit = overview?.artifact_audit

  return (
    <div style={{ padding: 24, display: 'flex', flexDirection: 'column', gap: 16 }}>
      <Space style={{ width: '100%', justifyContent: 'space-between' }}>
        <div>
          <Title level={4} style={{ margin: 0 }}>任务看板</Title>
          <Text type="secondary">
            自动刷新间隔 {AUTO_REFRESH_MS / 1000} 秒，最近更新时间：{formatDateTime(overview?.generated_at)}
          </Text>
        </div>
        <Space>
          <Popconfirm
            title="确认执行全量步骤校验清理？"
            description="会遍历全部论文：步骤状态与产物不一致时置失败，并清除不完整产物；不会删除论文文件。"
            okText="确认清理"
            cancelText="取消"
            onConfirm={() => handleCleanupStuck(false)}
          >
            <Button danger loading={cleaningStuck}>
              全量校验并清理步骤状态
            </Button>
          </Popconfirm>
          <Popconfirm
            title="强制清理（忽略队列状态）？"
            description="当队列长期有残留时使用。可能与正在执行任务并发冲突，请谨慎。"
            okText="强制执行"
            cancelText="取消"
            onConfirm={() => handleCleanupStuck(true)}
          >
            <Button loading={cleaningStuck}>
              强制清理（忽略队列）
            </Button>
          </Popconfirm>
          <Button icon={<ReloadOutlined />} loading={refreshing} onClick={() => loadOverview(true)}>
            立即刷新
          </Button>
        </Space>
      </Space>

      {error && (
        <Alert type="error" showIcon message="任务看板加载失败" description={error} />
      )}

      <Row gutter={16}>
        <Col span={4}>
          <Card loading={loading}>
            <Statistic title="队列等待中" value={overview?.queue.waiting_count || 0} prefix={<ClockCircleOutlined />} />
          </Card>
        </Col>
        <Col span={4}>
          <Card loading={loading}>
            <Statistic title="执行中任务" value={overview?.queue.running_count || 0} prefix={<SyncOutlined spin />} />
          </Card>
        </Col>
        <Col span={4}>
          <Card loading={loading}>
            <Statistic title="调度中任务" value={(overview?.queue.reserved_count || 0) + (overview?.queue.scheduled_count || 0)} />
          </Card>
        </Col>
        <Col span={4}>
          <Card loading={loading}>
            <Statistic
              title="在线Worker"
              value={overview?.queue.workers_online || 0}
              prefix={<ThunderboltOutlined />}
              suffix="节点"
            />
            <Text type="secondary">
              目标 {overview?.queue.worker_nodes_target || 0} 节点 · 进程 {overview?.queue.worker_process_total || 0}
            </Text>
          </Card>
        </Col>
        <Col span={4}>
          <Card loading={loading}>
            <Statistic title="执行中步骤数" value={overview?.processing.running_step_total || 0} />
          </Card>
        </Col>
        <Col span={4}>
          <Card loading={loading}>
            <Statistic title="失败步骤数" value={overview?.processing.failed_step_total || 0} prefix={<WarningOutlined />} />
          </Card>
        </Col>
      </Row>

      <Row gutter={16}>
        <Col span={8}>
          <Card title="当前剩余缺口" loading={loading}>
            <Statistic title="已完成论文仍有缺口" value={artifactAudit?.completed_papers_with_any_gap || 0} prefix={<WarningOutlined />} />
            <Text type="secondary">
              最近巡检：{formatDateTime(artifactAudit?.generated_at)}
            </Text>
          </Card>
        </Col>
        <Col span={8}>
          <Card title="当前向量缺口" loading={loading}>
            <Statistic
              title="缺分块 / 缺摘要"
              value={`${artifactAudit?.completed_papers_missing_chunk_vectors || 0} / ${artifactAudit?.completed_papers_missing_abstract_vectors || 0}`}
            />
            <Text type="secondary">
              最近一轮新排补建 {artifactAudit?.queued_repairs || 0} 篇
            </Text>
          </Card>
        </Col>
        <Col span={8}>
          <Card title="已完成步骤缺产物" loading={loading}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              <Text type="secondary">标题 {artifactAudit?.completed_steps_missing_title || 0}</Text>
              <Text type="secondary">摘要 {artifactAudit?.completed_steps_missing_abstract || 0}</Text>
              <Text type="secondary">关键词 {artifactAudit?.completed_steps_missing_keywords || 0}</Text>
              <Text type="secondary">报告 {artifactAudit?.completed_steps_missing_report || 0}</Text>
            </div>
          </Card>
        </Col>
      </Row>

      <Row gutter={16}>
        <Col span={8}>
          <Card title="论文级并发占用" loading={loading}>
            <Progress
              percent={overview?.concurrency.paper.utilization_percent || 0}
              status={(overview?.concurrency.paper.in_use || 0) > (overview?.concurrency.paper.limit || 0) ? 'exception' : 'active'}
            />
            <Text type="secondary">
              当前 {overview?.concurrency.paper.in_use || 0} / 限额 {overview?.concurrency.paper.limit || 0}
            </Text>
          </Card>
        </Col>
        <Col span={8}>
          <Card title="在线Worker槽位占用" loading={loading}>
            <Progress
              percent={overview?.queue.worker_total_utilization_percent || 0}
              status={(overview?.queue.worker_total_in_use || 0) > (overview?.queue.worker_total_limit || 0) ? 'exception' : 'active'}
            />
            <Text type="secondary">
              当前 {overview?.queue.worker_total_in_use || 0} / 限额 {overview?.queue.worker_total_limit || 0}
            </Text>
          </Card>
        </Col>
        <Col span={8}>
          <Card title="五步骤总体完成度" loading={loading}>
            <Progress
              percent={overview?.processing.overall_step_progress_percent || 0}
              status={(overview?.processing.failed_step_total || 0) > 0 ? 'exception' : 'active'}
            />
            <Text type="secondary">
              已完成步骤 {overview?.processing.completed_step_total || 0}，执行中 {overview?.processing.running_step_total || 0}
            </Text>
          </Card>
        </Col>
      </Row>

      <Row gutter={16}>
        <Col span={12}>
          <Card title="五步骤状态分布" loading={loading}>
            <Table
              size="small"
              rowKey="key"
              pagination={false}
              dataSource={stepRows}
              columns={[
                { title: '步骤', dataIndex: 'step', key: 'step', render: (s: string) => STEP_LABELS[s] || s },
                { title: '等待', dataIndex: 'pending', key: 'pending' },
                { title: '处理中', dataIndex: 'processing', key: 'processing' },
                { title: '已完成', dataIndex: 'completed', key: 'completed' },
                { title: '失败', dataIndex: 'failed', key: 'failed' },
              ]}
            />
          </Card>
        </Col>
        <Col span={12}>
          <Card title="模型实时并发占用" loading={loading}>
            <Table
              size="small"
              rowKey={(r) => `${r.model_type}-${r.model_name}`}
              pagination={{ pageSize: 6 }}
              dataSource={modelConcurrencyRows}
              columns={[
                { title: '类型', dataIndex: 'model_type', key: 'model_type', width: 90 },
                { title: '模型', dataIndex: 'model_name', key: 'model_name', ellipsis: true },
                { title: '占用', key: 'in_use', render: (_, r) => `${r.in_use}/${r.limit}` },
                {
                  title: '利用率',
                  key: 'util',
                  width: 120,
                  render: (_, r) => <Progress percent={r.utilization_percent || 0} size="small" />,
                },
              ]}
            />
          </Card>
        </Col>
      </Row>

      <Card title={`执行中论文进度（${overview?.processing.running_papers_count || 0} 篇）`} loading={loading}>
        <Table
          size="small"
          rowKey="paper_id"
          dataSource={runningPaperRows}
          pagination={{ pageSize: 8 }}
          columns={[
            { title: '论文', dataIndex: 'title', key: 'title', ellipsis: true },
            { title: '区域', dataIndex: 'zone', key: 'zone', width: 90 },
            { title: '用户', dataIndex: 'uploaded_by', key: 'uploaded_by', width: 120, render: (v: string | null) => v || '-' },
            {
              title: '进度',
              key: 'progress',
              width: 200,
              render: (_, r) => <Progress percent={r.progress_percent} size="small" />,
            },
            {
              title: '步骤状态',
              key: 'steps',
              render: (_, r) => (
                <Space size={[0, 4]} wrap>
                  {Object.entries(r.step_statuses || {}).map(([step, st]) => (
                    <Tag key={`${r.paper_id}-${step}`} color={statusColor(st)}>{STEP_LABELS[step] || step}:{st}</Tag>
                  ))}
                </Space>
              ),
            },
            { title: '创建时间', dataIndex: 'created_at', key: 'created_at', width: 170, render: (v: string) => formatDateTime(v) },
          ]}
        />
      </Card>

      <Row gutter={16}>
        <Col span={12}>
          <Card title="模型请求统计（24小时）" loading={loading}>
            <Table
              size="small"
              rowKey={(r) => `${r.model_type}-${r.model_name}`}
              dataSource={modelUsageRows}
              pagination={{ pageSize: 8 }}
              columns={[
                { title: '类型', dataIndex: 'model_type', key: 'model_type', width: 90 },
                { title: '模型', dataIndex: 'model_name', key: 'model_name', ellipsis: true },
                { title: '请求数', dataIndex: 'requests_24h', key: 'requests_24h', width: 100 },
                { title: '失败数', dataIndex: 'failed_24h', key: 'failed_24h', width: 100 },
                { title: '成功率', dataIndex: 'success_rate_24h', key: 'success_rate_24h', width: 100, render: (v: number | null) => v == null ? '-' : `${v}%` },
              ]}
            />
          </Card>
        </Col>
        <Col span={12}>
          <Card title="用户模型使用（24小时）" loading={loading}>
            <Table
              size="small"
              rowKey={(r) => `${r.user_id}-${r.model_type}-${r.model_name}`}
              dataSource={userUsageRows}
              pagination={{ pageSize: 8 }}
              columns={[
                { title: '用户', dataIndex: 'username', key: 'username', width: 120 },
                { title: '类型', dataIndex: 'model_type', key: 'model_type', width: 90 },
                { title: '模型', dataIndex: 'model_name', key: 'model_name', ellipsis: true },
                { title: '请求数', dataIndex: 'requests_24h', key: 'requests_24h', width: 90 },
                { title: '失败数', dataIndex: 'failed_24h', key: 'failed_24h', width: 90 },
              ]}
            />
          </Card>
        </Col>
      </Row>

      <Row gutter={16}>
        <Col span={12}>
          <Card title="Celery任务类型拆分" loading={loading}>
            <Table
              size="small"
              rowKey="task_name"
              dataSource={taskRows}
              pagination={{ pageSize: 6 }}
              columns={[
                { title: '任务名', dataIndex: 'task_name', key: 'task_name', ellipsis: true },
                { title: '执行中', dataIndex: 'running', key: 'running', width: 90 },
                { title: '预留', dataIndex: 'reserved', key: 'reserved', width: 90 },
                { title: '调度', dataIndex: 'scheduled', key: 'scheduled', width: 90 },
              ]}
            />
          </Card>
        </Col>
        <Col span={12}>
          <Card title="最近失败任务（通知）" loading={loading}>
            <Table
              size="small"
              rowKey="id"
              dataSource={failedRows}
              pagination={{ pageSize: 6 }}
              columns={[
                { title: '类型', dataIndex: 'type', key: 'type', width: 120 },
                { title: '用户', dataIndex: 'username', key: 'username', width: 120, render: (v: string | null) => v || '-' },
                { title: '失败信息', dataIndex: 'content', key: 'content', ellipsis: true },
                { title: '时间', dataIndex: 'created_at', key: 'created_at', width: 170, render: (v: string) => formatDateTime(v) },
              ]}
            />
          </Card>
        </Col>
      </Row>
    </div>
  )
}
