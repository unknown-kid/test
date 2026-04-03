import { Space, Button, Popconfirm } from 'antd'
import { DeleteOutlined, UploadOutlined, FolderAddOutlined, ReloadOutlined, DragOutlined, CopyOutlined } from '@ant-design/icons'

interface Props {
  selectedCount: number
  onBatchDelete: () => void
  onBatchMove: () => void
  onUpload: () => void
  onNewFolder: () => void
  onReprocess?: () => void
  reprocessLoading?: boolean
  reprocessButtonText?: string
  readOnly?: boolean
  copyOnly?: boolean
  onBatchCopy?: () => void
  copyButtonText?: string
}

export default function BatchActions({
  selectedCount,
  onBatchDelete,
  onBatchMove,
  onUpload,
  onNewFolder,
  onReprocess,
  reprocessLoading,
  reprocessButtonText,
  readOnly,
  copyOnly,
  onBatchCopy,
  copyButtonText,
}: Props) {
  if (readOnly && !copyOnly) return null

  if (copyOnly) {
    return (
      <Space style={{ marginBottom: 12 }}>
        <Button
          icon={<CopyOutlined />}
          onClick={onBatchCopy}
          disabled={selectedCount === 0}
        >
          {copyButtonText || `批量复制 (${selectedCount})`}
        </Button>
      </Space>
    )
  }

  return (
    <Space style={{ marginBottom: 12 }}>
      <Button icon={<UploadOutlined />} type="primary" onClick={onUpload}>上传论文</Button>
      <Button icon={<FolderAddOutlined />} onClick={onNewFolder}>新建文件夹</Button>
      {selectedCount > 0 && (
        <>
          <Button icon={<DragOutlined />} onClick={onBatchMove}>批量移动 ({selectedCount})</Button>
          <Popconfirm title={`确定删除选中的 ${selectedCount} 篇论文？`} onConfirm={onBatchDelete}>
            <Button danger icon={<DeleteOutlined />}>删除选中 ({selectedCount})</Button>
          </Popconfirm>
        </>
      )}
      {onReprocess && (
        <Button
          icon={<ReloadOutlined />}
          onClick={onReprocess}
          loading={reprocessLoading}
        >
          {reprocessButtonText || '一键补全'}
        </Button>
      )}
    </Space>
  )
}
