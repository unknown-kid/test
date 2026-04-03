import { Tree } from 'antd'
import { FolderOutlined } from '@ant-design/icons'
import type { FolderTreeNode } from '../api/files'

interface Props {
  tree: FolderTreeNode[]
  onSelect: (folderId: string | null) => void
  selectedId: string | null
}

function buildTreeData(nodes: FolderTreeNode[]): any[] {
  return nodes.map((n) => ({
    key: n.id,
    title: `${n.name} (${n.paper_count})`,
    icon: <FolderOutlined />,
    children: n.children.length > 0 ? buildTreeData(n.children) : undefined,
  }))
}

export default function FolderTree({ tree, onSelect, selectedId }: Props) {
  return (
    <Tree
      showIcon
      defaultExpandAll
      selectedKeys={selectedId ? [selectedId] : []}
      treeData={[
        { key: '__root__', title: '根目录', icon: <FolderOutlined />, children: buildTreeData(tree) },
      ]}
      onSelect={(keys) => {
        const key = keys[0] as string
        onSelect(key === '__root__' ? null : key)
      }}
      style={{ minHeight: 200 }}
    />
  )
}
