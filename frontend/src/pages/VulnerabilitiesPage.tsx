import { ArrowLeftOutlined, ReloadOutlined } from '@ant-design/icons'
import {
  Button,
  Card,
  Descriptions,
  Drawer,
  Input,
  Select,
  Space,
  Spin,
  Table,
  Typography,
  message,
  type TableProps,
} from 'antd'
import { useCallback, useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { resultsApi } from '../api'
import { RISK_LABELS, StatusTag } from '../components/StatusTag'
import type { VulnerabilityDetail, VulnerabilityListItem } from '../types'

export function VulnerabilitiesPage() {
  const { id: idText } = useParams()
  const id = Number(idText)
  const navigate = useNavigate()
  const [data, setData] = useState<VulnerabilityListItem[]>([])
  const [loading, setLoading] = useState(false)
  const [riskLevel, setRiskLevel] = useState<string | undefined>()
  const [verifyStatus, setVerifyStatus] = useState<string | undefined>()
  const [keyword, setKeyword] = useState('')
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [detail, setDetail] = useState<VulnerabilityDetail | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)

  const load = useCallback(async () => {
    if (!Number.isFinite(id)) return
    setLoading(true)
    try {
      const list = await resultsApi.vulnerabilities(id, {
        risk_level: riskLevel || undefined,
        verify_status: verifyStatus || undefined,
        keyword: keyword || undefined,
      })
      setData(list)
    } catch (error) {
      message.error((error as Error).message)
    } finally {
      setLoading(false)
    }
  }, [id, keyword, riskLevel, verifyStatus])

  useEffect(() => {
    void load()
  }, [load])

  const openDetail = async (row: VulnerabilityListItem) => {
    setDrawerOpen(true)
    setDetail(null)
    setDetailLoading(true)
    try {
      const item = await resultsApi.vulnerability(id, row.id)
      setDetail(item)
    } catch (error) {
      message.error((error as Error).message)
    } finally {
      setDetailLoading(false)
    }
  }

  const columns: TableProps<VulnerabilityListItem>['columns'] = [
    { title: '编号', dataIndex: 'vuln_code', width: 110 },
    {
      title: '漏洞标题',
      dataIndex: 'vuln_title',
      render: (value: string, row) => (
        <Typography.Link onClick={() => void openDetail(row)}>{value}</Typography.Link>
      ),
    },
    {
      title: '风险等级',
      dataIndex: 'risk_level',
      width: 110,
      render: (value: string) => <StatusTag status={value} kind="risk" />,
    },
    {
      title: '验证状态',
      dataIndex: 'verify_status',
      width: 120,
      render: (value: string) => <StatusTag status={value} kind="verify" />,
    },
    {
      title: '文件位置',
      dataIndex: 'file_path',
      width: 260,
      render: (value: string) => <Typography.Text code>{value}</Typography.Text>,
    },
  ]

  return (
    <Card
      className="page-card"
      title="漏洞列表"
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
      <Space wrap style={{ marginBottom: 16 }}>
        <Select
          allowClear
          placeholder="风险等级"
          style={{ width: 150 }}
          value={riskLevel}
          onChange={setRiskLevel}
          options={Object.entries(RISK_LABELS).map(([value, label]) => ({
            value,
            label,
          }))}
        />
        <Select
          allowClear
          placeholder="验证状态"
          style={{ width: 150 }}
          value={verifyStatus}
          onChange={setVerifyStatus}
          options={[
            { value: 'pending', label: '待验证' },
            { value: 'verified', label: '已验证' },
            { value: 'failed', label: '验证失败' },
            { value: 'skipped', label: '已跳过' },
          ]}
        />
        <Input.Search
          allowClear
          placeholder="标题或文件路径"
          style={{ width: 240 }}
          value={keyword}
          onChange={(event) => setKeyword(event.target.value)}
          onSearch={() => void load()}
        />
        <Button onClick={() => void load()}>查询</Button>
      </Space>

      <Table<VulnerabilityListItem>
        rowKey="id"
        loading={loading}
        columns={columns}
        dataSource={data}
        pagination={{ pageSize: 10, showSizeChanger: false }}
        locale={{ emptyText: '暂无漏洞' }}
        onRow={(row) => ({ onClick: () => void openDetail(row) })}
        scroll={{ x: 900 }}
      />

      <Drawer
        title={detail ? `${detail.vuln_code} ${detail.vuln_title}` : '漏洞详情'}
        width={700}
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
      >
        {detailLoading ? (
          <div style={{ textAlign: 'center', padding: 48 }}>
            <Spin />
          </div>
        ) : detail ? (
          <Descriptions
            bordered
            column={1}
            size="small"
            items={[
              {
                key: 'risk',
                label: '风险等级',
                children: <StatusTag status={detail.risk_level} kind="risk" />,
              },
              {
                key: 'verify',
                label: '验证状态',
                children: <StatusTag status={detail.verify_status} kind="verify" />,
              },
              { key: 'file', label: '文件位置', children: <Typography.Text code>{detail.file_path}</Typography.Text> },
              { key: 'impact', label: '影响说明', children: detail.impact_text },
              { key: 'condition', label: '触发条件', children: detail.condition_text },
              {
                key: 'evidence',
                label: '证据内容',
                children: (
                  <Typography.Paragraph style={{ whiteSpace: 'pre-wrap', marginBottom: 0 }}>
                    {detail.evidence_text}
                  </Typography.Paragraph>
                ),
              },
              {
                key: 'reproduce',
                label: '复现步骤',
                children: (
                  <Typography.Paragraph style={{ whiteSpace: 'pre-wrap', marginBottom: 0 }}>
                    {detail.reproduce_steps_text || '-'}
                  </Typography.Paragraph>
                ),
              },
              {
                key: 'code',
                label: '验证代码',
                children: (
                  <Typography.Paragraph style={{ whiteSpace: 'pre-wrap', marginBottom: 0 }}>
                    {detail.verify_code_text || '无（静态证据型漏洞）'}
                  </Typography.Paragraph>
                ),
              },
            ]}
          />
        ) : null}
      </Drawer>
    </Card>
  )
}
