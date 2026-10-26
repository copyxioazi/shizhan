import { ArrowLeftOutlined, ReloadOutlined } from '@ant-design/icons'
import {
  Badge,
  Button,
  Card,
  Col,
  Empty,
  List,
  Row,
  Select,
  Space,
  Statistic,
  Switch,
  Tag,
  Typography,
  message,
  notification,
} from 'antd'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { monitorApi, projectsApi } from '../api'
import { ResourceChart } from '../charts/ResourceChart'
import {
  ROLE_LABELS,
  STAGE_LABELS,
  StatusTag,
} from '../components/StatusTag'
import { useProjectStream } from '../hooks/useProjectStream'
import type {
  ChatItem,
  LogItem,
  ProjectDetail,
  ProjectStatus,
  ResourcePoint,
  StageItem,
  StageName,
  StageStatus,
  StreamMessage,
  WorkerTask,
  WorkerRole,
  WorkerStatus,
} from '../types'

const ROLE_ORDER: WorkerRole[] = [
  'env_checker',
  'code_analyst',
  'vuln_verifier',
  'report_writer',
  'ops_assistant',
  'general',
]

function upsertById<T extends { id: number }>(list: T[], item: T, cap = 1000): T[] {
  const index = list.findIndex((entry) => entry.id === item.id)
  if (index >= 0) {
    const copy = [...list]
    copy[index] = { ...copy[index], ...item }
    return copy
  }
  return [...list, item].slice(-cap)
}

function logFromMessage(data: Record<string, unknown>): LogItem {
  return {
    id: Number(data.log_id),
    stage_id: (data.stage_id as number | null) ?? null,
    worker_task_id: (data.worker_task_id as number | null) ?? null,
    log_level: data.log_level as LogItem['log_level'],
    log_content: String(data.log_content ?? ''),
    created_at: String(data.created_at ?? ''),
  }
}

