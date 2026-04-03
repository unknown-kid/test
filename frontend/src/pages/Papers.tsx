import { useEffect, useState, useRef, useCallback } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import { Layout, Breadcrumb, Input, Modal, message, Tabs, Button, TreeSelect, Spin } from 'antd'
import { HomeOutlined, LogoutOutlined, SettingOutlined } from '@ant-design/icons'
import { useFileStore } from '../stores/fileStore'
import { useAuthStore } from '../stores/authStore'
import { filesApi, type FolderTreeNode } from '../api/files'
import FileList from '../components/FileList'
import FolderTree from '../components/FolderTree'
import BatchActions from '../components/BatchActions'
import UploadDialog from '../components/UploadDialog'
import SearchBar from '../components/SearchBar'
import NotificationButton from '../components/NotificationButton'
import type { PaperListResponse } from '../api/search'

const { Sider, Content, Header } = Layout

const ROOT_KEY = '__root__'

function buildFolderOptions(nodes: FolderTreeNode[]): any[] {
  return nodes.map((node) => ({
    title: `${node.name} (${node.paper_count})`,
    value: node.id,
    key: node.id,
    children: buildFolderOptions(node.children),
  }))
}

export default function Papers({ forceZone }: { forceZone?: 'shared' | 'personal' }) {
  const navigate = useNavigate()
  const location = useLocation()
  const isAdmin = location.pathname.startsWith('/admin')
  const isShared = forceZone === 'shared' || location.pathname.includes('/shared')

  const {
    zone, currentFolderId, contents, folderTree, loading,
    page, pageSize, setZone, setCurrentFolder, setPage, setPageSize,
    fetchContents, fetchTree,
  } = useFileStore()
  const { user, logout } = useAuthStore()

  const [selectedPaperIds, setSelectedPaperIds] = useState<string[]>([])
  const [uploadOpen, setUploadOpen] = useState(false)
  const [newFolderName, setNewFolderName] = useState('')
  const [newFolderOpen, setNewFolderOpen] = useState(false)
  const [searchResults, setSearchResults] = useState<PaperListResponse | null>(null)
  const [transferOpen, setTransferOpen] = useState(false)
  const [transferMode, setTransferMode] = useState<'move' | 'copy'>('move')
  const [transferPaperId, setTransferPaperId] = useState<string | null>(null)
  const [transferTarget, setTransferTarget] = useState<string>(ROOT_KEY)
  const [transferLoading, setTransferLoading] = useState(false)
  const [batchMoveOpen, setBatchMoveOpen] = useState(false)
  const [batchMoveTarget, setBatchMoveTarget] = useState<string>(ROOT_KEY)
  const [batchMoveLoading, setBatchMoveLoading] = useState(false)
  const [batchCopyOpen, setBatchCopyOpen] = useState(false)
  const [batchCopyTarget, setBatchCopyTarget] = useState<string>(ROOT_KEY)
  const [batchCopyLoading, setBatchCopyLoading] = useState(false)
  const [reprocessLoading, setReprocessLoading] = useState(false)
  const [personalFolderTree, setPersonalFolderTree] = useState<FolderTreeNode[]>([])
  const [personalTreeLoading, setPersonalTreeLoading] = useState(false)
  const [siderWidth, setSiderWidth] = useState(240)
  const draggingRef = useRef(false)
  const resizeStartXRef = useRef(0)
  const resizeStartWidthRef = useRef(240)
  const MIN_SIDER_WIDTH = 200
  const MAX_SIDER_WIDTH = 420

  useEffect(() => {
    const z = isShared ? 'shared' : 'personal'
    if (zone !== z) setZone(z as any)
  }, [isShared])

  useEffect(() => {
    fetchContents()
    fetchTree()
  }, [zone, currentFolderId, page, pageSize])

  const handleFolderClick = (folderId: string) => {
    setCurrentFolder(folderId)
  }

  const handleDeleteFolder = async (folderId: string) => {
    try {
      await filesApi.deleteFolder(folderId)
      message.success('文件夹已删除')
      fetchContents()
      fetchTree()
    } catch (err: any) {
      message.error(err.response?.data?.detail || '删除失败')
    }
  }

  const handleDeletePaper = async (paperId: string) => {
    try {
      await filesApi.deletePaper(paperId)
      message.success('论文已删除')
      fetchContents()
    } catch (err: any) {
      message.error(err.response?.data?.detail || '删除失败')
    }
  }

  const handleBatchDelete = async () => {
    try {
      await filesApi.batchDeletePapers(selectedPaperIds)
      message.success('批量删除完成')
      setSelectedPaperIds([])
      fetchContents()
    } catch (err: any) {
      message.error(err.response?.data?.detail || '批量删除失败')
    }
  }

  const handleOpenBatchMove = () => {
    if (selectedPaperIds.length === 0) return
    setBatchMoveTarget(currentFolderId || ROOT_KEY)
    setBatchMoveOpen(true)
  }

  const handleBatchMove = async () => {
    if (selectedPaperIds.length === 0) return
    const targetFolderId = batchMoveTarget === ROOT_KEY ? null : batchMoveTarget
    setBatchMoveLoading(true)
    try {
      const res = await filesApi.batchMovePapers(selectedPaperIds, targetFolderId)
      const { success = 0, failed = 0 } = res.data || {}
      if (failed > 0) {
        message.warning(`批量移动完成：成功 ${success}，失败 ${failed}`)
      } else {
        message.success(`批量移动完成：${success} 篇`)
      }
      setBatchMoveOpen(false)
      setSelectedPaperIds([])
      setSearchResults(null)
      fetchContents()
      fetchTree()
    } catch (err: any) {
      message.error(err.response?.data?.detail || '批量移动失败')
    } finally {
      setBatchMoveLoading(false)
    }
  }

  const loadPersonalFolderTree = async () => {
    setPersonalTreeLoading(true)
    try {
      const res = await filesApi.getFolderTree('personal')
      setPersonalFolderTree(res.data || [])
    } catch (err: any) {
      message.error(err.response?.data?.detail || '加载个人区目录失败')
      setPersonalFolderTree([])
    } finally {
      setPersonalTreeLoading(false)
    }
  }

  const handleOpenBatchCopy = async () => {
    if (selectedPaperIds.length === 0) return
    setBatchCopyTarget(ROOT_KEY)
    setBatchCopyOpen(true)
    await loadPersonalFolderTree()
  }

  const handleBatchCopy = async () => {
    if (selectedPaperIds.length === 0) return
    const targetFolderId = batchCopyTarget === ROOT_KEY ? null : batchCopyTarget
    setBatchCopyLoading(true)
    try {
      const res = await filesApi.batchCopyPapers(selectedPaperIds, targetFolderId)
      const { success = 0, failed = 0 } = res.data || {}
      if (failed > 0) {
        message.warning(`批量复制已提交：成功 ${success}，失败 ${failed}`)
      } else {
        message.success(`批量复制已提交：${success} 篇`)
      }
      setBatchCopyOpen(false)
      setSelectedPaperIds([])
    } catch (err: any) {
      message.error(err.response?.data?.detail || '批量复制失败')
    } finally {
      setBatchCopyLoading(false)
    }
  }

  const handleNewFolder = async () => {
    if (!newFolderName.trim()) return
    try {
      await filesApi.createFolder(newFolderName.trim(), zone, currentFolderId || undefined)
      message.success('文件夹已创建')
      setNewFolderOpen(false)
      setNewFolderName('')
      fetchContents()
      fetchTree()
    } catch (err: any) {
      message.error(err.response?.data?.detail || '创建失败')
    }
  }

  const handlePaperClick = (paperId: string) => {
    if (isAdmin) {
      navigate(`/admin/papers/${paperId}`)
      return
    }
    window.open(`/paper/${paperId}`, '_blank')
  }

  const openTransfer = (paperId: string, mode: 'move' | 'copy') => {
    setTransferPaperId(paperId)
    setTransferMode(mode)
    setTransferTarget(currentFolderId || ROOT_KEY)
    setTransferOpen(true)
  }

  const handleMovePaper = (paperId: string) => {
    openTransfer(paperId, 'move')
  }

  const handleCopyPaper = (paperId: string) => {
    openTransfer(paperId, 'copy')
  }

  const handleTransfer = async () => {
    if (!transferPaperId) return
    const targetFolderId = transferTarget === ROOT_KEY ? null : transferTarget
    setTransferLoading(true)
    try {
      if (transferMode === 'move') {
        await filesApi.movePaper(transferPaperId, targetFolderId)
        message.success('论文已移动')
      } else {
        await filesApi.copyPaper(transferPaperId, targetFolderId)
        message.success('复制任务已提交')
      }
      setTransferOpen(false)
      setTransferPaperId(null)
      setSearchResults(null)
      fetchContents()
      fetchTree()
    } catch (err: any) {
      message.error(err.response?.data?.detail || (transferMode === 'move' ? '移动失败' : '复制失败'))
    } finally {
      setTransferLoading(false)
    }
  }

  const handleLogout = async () => {
    await logout()
    navigate('/login')
  }

  const isSharedUserView = zone === 'shared' && user?.role === 'user'
  const readOnly = isSharedUserView

  const handleReprocessFailed = () => {
    Modal.confirm({
      title: '重跑失败论文',
      content: '将重跑当前目录（含子目录）中失败论文的5步提取任务，是否继续？',
      okText: '开始重跑',
      cancelText: '取消',
      onOk: async () => {
        setReprocessLoading(true)
        try {
          const res = await filesApi.reprocessPapers(zone, currentFolderId || undefined, true)
          const total = Number(res.data?.total || 0)
          if (total === 0) {
            message.info('当前目录下没有失败论文')
          } else {
            message.success(res.data?.message || `已提交 ${total} 篇失败论文重跑任务`)
          }
          setSearchResults(null)
          fetchContents()
        } catch (err: any) {
          message.error(err.response?.data?.detail || '重跑失败论文任务提交失败')
        } finally {
          setReprocessLoading(false)
        }
      },
    })
  }

  const handleResizeMouseDown = useCallback((e: React.MouseEvent<HTMLDivElement>) => {
    e.preventDefault()
    draggingRef.current = true
    resizeStartXRef.current = e.clientX
    resizeStartWidthRef.current = siderWidth
    document.body.style.cursor = 'col-resize'
    document.body.style.userSelect = 'none'

    const onMouseMove = (ev: MouseEvent) => {
      if (!draggingRef.current) return
      const delta = ev.clientX - resizeStartXRef.current
      const nextWidth = Math.min(
        MAX_SIDER_WIDTH,
        Math.max(MIN_SIDER_WIDTH, resizeStartWidthRef.current + delta),
      )
      setSiderWidth(nextWidth)
    }

    const onMouseUp = () => {
      draggingRef.current = false
      document.body.style.cursor = ''
      document.body.style.userSelect = ''
      document.removeEventListener('mousemove', onMouseMove)
      document.removeEventListener('mouseup', onMouseUp)
    }

    document.addEventListener('mousemove', onMouseMove)
    document.addEventListener('mouseup', onMouseUp)
  }, [siderWidth])

  return (
    <Layout style={{ minHeight: isAdmin ? 'auto' : '100vh' }}>
      {!isAdmin && (
        <Header style={{ background: '#fff', display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '0 24px', borderBottom: '1px solid #f0f0f0' }}>
          <span style={{ fontSize: 18, fontWeight: 600 }}>AI论文阅读平台</span>
          <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
            <span>{user?.username}</span>
            <NotificationButton />
            <Button size="small" icon={<SettingOutlined />} onClick={() => navigate('/settings')}>设置</Button>
            <Button size="small" icon={<LogoutOutlined />} onClick={handleLogout}>退出</Button>
          </div>
        </Header>
      )}
      <Layout>
        <Sider
          width={siderWidth}
          style={{
            background: '#fff',
            borderRight: '1px solid #f0f0f0',
            padding: 12,
            width: siderWidth,
            flex: `0 0 ${siderWidth}px`,
            maxWidth: siderWidth,
            minWidth: siderWidth,
          }}
        >
          {!isAdmin && (
            <Tabs
              activeKey={zone}
              onChange={(k) => {
                navigate(k === 'shared' ? '/papers/shared' : '/papers/my')
              }}
              items={[
                { key: 'personal', label: '个人区' },
                { key: 'shared', label: '共享区' },
              ]}
              size="small"
            />
          )}
          {isAdmin && <div style={{ padding: '8px 0', fontWeight: 600 }}>共享区论文</div>}
          <FolderTree
            tree={folderTree}
            onSelect={(id) => setCurrentFolder(id)}
            selectedId={currentFolderId}
          />
        </Sider>
        <div
          onMouseDown={handleResizeMouseDown}
          style={{
            width: 5,
            cursor: 'col-resize',
            background: '#e8e8e8',
            flex: '0 0 5px',
            transition: 'background 0.2s',
          }}
          onMouseEnter={(e) => { e.currentTarget.style.background = '#bbb' }}
          onMouseLeave={(e) => { if (!draggingRef.current) e.currentTarget.style.background = '#e8e8e8' }}
        />
        <Content style={{ padding: 16, minWidth: 0 }}>
          <Breadcrumb
            style={{ marginBottom: 12 }}
            items={[
              {
                title: <span onClick={() => { setCurrentFolder(null); setSearchResults(null) }} style={{ cursor: 'pointer' }}><HomeOutlined /> {zone === 'shared' ? '共享区' : '个人区'}</span>,
              },
              ...(contents?.breadcrumbs.map((b) => ({
                title: <span onClick={() => { setCurrentFolder(b.id); setSearchResults(null) }} style={{ cursor: 'pointer' }}>{b.name}</span>,
              })) || []),
            ]}
          />

          <SearchBar zone={zone} folderId={currentFolderId} onResults={setSearchResults} />

          <BatchActions
            selectedCount={selectedPaperIds.length}
            onBatchDelete={handleBatchDelete}
            onBatchMove={handleOpenBatchMove}
            onUpload={() => setUploadOpen(true)}
            onNewFolder={() => setNewFolderOpen(true)}
            onReprocess={readOnly ? undefined : handleReprocessFailed}
            reprocessLoading={reprocessLoading}
            reprocessButtonText="一键重跑失败论文(5步)"
            readOnly={readOnly}
            copyOnly={isSharedUserView}
            onBatchCopy={isSharedUserView ? handleOpenBatchCopy : undefined}
            copyButtonText={`批量复制到个人区 (${selectedPaperIds.length})`}
          />

          <FileList
            folders={searchResults ? [] : (contents?.folders || [])}
            papers={searchResults ? searchResults.items : (contents?.papers.items || [])}
            total={searchResults ? searchResults.total : (contents?.papers.total || 0)}
            page={searchResults ? searchResults.page : page}
            pageSize={searchResults ? searchResults.page_size : pageSize}
            loading={loading}
            selectedPaperIds={selectedPaperIds}
            onSelectPapers={setSelectedPaperIds}
            onFolderClick={handleFolderClick}
            onDeleteFolder={handleDeleteFolder}
            onDeletePaper={handleDeletePaper}
            onMovePaper={handleMovePaper}
            onCopyPaper={handleCopyPaper}
            onPageChange={(p, ps) => {
              if (ps !== pageSize) {
                setPageSize(ps)
              } else {
                setPage(p)
              }
            }}
            onPaperClick={handlePaperClick}
            readOnly={readOnly}
            selectionEnabled={!readOnly || isSharedUserView}
          />

          <UploadDialog
            open={uploadOpen}
            onClose={() => setUploadOpen(false)}
            zone={zone}
            folderId={currentFolderId}
            onSuccess={() => { fetchContents(); fetchTree() }}
          />

          <Modal
            title="新建文件夹"
            open={newFolderOpen}
            onOk={handleNewFolder}
            onCancel={() => { setNewFolderOpen(false); setNewFolderName('') }}
            okText="创建"
            cancelText="取消"
          >
            <Input
              placeholder="文件夹名称"
              value={newFolderName}
              onChange={(e) => setNewFolderName(e.target.value)}
              onPressEnter={handleNewFolder}
            />
          </Modal>

          <Modal
            title={transferMode === 'move' ? '移动论文' : '复制论文'}
            open={transferOpen}
            onOk={handleTransfer}
            onCancel={() => { setTransferOpen(false); setTransferPaperId(null) }}
            okText={transferMode === 'move' ? '移动' : '复制'}
            cancelText="取消"
            confirmLoading={transferLoading}
          >
            <TreeSelect
              value={transferTarget}
              style={{ width: '100%' }}
              treeData={[
                { title: '根目录', value: ROOT_KEY, key: ROOT_KEY, children: buildFolderOptions(folderTree) },
              ]}
              treeDefaultExpandAll
              onChange={(value) => setTransferTarget(String(value))}
              placeholder="选择目标文件夹"
            />
          </Modal>

          <Modal
            title="批量移动论文"
            open={batchMoveOpen}
            onOk={handleBatchMove}
            onCancel={() => setBatchMoveOpen(false)}
            okText="移动"
            cancelText="取消"
            confirmLoading={batchMoveLoading}
          >
            <TreeSelect
              value={batchMoveTarget}
              style={{ width: '100%' }}
              treeData={[
                { title: '根目录', value: ROOT_KEY, key: ROOT_KEY, children: buildFolderOptions(folderTree) },
              ]}
              treeDefaultExpandAll
              onChange={(value) => setBatchMoveTarget(String(value))}
              placeholder="选择目标文件夹"
            />
          </Modal>

          <Modal
            title="批量复制到个人区"
            open={batchCopyOpen}
            onOk={handleBatchCopy}
            onCancel={() => setBatchCopyOpen(false)}
            okText="复制"
            cancelText="取消"
            confirmLoading={batchCopyLoading}
          >
            <Spin spinning={personalTreeLoading}>
              <TreeSelect
                value={batchCopyTarget}
                style={{ width: '100%' }}
                treeData={[
                  { title: '个人区根目录', value: ROOT_KEY, key: ROOT_KEY, children: buildFolderOptions(personalFolderTree) },
                ]}
                treeDefaultExpandAll
                onChange={(value) => setBatchCopyTarget(String(value))}
                placeholder="选择个人区目标文件夹"
              />
            </Spin>
          </Modal>
        </Content>
      </Layout>
    </Layout>
  )
}
