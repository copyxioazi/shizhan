import { ArrowLeftOutlined, ReloadOutlined } from '@ant-design/icons'
import {
  Button,
  Card,
  Empty,
  Space,
  Table,
  Tag,
  Timeline,
  Typography,
  message,
  type TableProps,
} from 'antd'
import { useCallback, useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { resultsApi } from '../api'
import { StatusTag } from '../components/StatusTag'
import type { AttackPathDetail, AttackPathListItem } from '../types'

export function AttackPathsPage() {
  const { id: idText } = useParams()
  const id = Number(idText)
  const navigate = useNavigate()
  const [data, setData] = useState<AttackPathListItem[]>([])
  const [details, setDetails] = useState<Record<number, AttackPathDetail>>({})
  const [loading, setLoading] = useState(false)

  const load = useCallback(async () => {
    if (!Number.isFinite(id)) return
    setLoading(true)
    try {
      const list = await resultsApi.attackPaths(id)
      setData(list)
      const entries = await Promise.all(
        list.map(async (item) => {
          const detail = await resultsApi.attackPath(id, item.id)
          return [item.id, detail] as const
        }),
      )
      setDetails(Object.fromEntries(entries))
    } catch (error) {
      message.error((error as Error).message)
    } finally {
      setLoading(false)
    }
  }, [id])

  useEffect(() => {
    void load()
  }, [load])

  const columns: TableProps<AttackPathListItem>['columns'] = [
    { title: '路径编号', dataIndex: 'path_code', width: 120 },
    { title: '路径标题', dataIndex: 'path_title' },
    {
      title: '关联漏洞',
      dataIndex: 'vuln_count',
      width: 110,
      render: (value: number) => `${value} 个`,
    },
    {
      title: '最高风险',
      dataIndex: 'max_risk_level',
      width: 110,
      render: (value: string | null) =>
        value ? <StatusTag status={value} kind="risk" /> : '-',
    },
    {
      title: '最终影响',
      dataIndex: 'final_impact_text',
      ellipsis: true,
    },
  ]

  return (
    <Card
      className="page-card"
      title="攻击路径"
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
      <Table<AttackPathListItem>
        rowKey="id"
        loading={loading}
        columns={columns}
        dataSource={data}
        pagination={false}
        locale={{ emptyText: '暂无攻击路径' }}
        expandable={{
          expandedRowRender: (record) => {
            const detail = details[record.id]
            if (!detail) return <Empty description="加载中" />
            return (
              <Space direction="vertical" size={12} style={{ width: '100%' }}>
                <Typography.Paragraph style={{ marginBottom: 0 }}>
                  {detail.path_summary}
                </Typography.Paragraph>
                <Timeline
                  items={detail.items.map((item) => ({
                    color: item.risk_level === 'critical' ? 'red' : 'blue',
                    children: (
                      <Space direction="vertical" size={2}>
                        <Typography.Text>
                          步骤 {item.step_order}：{item.step_text}
                        </Typography.Text>
                        <Space wrap size={6}>
                          <Tag>{item.vuln_code}</Tag>
                          <Typography.Text>{item.vuln_title}</Typography.Text>
                          <StatusTag status={item.risk_level} kind="risk" />
                          <StatusTag status={item.verify_status} kind="verify" />
                          <Typography.Text code>{item.file_path}</Typography.Text>
                        </Space>
                      </Space>
                    ),
                  }))}
                />
                <Typography.Text type="secondary">
                  最终影响：{detail.final_impact_text}
                </Typography.Text>
              </Space>
            )
          },
        }}
      />
    </Card>
  )
}
