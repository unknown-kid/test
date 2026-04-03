import { Modal, Radio, Space, Typography } from 'antd'
import { useState } from 'react'

const { Text } = Typography

export type ConflictType = 'folder' | 'file'
export type FolderResolution = 'overwrite' | 'merge'
export type FileResolution = 'overwrite' | 'skip'

interface Props {
  open: boolean
  type: ConflictType
  conflictNames: string[]
  onResolve: (resolution: string) => void
  onCancel: () => void
}

export default function ConflictDialog({ open, type, conflictNames, onResolve, onCancel }: Props) {
  const [resolution, setResolution] = useState<string>(type === 'folder' ? 'merge' : 'skip')

  const options = type === 'folder'
    ? [
        { label: '全部覆盖', value: 'overwrite' },
        { label: '全部合并', value: 'merge' },
      ]
    : [
        { label: '全部覆盖', value: 'overwrite' },
        { label: '全部跳过', value: 'skip' },
      ]

  return (
    <Modal
      title={`${type === 'folder' ? '文件夹' : '文件'}名称冲突`}
      open={open}
      onOk={() => onResolve(resolution)}
      onCancel={onCancel}
      okText="确定"
      cancelText="取消"
    >
      <div style={{ marginBottom: 16 }}>
        <Text>以下{type === 'folder' ? '文件夹' : '文件'}存在同名冲突：</Text>
        <ul>
          {conflictNames.map((n) => <li key={n}>{n}</li>)}
        </ul>
      </div>
      <Radio.Group
        value={resolution}
        onChange={(e) => setResolution(e.target.value)}
      >
        <Space direction="vertical">
          {options.map((o) => (
            <Radio key={o.value} value={o.value}>{o.label}</Radio>
          ))}
        </Space>
      </Radio.Group>
    </Modal>
  )
}
