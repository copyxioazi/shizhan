import { ArrowLeftOutlined } from '@ant-design/icons'
import {
  Alert,
  Button,
  Card,
  Form,
  Input,
  Select,
  Space,
  message,
} from 'antd'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { projectsApi, type ProjectCreateBody } from '../api'

export function ProjectCreatePage() {
  const navigate = useNavigate()
  const [form] = Form.useForm<ProjectCreateBody>()
  const [loading, setLoading] = useState(false)

  const onFinish = async (values: ProjectCreateBody) => {
    setLoading(true)
    try {
      const project = await projectsApi.create({
        ...values,
        source_type: 'local_path',
      })
      message.success('项目创建成功')
      navigate(`/projects/${project.id}`, { replace: true })
    } catch (error) {
      message.error((error as Error).message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <Card
      className="page-card"
      title="新建评估项目"
      extra={
        <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/projects')}>
          返回列表
        </Button>
      }
    >
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 20 }}
        message="源码目录将同步到 Linux VM 的沙箱中，原目录全程只读，不会被修改。"
      />
      <Form<ProjectCreateBody>
        form={form}
        layout="vertical"
        initialValues={{
          source_type: 'local_path',
        }}
        onFinish={onFinish}
        style={{ maxWidth: 760 }}
      >
        <Form.Item
          label="项目名称"
          name="project_name"
          rules={[
            { required: true, message: '请输入项目名称' },
            { max: 128, message: '项目名称不超过 128 个字符' },
          ]}
        >
          <Input placeholder="例如：vuln-demo 安全评估" />
        </Form.Item>

        <Form.Item label="源码类型" name="source_type">
          <Select
            options={[
              { value: 'local_path', label: '本机目录' },
              { value: 'git_repo', label: 'Git 仓库（P2，暂不支持）', disabled: true },
            ]}
          />
        </Form.Item>

        <Form.Item
          label="源码路径"
          name="source_path"
          rules={[{ required: true, message: '请输入源码绝对路径' }]}
          extra="必须是本机已存在且可读的目录绝对路径"
        >
          <Input placeholder="D:\\pythoncode\\auto\\examples\\vuln-demo" />
        </Form.Item>

        <Form.Item
          label="任务说明"
          name="task_content"
          rules={[
            { required: true, message: '请输入任务说明' },
            { max: 5000, message: '任务说明不超过 5000 个字符' },
          ]}
        >
          <Input.TextArea
            rows={4}
            showCount
            maxLength={5000}
            placeholder="例如：重点检查 SQL 注入、命令注入、文件操作与越权。"
          />
        </Form.Item>

        <Form.Item
          label="隔离环境类型"
          name="isolation_type"
          extra="留空时使用系统配置 isolation.default_type"
        >
          <Select
            allowClear
            placeholder="使用系统默认"
            options={[
              { value: 'docker', label: 'Docker 容器（Linux VM，强隔离）' },
              { value: 'local', label: '本机目录（P2 调试模式）', disabled: true },
            ]}
          />
        </Form.Item>

        <Form.Item>
          <Space>
            <Button type="primary" htmlType="submit" loading={loading}>
              创建项目
            </Button>
            <Button onClick={() => navigate('/projects')}>取消</Button>
          </Space>
        </Form.Item>
      </Form>
    </Card>
  )
}
