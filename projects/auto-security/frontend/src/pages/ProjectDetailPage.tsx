import {
  ApartmentOutlined,
  ArrowLeftOutlined,
  BugOutlined,
  DashboardOutlined,
  DeleteOutlined,
  FileTextOutlined,
  PauseCircleOutlined,
  PlayCircleOutlined,
  ReloadOutlined,
} from '@ant-design/icons'
import {
  Alert,
  Button,
  Card,
  Col,
  Descriptions,
  Input,
  Modal,
  Result,
  Row,
  Space,
  Spin,
  Statistic,
  Timeline,
  Typography,
  message,
} from 'antd'
import { useCallback, useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { projectsApi } from '../api'
import { STAGE_LABELS, StatusTag } from '../components/StatusTag'
import { useProjectStream } from '../hooks/useProjectStream'
import type { ProjectDetail, StageItem } from '../types'

const STAGE_COLORS: Record<string, string> = {
  pending: 'gray',
  running: 'blue',
  success: 'green',
  failed: 'red',
  cancelled: 'orange',
}

export function ProjectDetailPage() {
  const { id: idText } = useParams()
  const id = Number(idText)
  const navigate = useNavigate()
  const [detail, setDetail] = useState<ProjectDetail | null>(null)
  const [stages, setStages] = useState<StageItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [deleteOpen, setDeleteOpen] = useState(false)
  const [deleteName, setDeleteName] = useState('')

  const load = useCallback(async () => {
    if (!Number.isFinite(id)) return
    try {
      const [project, stageList] = await Promise.all([
        projectsApi.detail(id),
        projectsApi.stages(id),
      ])
      setDetail(project)
      setStages(stageList)
      setError(null)
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setLoading(false)
    }
  }, [id])

  useEffect(() => {
    void load()
  }, [load])

  const connection = useProjectStream(
    Number.isFinite(id) ? id : undefined,
    (msg) => {
      if (msg.type === 'project_status' || msg.type === 'stage_status') {
        void load()
      }
    },
  )

  useEffect(() => {
    if (connection === 'connected') return
    const timer = window.setInterval(() => void load(), 5000)
    return () => window.clearInterval(timer)
  }, [connection, load])

  const handleStart = async () => {
    try {
      const result = await projectsApi.start(id)
      message.success(`任务已启动，第 ${result.run_no} 轮`)
      void load()
    } catch (err) {
      message.error((err as Error).message)
    }
  }

  const handleStop = async () => {
    try {
      await projectsApi.stop(id)
      message.success('停止信号已发送')
      void load()
    } catch (err) {
      message.error((err as Error).message)
    }
  }

  const handleDelete = async () => {
    if (!detail || deleteName.trim() !== detail.project_name) {
      message.error('请输入完整的项目名称以确认删除')
      return
    }
    try {
      const result = await projectsApi.remove(id)
      if (result.warnings?.length) {
        message.warning(result.warnings.join('；'))
      } else {
        message.success('项目已删除')
      }
      navigate('/projects', { replace: true })
    } catch (err) {
      message.error((err as Error).message)
    }
  }

  if (loading && !detail) {
    return (
      <div style={{ textAlign: 'center', padding: 80 }}>
        <Spin size="large" />
      </div>
    )
  }

  if (error || !detail) {
    return (
      <Result
        status="404"
        title="项目不可用"
        subTitle={error || '项目不存在或无权限访问'}
        extra={
          <Button type="primary" onClick={() => navigate('/projects')}>
            返回项目列表
          </Button>
        }
      />
    )
  }

  const canStart = ['created', 'stopped', 'failed'].includes(detail.project_status)
  const canStop = detail.project_status === 'running'

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Card
        title={
          <Space>
            <Typography.Title level={4} style={{ margin: 0 }}>
              {detail.project_name}
            </Typography.Title>
            <StatusTag status={detail.project_status} kind="project" />
            {detail.current_run_no ? (
              <Typography.Text type="secondary">
                第 {detail.current_run_no} 轮
              </Typography.Text>
            ) : null}
          </Space>
        }
        extra={
          <Space>
            <Button icon={<ReloadOutlined />} onClick={() => void load()}>
              刷新
            </Button>
            {canStart && (
              <Button
                type="primary"
                icon={<PlayCircleOutlined />}
                onClick={() => void handleStart()}
              >
                启动任务
              </Button>
            )}
            {canStop && (
              <Button icon={<PauseCircleOutlined />} onClick={() => void handleStop()}>
                停止任务
              </Button>
            )}
            {detail.project_status !== 'running' && (
              <Button
                danger
                icon={<DeleteOutlined />}
                onClick={() => {
                  setDeleteName('')
                  setDeleteOpen(true)
                }}
              >
                删除
              </Button>
            )}
            <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/projects')}>
              返回
            </Button>
          </Space>
        }
      >
        <Descriptions
          bordered
          size="small"
          column={{ xs: 1, md: 2 }}
          items={[
            { key: 'source', label: '源码来源', children: detail.source_path },
            { key: 'task', label: '任务说明', children: detail.task_content },
            {
              key: 'isolation',
              label: '隔离环境',
              children: detail.isolation ? (
                <Space>
                  <StatusTag status={detail.isolation.env_status} kind="env" />
                  <Typography.Text code>
                    {detail.isolation.env_ref || '尚未创建容器'}
                  </Typography.Text>
                  <Typography.Text type="secondary">
                    {detail.isolation.env_type === 'docker'
                      ? '强隔离 · Docker'
                      : '本机目录'}
                  </Typography.Text>
                </Space>
              ) : (
                '未绑定'
              ),
            },
            {
              key: 'report',
              label: '报告状态',
              children: <StatusTag status={detail.report_status} kind="report" />,
            },
            { key: 'created', label: '创建时间', children: detail.created_at },
            { key: 'updated', label: '最近更新', children: detail.updated_at },
          ]}
        />
        <Row gutter={16} style={{ marginTop: 16 }}>
          <Col xs={12} md={6}>
            <Card size="small">
              <Statistic title="漏洞数量" value={detail.counts.vulnerability_count} />
            </Card>
          </Col>
          <Col xs={12} md={6}>
            <Card size="small">
              <Statistic
                title="已验证漏洞"
                value={detail.counts.verified_vulnerability_count}
                valueStyle={{ color: '#389e0d' }}
              />
            </Card>
          </Col>
          <Col xs={12} md={6}>
            <Card size="small">
              <Statistic title="攻击路径" value={detail.counts.attack_path_count} />
            </Card>
          </Col>
          <Col xs={12} md={6}>
            <Card size="small">
              <Statistic
                title="WS 连接"
                value={
                  connection === 'connected'
                    ? '已连接'
                    : connection === 'reconnecting'
                      ? '重连中'
                      : '未连接'
                }
                valueStyle={{
                  fontSize: 20,
                  color: connection === 'connected' ? '#389e0d' : '#d46b08',
                }}
              />
            </Card>
          </Col>
        </Row>
        <Space wrap style={{ marginTop: 16 }}>
          <Button
            icon={<DashboardOutlined />}
            onClick={() => navigate(`/projects/${id}/monitor`)}
          >
            实时监控
          </Button>
          <Button
            icon={<BugOutlined />}
            onClick={() => navigate(`/projects/${id}/vulnerabilities`)}
          >
            漏洞列表
          </Button>
          <Button
            icon={<ApartmentOutlined />}
            onClick={() => navigate(`/projects/${id}/attack-paths`)}
          >
            攻击路径
          </Button>
          <Button
            icon={<FileTextOutlined />}
            onClick={() => navigate(`/projects/${id}/report`)}
          >
            评估报告
          </Button>
        </Space>
      </Card>

      <Card title="执行阶段">
        {stages.length === 0 ? (
          <Alert
            type="info"
            showIcon
            message="尚未启动任务，暂无阶段记录"
          />
        ) : (
          <Timeline
            items={stages.map((stage) => ({
              color: STAGE_COLORS[stage.stage_status] || 'gray',
              children: (
                <Space direction="vertical" size={2}>
                  <Space>
                    <Typography.Text strong>
                      {STAGE_LABELS[stage.stage_name] || stage.stage_name}
                    </Typography.Text>
                    <StatusTag status={stage.stage_status} kind="stage" />
                  </Space>
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    {stage.started_at || '-'} → {stage.finished_at || '-'}
                  </Typography.Text>
                  {stage.error_message ? (
                    <Typography.Text type="danger" style={{ fontSize: 12 }}>
                      {stage.error_message}
                    </Typography.Text>
                  ) : null}
                </Space>
              ),
            }))}
          />
        )}
      </Card>

      <Modal
        title="删除项目"
        open={deleteOpen}
        onCancel={() => setDeleteOpen(false)}
        onOk={() => void handleDelete()}
        okText="确认删除"
        okButtonProps={{ danger: true }}
        cancelText="取消"
      >
        <Typography.Paragraph>
          删除后项目及其漏洞、攻击路径、日志、报告与沙箱环境将永久清除，无法恢复。
        </Typography.Paragraph>
        <Typography.Paragraph>
          请输入项目名称 <Typography.Text strong>{detail.project_name}</Typography.Text> 以确认：
        </Typography.Paragraph>
        <Input
          value={deleteName}
          onChange={(event) => setDeleteName(event.target.value)}
          placeholder={detail.project_name}
        />
      </Modal>
    </Space>
  )
}
