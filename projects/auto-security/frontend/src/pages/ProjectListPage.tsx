import {
  DeleteOutlined,
  EyeOutlined,
  PauseCircleOutlined,
  PlayCircleOutlined,
  PlusOutlined,
  ReloadOutlined,
} from '@ant-design/icons'
import {
  Button,
  Card,
  Input,
  Modal,
  Select,
  Space,
  Table,
  Typography,
  message,
  type TableProps,
} from 'antd'
import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { projectsApi, systemApi } from '../api'
import { StatusTag } from '../components/StatusTag'
import { useAuthStore } from '../store/auth'
import type { ProjectListItem, ProjectStatus } from '../types'

const STATUS_OPTIONS: { value: ProjectStatus; label: string }[] = [
  { value: 'created', label: '待启动' },
  { value: 'running', label: '运行中' },
  { value: 'completed', label: '已完成' },
  { value: 'failed', label: '失败' },
  { value: 'stopped', label: '已停止' },
]

export function ProjectListPage() {
  const navigate = useNavigate()
  const user = useAuthStore((state) => state.user)
  const [data, setData] = useState<ProjectListItem[]>([])
  const [loading, setLoading] = useState(false)
  const [status, setStatus] = useState<string | undefined>()
  const [keyword, setKeyword] = useState('')
  const [createdBy, setCreatedBy] = useState<number | undefined>()
  const [creators, setCreators] = useState<
    Array<{ id: number; username: string }>
  >([])

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const list = await projectsApi.list({
        status: status || undefined,
        keyword: keyword || undefined,
        created_by: createdBy,
        limit: 500,
      })
      setData(list)
    } catch (error) {
      message.error((error as Error).message)
    } finally {
      setLoading(false)
    }
  }, [status, keyword, createdBy])

  useEffect(() => {
    void load()
  }, [load])

  useEffect(() => {
    if (user?.role !== 'admin') return
    systemApi
      .users()
      .then((rows) => setCreators(rows.map(({ id, username }) => ({ id, username }))))
      .catch(() => undefined)
  }, [user?.role])

  const handleStart = async (record: ProjectListItem) => {
    try {
      const result = await projectsApi.start(record.id)
      message.success(`任务已启动，第 ${result.run_no} 轮`)
      void load()
    } catch (error) {
      message.error((error as Error).message)
    }
  }

  const handleStop = async (record: ProjectListItem) => {
    try {
      await projectsApi.stop(record.id)
      message.success('停止信号已发送')
      void load()
    } catch (error) {
      message.error((error as Error).message)
    }
  }

  const handleDelete = (record: ProjectListItem) => {
    Modal.confirm({
      title: `删除项目「${record.project_name}」？`,
      content: '项目及其漏洞、攻击路径、日志、报告、沙箱环境将被永久删除，无法恢复。',
      okText: '确认删除',
      okType: 'danger',
      cancelText: '取消',
      onOk: async () => {
        try {
          const result = await projectsApi.remove(record.id)
          if (result.warnings?.length) {
            message.warning(result.warnings.join('；'))
          } else {
            message.success('项目已删除')
          }
          void load()
        } catch (error) {
          message.error((error as Error).message)
        }
      },
    })
  }

  const columns: TableProps<ProjectListItem>['columns'] = [
    {
      title: '项目名称',
      dataIndex: 'project_name',
      render: (value: string, record) => (
        <Typography.Link onClick={() => navigate(`/projects/${record.id}`)}>
          {value}
        </Typography.Link>
      ),
    },
    {
      title: '源码来源',
      dataIndex: 'source_path',
      ellipsis: true,
      render: (value: string) => (
        <Typography.Text className="mono" ellipsis={{ tooltip: value }}>
          {value}
        </Typography.Text>
      ),
    },
    {
      title: '项目状态',
      dataIndex: 'project_status',
      width: 110,
      render: (value: string) => <StatusTag status={value} kind="project" />,
    },
    ...(user?.role === 'admin'
      ? [
          {
            title: '创建人',
            dataIndex: 'created_by_username',
            width: 110,
          },
        ]
      : []),
    {
      title: '最近启动',
      dataIndex: 'last_started_at',
      width: 180,
      render: (value: string | null) => value || '-',
    },
    {
      title: '最近完成',
      dataIndex: 'last_finished_at',
      width: 180,
      render: (value: string | null) => value || '-',
    },
    {
      title: '操作',
      key: 'actions',
      width: 250,
      render: (_, record) => (
        <Space size={4}>
          <Button
            type="link"
            size="small"
            icon={<EyeOutlined />}
            onClick={() => navigate(`/projects/${record.id}`)}
          >
            详情
          </Button>
          {['created', 'stopped', 'failed'].includes(record.project_status) && (
            <Button
              type="link"
              size="small"
              icon={<PlayCircleOutlined />}
              onClick={() => void handleStart(record)}
            >
              启动
            </Button>
          )}
          {record.project_status === 'running' && (
            <Button
              type="link"
              size="small"
              icon={<PauseCircleOutlined />}
              onClick={() => void handleStop(record)}
            >
              停止
            </Button>
          )}
          {record.project_status !== 'running' && (
            <Button
              type="link"
              size="small"
              danger
              icon={<DeleteOutlined />}
              onClick={() => handleDelete(record)}
            >
              删除
            </Button>
          )}
        </Space>
      ),
    },
  ]

  return (
    <Card
      className="page-card"
      title="评估项目"
      extra={
        <Space>
          <Button icon={<ReloadOutlined />} onClick={() => void load()}>
            刷新
          </Button>
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={() => navigate('/projects/new')}
          >
            新建项目
          </Button>
        </Space>
      }
    >
      <Space wrap style={{ marginBottom: 16 }}>
        <Select
          allowClear
          placeholder="项目状态"
          style={{ width: 160 }}
          options={STATUS_OPTIONS}
          value={status}
          onChange={(value) => setStatus(value)}
        />
        {user?.role === 'admin' && (
          <Select
            allowClear
            placeholder="创建人"
            style={{ width: 160 }}
            value={createdBy}
            onChange={(value) => setCreatedBy(value)}
            options={creators.map((creator) => ({
              value: creator.id,
              label: creator.username,
            }))}
          />
        )}
        <Input.Search
          allowClear
          placeholder="按项目名称搜索"
          style={{ width: 260 }}
          value={keyword}
          onChange={(event) => setKeyword(event.target.value)}
          onSearch={() => void load()}
        />
        <Button onClick={() => void load()}>查询</Button>
      </Space>

      <Table<ProjectListItem>
        rowKey="id"
        loading={loading}
        columns={columns}
        dataSource={data}
        pagination={{ pageSize: 10, showSizeChanger: false }}
        locale={{ emptyText: '暂无项目，点击“新建项目”开始评估' }}
        scroll={{ x: 1200 }}
      />
    </Card>
  )
}
