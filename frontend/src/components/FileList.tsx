import { Table, Space, Button, Popconfirm, Typography } from 'antd'
import { FolderOutlined, FileOutlined, DeleteOutlined, DragOutlined, CopyOutlined } from '@ant-design/icons'
import type { PaperInfo, FolderInfo } from '../api/files'
import StatusTag from './StatusTag'
import dayjs from 'dayjs'

const { Text } = Typography

interface Props {
  folders: FolderInfo[]
  papers: PaperInfo[]
  total: number
  page: number
  pageSize: number
  loading: boolean
  selectedPaperIds: string[]
  onSelectPapers: (ids: string[]) => void
  onFolderClick: (folderId: string) => void
  onDeleteFolder: (folderId: string) => void
  onDeletePaper: (paperId: string) => void
  onMovePaper: (paperId: string) => void
  onCopyPaper: (paperId: string) => void
  onPageChange: (page: number, pageSize: number) => void
  onPaperClick: (paperId: string) => void
  readOnly?: boolean
  selectionEnabled?: boolean
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function formatSimilarity(score: number | null | undefined): string {
  if (typeof score !== 'number') return '-'
  return `${(score * 100).toFixed(2)}%`
}

export default function FileList({
  folders, papers, total, page, pageSize, loading,
  selectedPaperIds, onSelectPapers,
  onFolderClick, onDeleteFolder, onDeletePaper,
  onMovePaper, onCopyPaper,
  onPageChange, onPaperClick, readOnly, selectionEnabled = true,
}: Props) {
  const folderRows = folders.map((f) => ({
    key: `folder-${f.id}`,
    type: 'folder' as const,
    id: f.id,
    name: f.name,
    size: null,
    status: null,
    stepStatuses: null,
    paperCount: f.paper_count,
    createdAt: f.created_at,
  }))

  const paperRows = papers.map((p) => ({
    key: `paper-${p.id}`,
    type: 'paper' as const,
    id: p.id,
    name: p.title || p.original_filename || '未命名',
    similarityScore: p.similarity_score ?? null,
    size: p.file_size,
    status: p.processing_status,
    stepStatuses: p.step_statuses,
    paperCount: null,
    createdAt: p.created_at,
  }))

  const dataSource = [...folderRows, ...paperRows]
  const hasSimilarity = papers.some((p) => typeof p.similarity_score === 'number')

  const columns = [
    {
      title: '名称',
      dataIndex: 'name',
      key: 'name',
      render: (name: string, record: any) => (
        <Space
          style={{ cursor: 'pointer' }}
          onClick={() => record.type === 'folder' ? onFolderClick(record.id) : onPaperClick(record.id)}
        >
          {record.type === 'folder' ? <FolderOutlined style={{ color: '#faad14' }} /> : <FileOutlined style={{ color: '#1890ff' }} />}
          <Text>{name}</Text>
          {record.type === 'folder' && <Text type="secondary">({record.paperCount})</Text>}
        </Space>
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 100,
      render: (status: string | null, record: any) =>
        status ? <StatusTag status={status} stepStatuses={record.stepStatuses} /> : null,
    },
    ...(hasSimilarity ? [{
      title: '相似度',
      dataIndex: 'similarityScore',
      key: 'similarityScore',
      width: 100,
      render: (score: number | null, record: any) => record.type === 'paper' ? formatSimilarity(score) : '-',
      sorter: (a: any, b: any) => (b.similarityScore ?? -1) - (a.similarityScore ?? -1),
      defaultSortOrder: 'descend' as const,
    }] : []),
    {
      title: '大小',
      dataIndex: 'size',
      key: 'size',
      width: 100,
      render: (size: number | null) => size !== null ? formatSize(size) : '-',
    },
    {
      title: '时间',
      dataIndex: 'createdAt',
      key: 'createdAt',
      width: 160,
      render: (t: string) => dayjs(t).format('YYYY-MM-DD HH:mm'),
    },
    ...(!readOnly ? [{
      title: '操作',
      key: 'actions',
      width: 140,
      render: (_: any, record: any) => (
        <Space size={0}>
          {record.type === 'paper' && (
            <>
              <Button
                type="text"
                size="small"
                icon={<DragOutlined />}
                title="移动"
                onClick={() => onMovePaper(record.id)}
              />
              <Button
                type="text"
                size="small"
                icon={<CopyOutlined />}
                title="复制"
                onClick={() => onCopyPaper(record.id)}
              />
            </>
          )}
          <Popconfirm
            title={`确定删除${record.type === 'folder' ? '文件夹' : '论文'}？`}
            onConfirm={() => record.type === 'folder' ? onDeleteFolder(record.id) : onDeletePaper(record.id)}
          >
            <Button type="text" danger icon={<DeleteOutlined />} size="small" />
          </Popconfirm>
        </Space>
      ),
    }] : []),
  ]

  return (
    <Table
      dataSource={dataSource}
      columns={columns}
      loading={loading}
      size="small"
      rowSelection={selectionEnabled ? {
        selectedRowKeys: selectedPaperIds.map((id) => `paper-${id}`),
        onChange: (keys) => {
          const ids = (keys as string[])
            .filter((k) => k.startsWith('paper-'))
            .map((k) => k.replace('paper-', ''))
          onSelectPapers(ids)
        },
        getCheckboxProps: (record: any) => ({
          disabled: record.type === 'folder',
        }),
      } : undefined}
      pagination={{
        current: page,
        pageSize,
        total: total + folders.length,
        showSizeChanger: true,
        pageSizeOptions: ['10', '20', '50', '100'],
        onChange: onPageChange,
        showTotal: (t) => `共 ${t} 项`,
      }}
    />
  )
}
