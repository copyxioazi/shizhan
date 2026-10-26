import {
  ArrowLeftOutlined,
  DownloadOutlined,
  ReloadOutlined,
} from '@ant-design/icons'
import { Alert, Button, Card, Result, Space, Spin, Typography, message } from 'antd'
import { useCallback, useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { resultsApi } from '../api'
import type { ReportData } from '../types'

export function ReportPage() {
  const { id: idText } = useParams()
  const id = Number(idText)
  const navigate = useNavigate()
  const [report, setReport] = useState<ReportData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [downloading, setDownloading] = useState(false)

  const load = useCallback(async () => {
    if (!Number.isFinite(id)) return
    setLoading(true)
    try {
      const data = await resultsApi.report(id)
      setReport(data)
      setError(null)
    } catch (err) {
      setReport(null)
      setError((err as Error).message)
    } finally {
      setLoading(false)
    }
  }, [id])

  useEffect(() => {
    void load()
  }, [load])

  const handleDownload = async () => {
    setDownloading(true)
    try {
      await resultsApi.downloadReport(id, report?.run_no)
      message.success('报告已开始下载')
    } catch (err) {
      message.error((err as Error).message)
    } finally {
      setDownloading(false)
    }
  }

  if (loading) {
    return (
      <div style={{ textAlign: 'center', padding: 80 }}>
        <Spin size="large" />
      </div>
    )
  }

  if (!report) {
    return (
      <Card>
        <Result
          status="info"
          title="报告尚未就绪"
          subTitle={error || '任务尚未完成报告生成，请稍后再试'}
          extra={
            <Space>
              <Button icon={<ReloadOutlined />} onClick={() => void load()}>
                刷新
              </Button>
              <Button type="primary" onClick={() => navigate(`/projects/${id}`)}>
                返回项目详情
              </Button>
            </Space>
          }
        />
      </Card>
    )
  }

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Card
        title={
          <Space>
            <Typography.Title level={4} style={{ margin: 0 }}>
              评估报告
            </Typography.Title>
            <Typography.Text type="secondary">
              第 {report.run_no} 轮 · {report.created_at}
            </Typography.Text>
          </Space>
        }
        extra={
          <Space>
            <Button icon={<ReloadOutlined />} onClick={() => void load()}>
              刷新
            </Button>
            <Button
              type="primary"
              icon={<DownloadOutlined />}
              loading={downloading}
              onClick={() => void handleDownload()}
            >
              下载 HTML
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
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
          message="报告在 sandbox iframe 中渲染，禁止执行脚本与加载外部资源。"
        />
        <iframe
          className="report-frame"
          title="安全评估报告"
          sandbox=""
          srcDoc={report.report_html}
        />
      </Card>
    </Space>
  )
}
