import { useEffect, useState } from 'react'
import { Card, Form, Input, Select, Button, message, Alert, Space, Spin, Divider, Row, Col } from 'antd'
import { SaveOutlined, ApiOutlined } from '@ant-design/icons'
import { adminApi, type ConfigItem } from '../../api/admin'

const MODEL_KEYS = {
  chat: { url: 'chat_api_url', key: 'chat_api_key', model: 'chat_model_name' },
  embedding: { url: 'embedding_api_url', key: 'embedding_api_key', model: 'embedding_model_name' },
  translate: { url: 'translate_api_url', key: 'translate_api_key', model: 'translate_model_name', type: 'translate_type' },
}

export default function Models() {
  const [configs, setConfigs] = useState<Record<string, string>>({})
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState<Record<string, boolean>>({})
  const [testing, setTesting] = useState<Record<string, boolean>>({})
  const [testResult, setTestResult] = useState<Record<string, { success: boolean; message: string }>>({})

  const [chatForm] = Form.useForm()
  const [embedForm] = Form.useForm()
  const [transForm] = Form.useForm()

  const loadConfigs = async () => {
    setLoading(true)
    try {
      const res = await adminApi.getConfigs()
      const map: Record<string, string> = {}
      res.data.forEach((c: ConfigItem) => { map[c.key] = c.value })
      setConfigs(map)
      chatForm.setFieldsValue({
        api_url: map.chat_api_url || '',
        api_key: map.chat_api_key || '',
        model_name: map.chat_model_name || '',
      })
      embedForm.setFieldsValue({
        api_url: map.embedding_api_url || '',
        api_key: map.embedding_api_key || '',
        model_name: map.embedding_model_name || '',
      })
      transForm.setFieldsValue({
        translate_type: map.translate_type || 'openai',
        api_url: map.translate_api_url || '',
        api_key: map.translate_api_key || '',
        model_name: map.translate_model_name || '',
      })
    } catch { /* ignore */ }
    finally { setLoading(false) }
  }

  useEffect(() => { loadConfigs() }, [])

  const handleSave = async (type: string, values: any) => {
    setSaving(p => ({ ...p, [type]: true }))
    try {
      const keys = MODEL_KEYS[type as keyof typeof MODEL_KEYS]
      const updates: Promise<any>[] = []
      if (keys.url) updates.push(adminApi.updateConfig((keys as any).url, values.api_url || ''))
      if (keys.key) updates.push(adminApi.updateConfig((keys as any).key, values.api_key || ''))
      if (keys.model) updates.push(adminApi.updateConfig((keys as any).model, values.model_name || ''))
      if ('type' in keys && values.translate_type) updates.push(adminApi.updateConfig(keys.type!, values.translate_type))
      await Promise.all(updates)
      message.success('配置已保存')
      loadConfigs()
    } catch (err: any) {
      message.error(err.response?.data?.detail || '保存失败')
    } finally {
      setSaving(p => ({ ...p, [type]: false }))
    }
  }

  const handleTest = async (type: string, values: any) => {
    setTesting(p => ({ ...p, [type]: true }))
    setTestResult(p => ({ ...p, [type]: undefined as any }))
    try {
      const req: any = {
        model_type: type,
        api_url: values.api_url || '',
        api_key: values.api_key || '',
        model_name: values.model_name || '',
      }
      if (type === 'translate') req.translate_type = values.translate_type || 'openai'
      const res = await adminApi.testModel(req)
      setTestResult(p => ({ ...p, [type]: res.data }))
    } catch {
      setTestResult(p => ({ ...p, [type]: { success: false, message: '请求失败' } }))
    } finally {
      setTesting(p => ({ ...p, [type]: false }))
    }
  }

  const transType = Form.useWatch('translate_type', transForm)
  const isDeepL = transType === 'deepl'

  if (loading) return <div style={{ textAlign: 'center', padding: 80 }}><Spin size="large" /></div>

  return (
    <div style={{ padding: 24 }}>
      <Row gutter={16}>
        <Col span={8}>
          <Card title="对话模型" size="small">
            <Form form={chatForm} layout="vertical" onFinish={(v) => handleSave('chat', v)}>
              <Form.Item name="api_url" label="API地址"><Input placeholder="https://api.openai.com/v1" /></Form.Item>
              <Form.Item name="api_key" label="API密钥"><Input.Password placeholder="sk-..." /></Form.Item>
              <Form.Item name="model_name" label="模型名称"><Input placeholder="gpt-4o-mini" /></Form.Item>
              <Form.Item>
                <Space>
                  <Button type="primary" htmlType="submit" icon={<SaveOutlined />} loading={saving.chat}>保存</Button>
                  <Button icon={<ApiOutlined />} loading={testing.chat} onClick={() => handleTest('chat', chatForm.getFieldsValue())}>测试</Button>
                </Space>
              </Form.Item>
            </Form>
            {testResult.chat && <Alert type={testResult.chat.success ? 'success' : 'error'} message={testResult.chat.success ? '连接成功' : '连接失败'} description={testResult.chat.message} showIcon />}
          </Card>
        </Col>

        <Col span={8}>
          <Card title="嵌入模型" size="small">
            <Form form={embedForm} layout="vertical" onFinish={(v) => handleSave('embedding', v)}>
              <Form.Item name="api_url" label="API地址"><Input placeholder="https://api.openai.com/v1" /></Form.Item>
              <Form.Item name="api_key" label="API密钥"><Input.Password placeholder="sk-..." /></Form.Item>
              <Form.Item name="model_name" label="模型名称"><Input placeholder="text-embedding-3-small" /></Form.Item>
              <Form.Item>
                <Space>
                  <Button type="primary" htmlType="submit" icon={<SaveOutlined />} loading={saving.embedding}>保存</Button>
                  <Button icon={<ApiOutlined />} loading={testing.embedding} onClick={() => handleTest('embedding', embedForm.getFieldsValue())}>测试</Button>
                </Space>
              </Form.Item>
            </Form>
            {testResult.embedding && <Alert type={testResult.embedding.success ? 'success' : 'error'} message={testResult.embedding.success ? '连接成功' : '连接失败'} description={testResult.embedding.message} showIcon />}
          </Card>
        </Col>

        <Col span={8}>
          <Card title="翻译模型" size="small">
            <Form form={transForm} layout="vertical" onFinish={(v) => handleSave('translate', v)}>
              <Form.Item name="translate_type" label="翻译类型">
                <Select options={[{ value: 'openai', label: 'OpenAI兼容' }, { value: 'deepl', label: 'DeepL' }]} />
              </Form.Item>
              {!isDeepL && <Form.Item name="api_url" label="API地址"><Input placeholder="https://api.openai.com/v1 或完整 /chat/completions 地址" /></Form.Item>}
              {isDeepL && <Form.Item name="api_url" label="API地址"><Input placeholder="https://api-free.deepl.com/v2/translate (留空使用默认)" /></Form.Item>}
              <Form.Item name="api_key" label="API密钥"><Input.Password placeholder={isDeepL ? 'DeepL API Key' : 'sk-...'} /></Form.Item>
              {!isDeepL && <Form.Item name="model_name" label="模型名称"><Input placeholder="gpt-4o-mini" /></Form.Item>}
              <Form.Item>
                <Space>
                  <Button type="primary" htmlType="submit" icon={<SaveOutlined />} loading={saving.translate}>保存</Button>
                  <Button icon={<ApiOutlined />} loading={testing.translate} onClick={() => handleTest('translate', transForm.getFieldsValue())}>测试</Button>
                </Space>
              </Form.Item>
            </Form>
            {testResult.translate && <Alert type={testResult.translate.success ? 'success' : 'error'} message={testResult.translate.success ? '连接成功' : '连接失败'} description={testResult.translate.message} showIcon />}
          </Card>
        </Col>
      </Row>
    </div>
  )
}
