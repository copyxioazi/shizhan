import { ReloadOutlined, SaveOutlined } from '@ant-design/icons'
import {
  Alert,
  Button,
  Card,
  Checkbox,
  Col,
  Form,
  Input,
  InputNumber,
  Row,
  Select,
  Space,
  Switch,
  Typography,
  message,
} from 'antd'
import { useCallback, useEffect, useState } from 'react'
import { systemApi } from '../api'
import type { ConfigMap } from '../types'

type FormValues = Record<string, any>

function toFormValues(config: ConfigMap): FormValues {
  const allowlist = config['sandbox.command_allowlist']
  return {
    ...config,
    'sandbox.command_allowlist': Array.isArray(allowlist)
      ? allowlist.join(', ')
      : String(allowlist ?? ''),
    'llm.api_key': '',
  }
}

export function SettingsPage() {
  const [form] = Form.useForm<FormValues>()
  const [config, setConfig] = useState<ConfigMap>({})
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [clearApiKey, setClearApiKey] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const data = await systemApi.config()
      setConfig(data)
      setClearApiKey(false)
      form.setFieldsValue(toFormValues(data))
    } catch (error) {
      message.error((error as Error).message)
    } finally {
      setLoading(false)
    }
  }, [form])

  useEffect(() => {
    void load()
  }, [load])

  const onSave = async () => {
    try {
      const values = await form.validateFields()
      setSaving(true)
      const payload: Record<string, unknown> = { ...values }
      const allowlist = String(values['sandbox.command_allowlist'] || '')
        .split(',')
        .map((item) => item.trim())
        .filter(Boolean)
      payload['sandbox.command_allowlist'] = allowlist
      const apiKey = String(values['llm.api_key'] || '')
      delete payload['llm.api_key']
      if (apiKey) {
        payload['llm.api_key'] = apiKey
      } else if (clearApiKey) {
        // 空字符串表示显式清空已配置的 Key，运行时会切回规则引擎
        payload['llm.api_key'] = ''
      }

      const updated = await systemApi.updateConfig(payload)
      setConfig(updated)
      setClearApiKey(false)
      form.setFieldsValue(toFormValues(updated))
      message.success('配置已保存，对之后启动的任务生效')
    } catch (error) {
      if (error instanceof Error) message.error(error.message)
    } finally {
      setSaving(false)
    }
  }

  const maskedKey = String(config['llm.api_key'] || '')

  return (
    <Card
      className="page-card"
      title="系统配置"
      extra={
        <Space>
          <Button icon={<ReloadOutlined />} onClick={() => void load()}>
            重新加载
          </Button>
          <Button
            type="primary"
            icon={<SaveOutlined />}
            loading={saving}
            onClick={() => void onSave()}
          >
            保存配置
          </Button>
        </Space>
      }
    >
      <Alert
        type="warning"
        showIcon
        style={{ marginBottom: 20 }}
        message="修改对之后启动的任务生效，正在运行的项目使用启动时的配置快照。"
      />
      <Form<FormValues> form={form} layout="vertical" disabled={loading}>
        <Card type="inner" title="隔离环境" style={{ marginBottom: 16 }}>
          <Row gutter={16}>
            <Col xs={24} md={8}>
              <Form.Item label="默认隔离类型" name="isolation.default_type">
                <Select
                  options={[
                    { value: 'docker', label: 'Docker 容器' },
                    { value: 'local', label: '本机目录（P2）', disabled: true },
                  ]}
                />
              </Form.Item>
            </Col>
            <Col xs={24} md={8}>
              <Form.Item label="沙箱镜像" name="sandbox.image">
                <Input placeholder="ase-sandbox:1.0" />
              </Form.Item>
            </Col>
            <Col xs={24} md={8}>
              <Form.Item
                label="允许沙箱访问外网"
                name="sandbox.network_enabled"
                valuePropName="checked"
              >
                <Switch checkedChildren="允许" unCheckedChildren="禁止" />
              </Form.Item>
            </Col>
            <Col xs={12} md={6}>
              <Form.Item label="CPU 核数上限" name="sandbox.cpu_limit">
                <InputNumber min={0.1} max={8} step={0.1} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col xs={12} md={6}>
              <Form.Item label="内存上限 (MB)" name="sandbox.memory_limit_mb">
                <InputNumber min={128} max={8192} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col xs={12} md={6}>
              <Form.Item label="PID 上限" name="sandbox.pids_limit">
                <InputNumber min={16} max={4096} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col xs={12} md={6}>
              <Form.Item label="命令超时 (秒)" name="sandbox.command_timeout_seconds">
                <InputNumber min={1} max={600} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col xs={12} md={6}>
              <Form.Item label="命令输出上限 (字节)" name="sandbox.output_limit_bytes">
                <InputNumber min={1024} max={1048576} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
          </Row>
        </Card>

        <Card type="inner" title="运行参数" style={{ marginBottom: 16 }}>
          <Row gutter={16}>
            <Col xs={12} md={6}>
              <Form.Item label="并发项目数" name="runtime.max_concurrent_projects">
                <InputNumber min={1} max={10} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col xs={12} md={6}>
              <Form.Item label="单阶段超时 (分钟)" name="runtime.stage_timeout_minutes">
                <InputNumber min={1} max={120} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col xs={12} md={6}>
              <Form.Item label="资源采样间隔 (秒)" name="runtime.resource_sample_seconds">
                <InputNumber min={1} max={60} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col xs={12} md={6}>
              <Form.Item label="数据保留天数" name="runtime.retention_days">
                <InputNumber min={1} max={3650} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
          </Row>
        </Card>

        <Card type="inner" title="执行限制" style={{ marginBottom: 16 }}>
          <Row gutter={16}>
            <Col xs={24} md={10}>
              <Form.Item
                label="命令白名单"
                name="sandbox.command_allowlist"
                extra="逗号分隔，仅允许白名单内的可执行文件"
              >
                <Input placeholder="python, python3" />
              </Form.Item>
            </Col>
            <Col xs={24} md={10}>
              <Form.Item label="目录遍历最大文件数" name="exec.max_files">
                <InputNumber min={1} max={100000} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
          </Row>
        </Card>

        <Card type="inner" title="LLM（OpenAI 兼容接口）">
          <Typography.Paragraph type="secondary">
            三项（base_url、model、api_key）任一为空时，本轮任务使用规则引擎降级模式。
          </Typography.Paragraph>
          <Row gutter={16}>
            <Col xs={24} md={12}>
              <Form.Item label="接口地址" name="llm.base_url">
                <Input placeholder="https://api.example.com/v1" />
              </Form.Item>
            </Col>
            <Col xs={24} md={12}>
              <Form.Item label="模型名称" name="llm.model">
                <Input placeholder="例如：gpt-4o-mini" />
              </Form.Item>
            </Col>
            <Col xs={24} md={12}>
              <Form.Item
                label="API Key"
                name="llm.api_key"
                extra={
                  maskedKey
                    ? `当前已配置：${maskedKey}；留空表示不修改`
                    : '尚未配置'
                }
              >
                <Input.Password
                  placeholder="留空表示不修改"
                  autoComplete="new-password"
                />
              </Form.Item>
              {maskedKey && (
                <Form.Item style={{ marginTop: -8 }}>
                  <Checkbox
                    checked={clearApiKey}
                    onChange={(event) => {
                      setClearApiKey(event.target.checked)
                      if (event.target.checked) {
                        form.setFieldValue('llm.api_key', '')
                      }
                    }}
                  >
                    清空已配置的 API Key（保存后切回规则引擎模式）
                  </Checkbox>
                </Form.Item>
              )}
            </Col>
            <Col xs={12} md={6}>
              <Form.Item label="调用超时 (秒)" name="llm.timeout_seconds">
                <InputNumber min={1} max={600} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col xs={12} md={6}>
              <Form.Item label="最大重试次数" name="llm.max_retries">
                <InputNumber min={0} max={10} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col xs={12} md={6}>
              <Form.Item label="温度" name="llm.temperature">
                <InputNumber min={0} max={2} step={0.1} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col xs={12} md={6}>
              <Form.Item label="最大输出 token" name="llm.max_tokens">
                <InputNumber min={1} max={32768} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
          </Row>
        </Card>

        <Card type="inner" title="编排模式（Agent）">
          <Typography.Paragraph type="secondary">
            one_shot 保持现有行为：一次性把源码交给模型分析。react 允许模型通过工具
            搜索、读取源码后自行决定下一步；超出轮次或 token 预算时自动回退到一次性分析。
          </Typography.Paragraph>
          <Row gutter={16}>
            <Col xs={24} md={8}>
              <Form.Item label="编排引擎" name="orchestration.engine">
                <Select
                  options={[
                    { value: 'fixed', label: 'fixed（默认）' },
                    { value: 'langgraph', label: 'langgraph' },
                  ]}
                />
              </Form.Item>
            </Col>
            <Col xs={12} md={5}>
              <Form.Item
                label="验证重规划轮次"
                name="orchestration.verify_max_retries"
              >
                <InputNumber min={0} max={3} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={16}>
            <Col xs={24} md={8}>
              <Form.Item label="代码分析模式" name="orchestration.analysis_mode">
                <Select
                  options={[
                    { value: 'one_shot', label: 'one_shot（默认）' },
                    { value: 'react', label: 'react（模型选工具）' },
                  ]}
                />
              </Form.Item>
            </Col>
            <Col xs={12} md={5}>
              <Form.Item label="最大工具轮次" name="orchestration.react_max_steps">
                <InputNumber min={1} max={12} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col xs={12} md={6}>
              <Form.Item label="Token 预算" name="orchestration.react_max_tokens">
                <InputNumber min={1000} max={60000} step={1000} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col xs={24} md={5}>
              <Form.Item
                label="单次输出截断 (字符)"
                name="orchestration.react_tool_output_chars"
              >
                <InputNumber min={500} max={20000} step={500} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
          </Row>
        </Card>
      </Form>
    </Card>
  )
}