export function MonitorPage() {
  const { id: idText } = useParams()
  const id = Number(idText)
  const navigate = useNavigate()

  const [project, setProject] = useState<ProjectDetail | null>(null)
  const [stages, setStages] = useState<StageItem[]>([])
  const [workers, setWorkers] = useState<WorkerTask[]>([])
  const [logs, setLogs] = useState<LogItem[]>([])
  const [messages, setMessages] = useState<ChatItem[]>([])
  const [resources, setResources] = useState<ResourcePoint[]>([])
  const [level, setLevel] = useState<string | undefined>()
  const [autoScroll, setAutoScroll] = useState(true)
  const [chatAutoScroll, setChatAutoScroll] = useState(true)
  const [chatRole, setChatRole] = useState<WorkerRole | undefined>()
  const logBoxRef = useRef<HTMLDivElement>(null)
  const chatBoxRef = useRef<HTMLDivElement>(null)

  const load = useCallback(async () => {
    if (!Number.isFinite(id)) return
    try {
      const [detail, stageList, workerList, logList, messageList, resourceList] =
        await Promise.all([
          projectsApi.detail(id),
          projectsApi.stages(id),
          projectsApi.workers(id),
          monitorApi.logs(id, { limit: 300 }),
          monitorApi.messages(id, { limit: 100 }),
          monitorApi.resources(id, { limit: 300 }),
        ])
      setProject(detail)
      setStages(stageList)
      setWorkers(workerList)
      setLogs(logList)
      setMessages(messageList)
      setResources(resourceList)
    } catch (error) {
      message.error((error as Error).message)
    }
  }, [id])

  useEffect(() => {
    void load()
  }, [load])

  const refreshWorkers = useCallback(() => {
    if (!Number.isFinite(id)) return
    projectsApi
      .workers(id)
      .then(setWorkers)
      .catch(() => undefined)
  }, [id])

  const connection = useProjectStream(
    Number.isFinite(id) ? id : undefined,
    (msg: StreamMessage) => {
      const data = msg.data
      switch (msg.type) {
        case 'project_status': {
          const status = data.project_status as ProjectStatus
          setProject((prev) =>
            prev ? { ...prev, project_status: status } : prev,
          )
          break
        }
        case 'stage_status': {
          const incoming: StageItem = {
            id: Number(data.stage_id),
            run_no: Number(data.run_no ?? 0),
            stage_name: data.stage_name as StageName,
            stage_status: data.stage_status as StageStatus,
            started_at: null,
            finished_at: null,
            error_message: null,
          }
          setStages((prev) => {
            const index = prev.findIndex((stage) => stage.id === incoming.id)
            if (index >= 0) {
              const copy = [...prev]
              copy[index] = {
                ...copy[index],
                stage_status: incoming.stage_status,
              }
              return copy
            }
            return [...prev, incoming]
          })
          break
        }
        case 'worker_status':
          refreshWorkers()
          break
        case 'runtime_log':
          setLogs((prev) => upsertById(prev, logFromMessage(data)))
          break
        case 'chat_message': {
          const item: ChatItem = {
            id: Number(data.message_id),
            worker_role: data.worker_role as WorkerRole,
            message_type: data.message_type as ChatItem['message_type'],
            message_text: String(data.message_text ?? ''),
            created_at: String(data.created_at ?? ''),
          }
          setMessages((prev) => upsertById(prev, item, 500))
          break
        }
        case 'resource_usage': {
          const point: ResourcePoint = {
            cpu_usage: Number(data.cpu_usage ?? 0),
            memory_usage: Number(data.memory_usage ?? 0),
            token_count: Number(data.token_count ?? 0),
            recorded_at: String(data.recorded_at ?? ''),
          }
          setResources((prev) => [...prev, point].slice(-300))
          break
        }
        case 'vulnerability_found':
          notification.info({
            message: '发现漏洞',
            description: `${data.vuln_code} ${data.vuln_title}（${data.risk_level}）`,
            placement: 'topRight',
          })
          break
        case 'report_ready':
          notification.success({
            message: '报告已生成',
            description: String(data.report_file_path ?? ''),
          })
          void load()
          break
        default:
          break
      }
    },
  )

  useEffect(() => {
    if (!autoScroll || !logBoxRef.current) return
    logBoxRef.current.scrollTop = logBoxRef.current.scrollHeight
  }, [logs, autoScroll])

  useEffect(() => {
    if (!chatAutoScroll || !chatBoxRef.current) return
    chatBoxRef.current.scrollTop = chatBoxRef.current.scrollHeight
  }, [messages, chatAutoScroll])

  const currentStage =
    stages.find((stage) => stage.stage_status === 'running') ||
    stages[stages.length - 1]

  const latestResource = resources[resources.length - 1]

  const latestByRole = useMemo(() => {
    const map = new Map<WorkerRole, WorkerTask>()
    for (const task of workers) {
      const previous = map.get(task.worker_role)
      if (!previous || task.id > previous.id) {
        map.set(task.worker_role, task)
      }
    }
    return map
  }, [workers])

  const filteredLogs = useMemo(
    () => logs.filter((item) => !level || item.log_level === level),
    [logs, level],
  )

  const filteredMessages = useMemo(
    () =>
      messages.filter((item) => !chatRole || item.worker_role === chatRole),
    [messages, chatRole],
  )

  const connectionBadge =
    connection === 'connected'
      ? { status: 'success' as const, text: '已连接' }
      : connection === 'reconnecting'
        ? { status: 'warning' as const, text: '重连中' }
        : connection === 'connecting'
          ? { status: 'processing' as const, text: '连接中' }
          : { status: 'default' as const, text: '已断开' }

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Card
        title={
          <Space wrap>
            <Typography.Title level={4} style={{ margin: 0 }}>
              {project?.project_name || `项目 #${id}`}
            </Typography.Title>
            <StatusTag status={project?.project_status} kind="project" />
            <Badge status={connectionBadge.status} text={connectionBadge.text} />
          </Space>
        }
        extra={
          <Space>
            <Button icon={<ReloadOutlined />} onClick={() => void load()}>
              刷新
            </Button>
            <Button
              icon={<ArrowLeftOutlined />}
              onClick={() => navigate(`/projects/${id}`)}
            >
              返回详情
            </Button>
          </Space>
        }
      >
        <Row gutter={16}>
          <Col xs={24} md={8}>
            <Card size="small">
              <Statistic
                title="当前阶段"
                value={
                  currentStage
                    ? STAGE_LABELS[currentStage.stage_name] ||
                      currentStage.stage_name
                    : '尚未开始'
                }
                suffix={
                  currentStage ? (
                    <StatusTag status={currentStage.stage_status} kind="stage" />
                  ) : null
                }
              />
            </Card>
          </Col>
          <Col xs={12} md={4}>
            <Card size="small">
              <Statistic
                title="CPU"
                value={latestResource?.cpu_usage ?? 0}
                precision={2}
                suffix="%"
              />
            </Card>
          </Col>
          <Col xs={12} md={4}>
            <Card size="small">
              <Statistic
                title="内存"
                value={latestResource?.memory_usage ?? 0}
                precision={2}
                suffix="MB"
              />
            </Card>
          </Col>
          <Col xs={12} md={4}>
            <Card size="small">
              <Statistic
                title="Token"
                value={latestResource?.token_count ?? 0}
              />
            </Card>
          </Col>
          <Col xs={12} md={4}>
            <Card size="small">
              <Statistic title="漏洞数量" value={project?.counts.vulnerability_count ?? 0} />
            </Card>
          </Col>
        </Row>
      </Card>

      <Row gutter={16}>
        <Col xs={24} xl={14}>
          <Card
            title="运行日志"
            extra={
              <Space>
                <Select
                  allowClear
                  placeholder="级别"
                  size="small"
                  style={{ width: 110 }}
                  value={level}
                  onChange={setLevel}
                  options={[
                    { value: 'debug', label: 'debug' },
                    { value: 'info', label: 'info' },
                    { value: 'warn', label: 'warn' },
                    { value: 'error', label: 'error' },
                  ]}
                />
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  自动滚动
                </Typography.Text>
                <Switch
                  size="small"
                  checked={autoScroll}
                  onChange={setAutoScroll}
                />
              </Space>
            }
            className="page-card"
          >
            <div className="scroll-box" ref={logBoxRef}>
              {filteredLogs.length === 0 ? (
                <span>暂无日志</span>
              ) : (
                filteredLogs.map((item) => (
                  <div key={item.id} className={`log-line log-${item.log_level}`}>
                    [{item.created_at}] [{item.log_level.toUpperCase()}] {item.log_content}
                  </div>
                ))
              )}
            </div>
          </Card>

          <Card title="资源消耗" className="page-card">
            {resources.length === 0 ? (
              <Empty description="暂无采样数据" />
            ) : (
              <ResourceChart data={resources} />
            )}
          </Card>
        </Col>

        <Col xs={24} xl={10}>
          <Card
            title="角色执行状态"
            className="page-card"
            extra={
              <Tag color="blue">6 类角色</Tag>
            }
          >
            <List
              size="small"
              dataSource={ROLE_ORDER}
              locale={{ emptyText: '暂无角色任务' }}
              renderItem={(role) => {
                const task = latestByRole.get(role)
                return (
                  <List.Item
                    actions={[
                      <StatusTag
                        key="status"
                        status={task?.task_status || 'idle'}
                        kind="worker"
                      />,
                    ]}
                  >
                    <List.Item.Meta
                      title={ROLE_LABELS[role] || role}
                      description={
                        task
                          ? `任务 #${task.id} · ${task.started_at || '未开始'}`
                          : '等待调度'
                      }
                    />
                  </List.Item>
                )
              }}
            />
          </Card>

          <Card
            title="聊天消息"
            className="page-card"
            extra={
              <Space size={6}>
                <Select
                  allowClear
                  placeholder="角色"
                  size="small"
                  style={{ width: 120 }}
                  value={chatRole}
                  onChange={(value) => setChatRole(value)}
                  options={[...ROLE_ORDER, 'system' as WorkerRole].map(
                    (role) => ({
                      value: role,
                      label: ROLE_LABELS[role] || role,
                    }),
                  )}
                />
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  自动滚动
                </Typography.Text>
                <Switch
                  size="small"
                  checked={chatAutoScroll}
                  onChange={setChatAutoScroll}
                />
              </Space>
            }
          >
            <div className="chat-box" ref={chatBoxRef}>
              {filteredMessages.length === 0 ? (
                <Empty description="暂无消息" />
              ) : (
                <List
                  size="small"
                  dataSource={filteredMessages}
                  renderItem={(item, index) => {
                    const previous = filteredMessages[index - 1]
                    const newGroup =
                      !previous || previous.worker_role !== item.worker_role
                    return (
                      <List.Item style={{ display: 'block' }}>
                        {newGroup && (
                          <div className="chat-role-header">
                            <Tag color="blue">
                              {ROLE_LABELS[item.worker_role] || item.worker_role}
                            </Tag>
                            <Typography.Text
                              type="secondary"
                              style={{ fontSize: 12 }}
                            >
                              {item.created_at}
                            </Typography.Text>
                          </div>
                        )}
                        <List.Item.Meta
                          title={
                            <Space size={6}>
                              <Tag>{item.message_type}</Tag>
                              <Typography.Text
                                type="secondary"
                                style={{ fontSize: 12 }}
                              >
                                {item.created_at}
                              </Typography.Text>
                            </Space>
                          }
                          description={
                            <Typography.Paragraph
                              style={{
                                marginBottom: 0,
                                whiteSpace: 'pre-wrap',
                              }}
                            >
                              {item.message_text}
                            </Typography.Paragraph>
                          }
                        />
                      </List.Item>
                    )
                  }}
                />
              )}
            </div>
          </Card>
        </Col>
      </Row>
    </Space>
  )
}
