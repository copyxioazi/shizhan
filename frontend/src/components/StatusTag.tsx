import { Tag } from 'antd'

type TagKind =
  | 'project'
  | 'stage'
  | 'worker'
  | 'verify'
  | 'risk'
  | 'report'
  | 'env'

const MAPS: Record<TagKind, Record<string, { label: string; color: string }>> = {
  project: {
    created: { label: '待启动', color: 'default' },
    running: { label: '运行中', color: 'processing' },
    completed: { label: '已完成', color: 'success' },
    failed: { label: '失败', color: 'error' },
    stopped: { label: '已停止', color: 'warning' },
  },
  stage: {
    pending: { label: '等待中', color: 'default' },
    running: { label: '执行中', color: 'processing' },
    success: { label: '成功', color: 'success' },
    failed: { label: '失败', color: 'error' },
    cancelled: { label: '已取消', color: 'warning' },
  },
  worker: {
    idle: { label: '空闲', color: 'default' },
    running: { label: '执行中', color: 'processing' },
    success: { label: '成功', color: 'success' },
    failed: { label: '失败', color: 'error' },
    cancelled: { label: '已取消', color: 'warning' },
  },
  verify: {
    pending: { label: '待验证', color: 'default' },
    verified: { label: '已验证', color: 'success' },
    failed: { label: '验证失败', color: 'error' },
    skipped: { label: '已跳过', color: 'warning' },
  },
  risk: {
    critical: { label: '严重', color: 'red' },
    high: { label: '高危', color: 'volcano' },
    medium: { label: '中危', color: 'orange' },
    low: { label: '低危', color: 'gold' },
    info: { label: '提示', color: 'blue' },
  },
  report: {
    none: { label: '暂无报告', color: 'default' },
    generating: { label: '生成中', color: 'processing' },
    ready: { label: '已就绪', color: 'success' },
    failed: { label: '生成失败', color: 'error' },
  },
  env: {
    pending: { label: '待创建', color: 'default' },
    creating: { label: '创建中', color: 'processing' },
    ready: { label: '已就绪', color: 'cyan' },
    running: { label: '运行中', color: 'processing' },
    stopped: { label: '已停止', color: 'default' },
    destroyed: { label: '已销毁', color: 'default' },
    failed: { label: '失败', color: 'error' },
  },
}

export function StatusTag({
  status,
  kind,
}: {
  status?: string | null
  kind: TagKind
}) {
  if (!status) return <Tag>未知</Tag>
  const item = MAPS[kind][status]
  if (!item) return <Tag>{status}</Tag>
  return <Tag color={item.color}>{item.label}</Tag>
}

export const RISK_LABELS: Record<string, string> = {
  critical: '严重',
  high: '高危',
  medium: '中危',
  low: '低危',
  info: '提示',
}

export const STAGE_LABELS: Record<string, string> = {
  environment_scan: '环境检查',
  code_analysis: '代码分析',
  vulnerability_verify: '漏洞验证',
  report_generate: '报告生成',
}

export const ROLE_LABELS: Record<string, string> = {
  general: '通用处理',
  env_checker: '环境检查',
  code_analyst: '代码分析',
  vuln_verifier: '漏洞验证',
  report_writer: '报告整理',
  ops_assistant: '运维辅助',
  system: '系统',
}
