import { useState } from 'react'
import { Modal, Upload, message } from 'antd'
import { InboxOutlined } from '@ant-design/icons'
import { filesApi } from '../api/files'

const { Dragger } = Upload

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
  const [uploadedCount, setUploadedCount] = useState(0)
  const [uploadTotal, setUploadTotal] = useState(0)

  const handleUpload = async () => {
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

  return (
    <Modal
      title="上传论文"
      open={open}
      onOk={handleUpload}
      onCancel={() => {
        if (uploading) return
        if (!uploading) {
          setFileList([])
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
    </Modal>
  )
}
