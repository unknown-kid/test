import { useEffect, useMemo, useState } from 'react'
import { Table, Input, Button, message, Spin, Popconfirm, Space, Typography } from 'antd'
import { SaveOutlined } from '@ant-design/icons'
import { adminApi, type ConfigItem } from '../../api/admin'

const { Text } = Typography

const STEP_WORKER_KEYS = [
  'celery_worker_node_count',
  'worker_total_concurrency_limit',
  'chunking_worker_limit',
  'title_worker_limit',
  'abstract_worker_limit',
  'keywords_worker_limit',
  'report_worker_limit',
] as const

const STEP_WORKER_KEY_SET = new Set<string>(STEP_WORKER_KEYS)

export default function Config() {
  const [configs, setConfigs] = useState<ConfigItem[]>([])
  const [loading, setLoading] = useState(false)
  const [editValues, setEditValues] = useState<Record<string, string>>({})
  const [saving, setSaving] = useState<Record<string, boolean>>({})
  const [cleaningStuck, setCleaningStuck] = useState(false)

  const loadConfigs = async () => {
    setLoading(true)
    try {
      const res = await adminApi.getConfigs()
      setConfigs(res.data)
      const vals: Record<string, string> = {}
      res.data.forEach((c) => { vals[c.key] = c.value })
      setEditValues(vals)
    } catch { /* ignore */ }
    finally { setLoading(false) }
  }

  useEffect(() => { loadConfigs() }, [])

  const handleSave = async (key: string) => {
    setSaving((prev) => ({ ...prev, [key]: true }))
    try {
      await adminApi.updateConfig(key, editValues[key])
      message.success(`${key} 已更新`)
      loadConfigs()
    } catch (err: any) {
      message.error(err.response?.data?.detail || '更新失败')
    } finally {
      setSaving((prev) => ({ ...prev, [key]: false }))
    }
  }

  const handleCleanupStuck = async (force = false) => {
    setCleaningStuck(true)
    try {
      const res = await adminApi.cleanupStuckProcessingTasks(force)
      const data = res.data
      message.success(
        `清理完成：扫描${data.scanned_papers || 0}篇，命中${data.matched_papers}篇，置失败${data.failed_papers}篇`
      )
    } catch (err: any) {
      message.error(err.response?.data?.detail || '清理失败')
    } finally {
      setCleaningStuck(false)
    }
  }

  const displayConfigs = useMemo(() => {
    const priorityMap = new Map<string, number>(STEP_WORKER_KEYS.map((key, index) => [key, index]))
    return [...configs].sort((a, b) => {
      const aPriority = priorityMap.get(a.key)
      const bPriority = priorityMap.get(b.key)
      if (aPriority != null && bPriority != null) return aPriority - bPriority
      if (aPriority != null) return -1
      if (bPriority != null) return 1
      return a.key.localeCompare(b.key)
    })
  }, [configs])

  const columns = [
    { title: '配置项', dataIndex: 'key', key: 'key', width: 250 },
    { title: '说明', dataIndex: 'description', key: 'description', width: 250 },
    {
      title: '值', key: 'value',
      render: (_: any, record: ConfigItem) => {
        const isSecret = record.key.includes('api_key')
        const isStepWorker = STEP_WORKER_KEY_SET.has(record.key)
        return (
          <Input
            value={editValues[record.key] || ''}
            onChange={(e) => setEditValues((prev) => ({ ...prev, [record.key]: e.target.value }))}
            type={isSecret ? 'password' : (isStepWorker ? 'number' : 'text')}
            min={isStepWorker ? 1 : undefined}
            step={isStepWorker ? 1 : undefined}
            style={{ width: '100%' }}
          />
        )
      },
    },
    {
      title: '操作', key: 'actions', width: 80,
      render: (_: any, record: ConfigItem) => (
        <Button
          size="small"
          type="primary"
          icon={<SaveOutlined />}
          loading={saving[record.key]}
          disabled={editValues[record.key] === record.value}
          onClick={() => handleSave(record.key)}
        />
      ),
    },
  ]

  if (loading) return <div style={{ textAlign: 'center', padding: 80 }}><Spin size="large" /></div>

  return (
    <div style={{ padding: 24 }}>
      <Space direction="vertical" size={4} style={{ marginBottom: 12 }}>
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
        <Text type="secondary">优先在队列空闲时执行；若队列持续卡住，可用“强制清理”。</Text>
      </Space>
      <Table dataSource={displayConfigs} columns={columns} rowKey="key" pagination={false} size="small" />
    </div>
  )
}
