import { Tag, Tooltip } from 'antd'
import { CheckCircleOutlined, SyncOutlined, ClockCircleOutlined, CloseCircleOutlined } from '@ant-design/icons'

const STATUS_MAP: Record<string, { color: string; text: string; icon: React.ReactNode }> = {
  completed: { color: 'success', text: '已完成', icon: <CheckCircleOutlined /> },
  processing: { color: 'processing', text: '处理中', icon: <SyncOutlined spin /> },
  pending: { color: 'default', text: '等待中', icon: <ClockCircleOutlined /> },
  failed: { color: 'error', text: '失败', icon: <CloseCircleOutlined /> },
}

const STEP_NAMES: Record<string, string> = {
  chunking: '分块向量化',
  title: '标题提取',
  abstract: '摘要提取',
  keywords: '关键词提取',
  report: '阅读报告',
}

interface Props {
  status: string
  stepStatuses?: Record<string, string>
}

export default function StatusTag({ status, stepStatuses }: Props) {
  const info = STATUS_MAP[status] || STATUS_MAP.pending

  const tooltipContent = stepStatuses ? (
    <div>
      {Object.entries(stepStatuses).map(([step, s]) => {
        const si = STATUS_MAP[s] || STATUS_MAP.pending
        return (
          <div key={step} style={{ marginBottom: 2 }}>
            {STEP_NAMES[step] || step}: {si.text}
          </div>
        )
      })}
    </div>
  ) : null

  return (
    <Tooltip title={tooltipContent}>
      <Tag color={info.color} icon={info.icon}>{info.text}</Tag>
    </Tooltip>
  )
}
