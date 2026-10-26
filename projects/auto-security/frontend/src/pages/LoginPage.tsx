import { LockOutlined, SafetyCertificateOutlined, UserOutlined } from '@ant-design/icons'
import {
  Alert,
  Button,
  Card,
  Form,
  Input,
  Space,
  Tabs,
  Typography,
  message,
} from 'antd'
import { useEffect, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { authApi } from '../api'
import { useAuthStore } from '../store/auth'
import type { SystemStatus } from '../types'

interface LoginValues {
  username: string
  password: string
}

interface InitValues extends LoginValues {
  confirm: string
}

export function LoginPage() {
  const navigate = useNavigate()
  const location = useLocation()
  const setAuth = useAuthStore((state) => state.setAuth)
  const token = useAuthStore((state) => state.token)
  const [system, setSystem] = useState<SystemStatus | null>(null)
  const [loading, setLoading] = useState(false)

  const target =
    (location.state as { from?: string } | null)?.from || '/projects'

  useEffect(() => {
    if (token) {
      navigate(target, { replace: true })
      return
    }
    authApi
      .status()
      .then(setSystem)
      .catch(() => setSystem(null))
  }, [navigate, target, token])

  const doLogin = async (values: LoginValues) => {
    const result = await authApi.login(values)
    setAuth(result.token, result.user)
    message.success(`欢迎回来，${result.user.username}`)
    navigate(target, { replace: true })
  }

  const onLogin = async (values: LoginValues) => {
    setLoading(true)
    try {
      await doLogin(values)
    } catch (error) {
      message.error((error as Error).message)
    } finally {
      setLoading(false)
    }
  }

  const onInit = async (values: InitValues) => {
    if (values.password !== values.confirm) {
      message.error('两次输入的密码不一致')
      return
    }
    setLoading(true)
    try {
      await authApi.init({
        username: values.username,
        password: values.password,
      })
      await doLogin({ username: values.username, password: values.password })
    } catch (error) {
      message.error((error as Error).message)
    } finally {
      setLoading(false)
    }
  }

  const loginForm = (
    <Form<LoginValues> layout="vertical" onFinish={onLogin} requiredMark={false}>
      <Form.Item
        label="用户名"
        name="username"
        rules={[{ required: true, message: '请输入用户名' }]}
      >
        <Input prefix={<UserOutlined />} placeholder="admin 或 demo" autoComplete="username" />
      </Form.Item>
      <Form.Item
        label="密码"
        name="password"
        rules={[{ required: true, message: '请输入密码' }]}
      >
        <Input.Password
          prefix={<LockOutlined />}
          placeholder="请输入密码"
          autoComplete="current-password"
        />
      </Form.Item>
      <Button type="primary" htmlType="submit" block loading={loading}>
        登录
      </Button>
      <Typography.Paragraph type="secondary" style={{ marginTop: 16, marginBottom: 0, fontSize: 12 }}>
        演示账号：demo / demo12345
      </Typography.Paragraph>
    </Form>
  )

  const initForm = (
    <Form<InitValues> layout="vertical" onFinish={onInit} requiredMark={false}>
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message="系统尚未初始化"
        description="首次使用请创建管理员账号；初始化完成后该入口将永久关闭。"
      />
      <Form.Item
        label="管理员用户名"
        name="username"
        rules={[
          { required: true, message: '请输入用户名' },
          { min: 3, max: 64, message: '用户名长度为 3–64 个字符' },
          {
            pattern: /^[A-Za-z0-9_-]+$/,
            message: '仅允许字母、数字、下划线与连字符',
          },
        ]}
      >
        <Input prefix={<UserOutlined />} placeholder="admin" />
      </Form.Item>
      <Form.Item
        label="密码"
        name="password"
        rules={[
          { required: true, message: '请输入密码' },
          { min: 8, max: 72, message: '密码长度为 8–72 个字符' },
        ]}
      >
        <Input.Password prefix={<LockOutlined />} placeholder="至少 8 个字符" />
      </Form.Item>
      <Form.Item
        label="确认密码"
        name="confirm"
        rules={[{ required: true, message: '请再次输入密码' }]}
      >
        <Input.Password prefix={<LockOutlined />} placeholder="再次输入密码" />
      </Form.Item>
      <Button type="primary" htmlType="submit" block loading={loading}>
        初始化并登录
      </Button>
    </Form>
  )

  return (
    <div className="login-page">
      <Card className="login-card">
        <Space direction="vertical" size={4} style={{ width: '100%', marginBottom: 20 }}>
          <Typography.Title level={3} style={{ margin: 0 }}>
            <SafetyCertificateOutlined style={{ color: '#1677ff', marginRight: 8 }} />
            自动化安全评估系统
          </Typography.Title>
          <Typography.Text type="secondary">
            源码接入 · 沙箱分析 · 漏洞验证 · 报告输出
          </Typography.Text>
        </Space>

        {system === null ? (
          loginForm
        ) : system.initialized ? (
          loginForm
        ) : (
          <Tabs
            items={[
              { key: 'init', label: '系统初始化', children: initForm },
              { key: 'login', label: '登录', children: loginForm },
            ]}
          />
        )}
      </Card>
    </div>
  )
}
