import { useState } from 'react'
import { Input, Space, Button, Select, message } from 'antd'
import { SearchOutlined, ClearOutlined } from '@ant-design/icons'
import { searchApi, type PaperListResponse } from '../api/search'

interface Props {
  zone: string
  folderId: string | null
  onResults: (data: PaperListResponse | null) => void
}

export default function SearchBar({ zone, folderId, onResults }: Props) {
  const [keywords, setKeywords] = useState('')
  const [ragQuery, setRagQuery] = useState('')
  const [loading, setLoading] = useState(false)
  const [order, setOrder] = useState('keyword_first')

  const handleSearch = async () => {
    if (!keywords.trim() && !ragQuery.trim()) {
      onResults(null)
      return
    }
    setLoading(true)
    try {
      if (keywords.trim() && ragQuery.trim()) {
        const res = await searchApi.cascade({
          keywords: keywords.trim(),
          rag_query: ragQuery.trim(),
          folder_id: folderId || undefined,
          zone,
          order,
        })
        onResults(res.data)
      } else if (keywords.trim()) {
        const res = await searchApi.keyword({
          keywords: keywords.trim(),
          folder_id: folderId || undefined,
          zone,
        })
        onResults(res.data)
      } else {
        const res = await searchApi.rag({
          query: ragQuery.trim(),
          folder_id: folderId || undefined,
          zone,
        })
        onResults(res.data)
      }
    } catch (err: any) {
      message.error(err.response?.data?.detail || '搜索失败')
    } finally {
      setLoading(false)
    }
  }

  const handleClear = () => {
    setKeywords('')
    setRagQuery('')
    onResults(null)
  }

  return (
    <Space style={{ marginBottom: 12, width: '100%' }} wrap>
      <Input
        placeholder="关键词搜索（分号分隔多个关键词）"
        value={keywords}
        onChange={(e) => setKeywords(e.target.value)}
        onPressEnter={handleSearch}
        style={{ width: 280 }}
        allowClear
      />
      <Input
        placeholder="RAG语义搜索"
        value={ragQuery}
        onChange={(e) => setRagQuery(e.target.value)}
        onPressEnter={handleSearch}
        style={{ width: 280 }}
        allowClear
      />
      {keywords.trim() && ragQuery.trim() && (
        <Select
          value={order}
          onChange={setOrder}
          style={{ width: 160 }}
          options={[
            { label: '先关键词后RAG', value: 'keyword_first' },
            { label: '先RAG后关键词', value: 'rag_first' },
          ]}
        />
      )}
      <Button type="primary" icon={<SearchOutlined />} onClick={handleSearch} loading={loading}>搜索</Button>
      <Button icon={<ClearOutlined />} onClick={handleClear}>清除</Button>
    </Space>
  )
}
