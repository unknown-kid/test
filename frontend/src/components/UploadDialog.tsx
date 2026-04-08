import { useState } from 'react'
import { Modal, Upload, message, Tabs, Input, Typography } from 'antd'
import { InboxOutlined } from '@ant-design/icons'
import { filesApi } from '../api/files'

const { Dragger } = Upload
const { TextArea } = Input
const { Text } = Typography

interface Props {
  open: boolean
  onClose: () => void
  zone: string
  folderId: string | null
  onSuccess: () => void
}

export default function UploadDialog({ open, onClose, zone, folderId, onSuccess }: Props) {
  const [uploading, setUploading] = useState(false)
  const [fileList, setFileList] = useState<File[]>([])
  const [urlText, setUrlText] = useState('')
  const [activeTab, setActiveTab] = useState<'file' | 'url'>('file')
  const [uploadedCount, setUploadedCount] = useState(0)
  const [uploadTotal, setUploadTotal] = useState(0)

  const handleFileUpload = async () => {
    if (fileList.length === 0) {
      message.warning('请选择PDF文件')
      return
    }
    const queue = [...fileList]
    const total = queue.length
    const concurrency = Math.min(4, total)
    const failedFiles: File[] = []

    const runWorker = async () => {
      while (queue.length > 0) {
        const file = queue.shift()
        if (!file) return
        try {
          await filesApi.uploadPaper(file, zone, folderId || undefined)
        } catch {
          failedFiles.push(file)
        } finally {
          setUploadedCount((prev) => prev + 1)
        }
      }
    }

    setUploading(true)
    setUploadedCount(0)
    setUploadTotal(total)
    try {
      await Promise.all(Array.from({ length: concurrency }, () => runWorker()))
      const successCount = total - failedFiles.length
      if (successCount > 0) {
        onSuccess()
      }
      if (failedFiles.length === 0) {
        message.success(`上传成功：${successCount} 篇`)
        setFileList([])
        onClose()
      } else if (successCount === 0) {
        message.error('上传失败，请重试')
        setFileList(failedFiles)
      } else {
        message.warning(`上传完成：成功 ${successCount}，失败 ${failedFiles.length}`)
        setFileList(failedFiles)
      }
    } finally {
      setUploading(false)
      setUploadTotal(0)
    }
  }

  const handleUrlUpload = async () => {
    const urls = urlText
      .split(/\r?\n/)
      .map((item) => item.trim())
      .filter(Boolean)

    if (urls.length === 0) {
      message.warning('请至少输入一个PDF链接')
      return
    }

    setUploading(true)
    setUploadedCount(0)
    setUploadTotal(urls.length)
    try {
      const res = await filesApi.uploadPapersByUrl(urls, zone, folderId || undefined)
      const results = res.data?.results || []
      const successCount = results.filter((item: any) => item.status === 'success').length
      const failedRows = results.filter((item: any) => item.status !== 'success')

      setUploadedCount(urls.length)
      if (successCount > 0) {
        onSuccess()
      }

      if (failedRows.length === 0) {
        message.success(`链接上传成功：${successCount} 篇`)
        setUrlText('')
        onClose()
        return
      }

      const firstError = failedRows[0]?.error ? `，首个错误：${failedRows[0].error}` : ''
      if (successCount === 0) {
        message.error(`链接上传失败${firstError}`)
      } else {
        message.warning(`链接上传完成：成功 ${successCount}，失败 ${failedRows.length}${firstError}`)
      }
    } finally {
      setUploading(false)
      setUploadTotal(0)
    }
  }

  const handleUpload = async () => {
    if (activeTab === 'url') {
      await handleUrlUpload()
      return
    }
    await handleFileUpload()
  }

  return (
    <Modal
      title="上传论文"
      open={open}
      onOk={handleUpload}
      onCancel={() => {
        if (uploading) return
        if (!uploading) {
          setFileList([])
          setUrlText('')
        }
        onClose()
      }}
      confirmLoading={uploading}
      okText={uploading && uploadTotal > 0 ? `上传中 ${uploadedCount}/${uploadTotal}` : '上传'}
      cancelText="取消"
      cancelButtonProps={{ disabled: uploading }}
      maskClosable={!uploading}
      closable={!uploading}
    >
      {uploading && uploadTotal > 0 && (
        <div style={{ marginBottom: 10, fontSize: 12, color: '#666' }}>
          正在上传：{uploadedCount}/{uploadTotal}
        </div>
      )}
      <Tabs
        activeKey={activeTab}
        onChange={(key) => setActiveTab(key as 'file' | 'url')}
        items={[
          {
            key: 'file',
            label: '文件上传',
            children: (
              <Dragger
                accept=".pdf"
                multiple
                disabled={uploading}
                beforeUpload={(file) => {
                  if (file.size > 100 * 1024 * 1024) {
                    message.error('文件大小不能超过100MB')
                    return Upload.LIST_IGNORE
                  }
                  setFileList((prev) => [...prev, file as unknown as File])
                  return false
                }}
                onRemove={(file) => {
                  setFileList((prev) => prev.filter((f) => f.name !== file.name))
                }}
                fileList={fileList.map((f, i) => ({ uid: `${i}`, name: f.name, status: 'done' as const }))}
              >
                <p className="ant-upload-drag-icon"><InboxOutlined /></p>
                <p className="ant-upload-text">点击或拖拽PDF文件到此区域</p>
                <p className="ant-upload-hint">支持批量上传，单个文件最大100MB</p>
              </Dragger>
            ),
          },
          {
            key: 'url',
            label: '链接上传',
            children: (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                <Text type="secondary">
                  每行一个链接，按回车分隔。后端会直接下载并按普通上传流程处理。
                </Text>
                <TextArea
                  rows={8}
                  disabled={uploading}
                  value={urlText}
                  onChange={(e) => setUrlText(e.target.value)}
                  placeholder={[
                    'https://example.com/paper-1.pdf',
                    'https://example.com/download?id=paper-2',
                  ].join('\n')}
                />
                <Text type="secondary">
                  仅支持真实可下载的 PDF 内容；如果链接不是 PDF，系统会返回对应错误。
                </Text>
              </div>
            ),
          },
        ]}
      />
    </Modal>
  )
}
