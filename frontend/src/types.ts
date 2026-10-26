export type ProjectStatus =
  | 'created'
  | 'running'
  | 'completed'
  | 'failed'
  | 'stopped'

export type StageStatus = 'pending' | 'running' | 'success' | 'failed' | 'cancelled'
export type WorkerStatus = 'idle' | 'running' | 'success' | 'failed' | 'cancelled'
export type VerifyStatus = 'pending' | 'verified' | 'failed' | 'skipped'
export type RiskLevel = 'critical' | 'high' | 'medium' | 'low' | 'info'
export type ReportStatus = 'none' | 'generating' | 'ready' | 'failed'

export type StageName =
  | 'environment_scan'
  | 'code_analysis'
  | 'vulnerability_verify'
  | 'report_generate'

export type WorkerRole =
  | 'general'
  | 'env_checker'
  | 'code_analyst'
  | 'vuln_verifier'
  | 'report_writer'
  | 'ops_assistant'
  | 'system'

export interface User {
  id: number
  username: string
  role: 'admin' | 'user'
  status?: string
  created_at?: string
}

export interface SystemStatus {
  initialized: boolean
  llm_configured: boolean
  isolation_available: { docker: boolean; local: boolean }
}

export interface IsolationSummary {
  env_id?: number
  env_type: string
  env_status: string
  env_ref?: string | null
}

export interface ProjectListItem {
  id: number
  project_name: string
  source_type: string
  source_path: string
  task_content?: string
  project_status: ProjectStatus
  created_by: number
  created_by_username: string
  created_at: string
  last_started_at: string | null
  last_finished_at: string | null
}

export interface ProjectDetail {
  id: number
  project_name: string
  source_type: string
  source_path: string
  task_content: string
  project_status: ProjectStatus
  created_by: number
  created_by_username: string
  created_at: string
  updated_at: string
  current_run_no: number | null
  isolation: IsolationSummary | null
  counts: {
    vulnerability_count: number
    verified_vulnerability_count: number
    attack_path_count: number
  }
  report_status: ReportStatus
}

export interface StageItem {
  id: number
  run_no: number
  stage_name: StageName
  stage_status: StageStatus
  started_at: string | null
  finished_at: string | null
  error_message: string | null
}

export interface WorkerTask {
  id: number
  stage_id: number
  stage_name: StageName
  run_no: number
  worker_role: WorkerRole
  task_status: WorkerStatus
  task_content: string
  result_summary: string | null
  error_message: string | null
  started_at: string | null
  finished_at: string | null
}

export interface VulnerabilityListItem {
  id: number
  vuln_code: string
  vuln_title: string
  risk_level: RiskLevel
  file_path: string
  verify_status: VerifyStatus
  created_at: string
}

export interface VulnerabilityDetail extends VulnerabilityListItem {
  impact_text: string
  condition_text: string
  evidence_text: string
  reproduce_steps_text: string | null
  verify_code_text: string | null
}

export interface AttackPathListItem {
  id: number
  path_code: string
  path_title: string
  path_summary: string
  vuln_count: number
  max_risk_level: RiskLevel | null
  final_impact_text: string
  created_at: string
}

export interface AttackPathItem {
  step_order: number
  step_text: string
  vuln_id: number
  vuln_code: string
  vuln_title: string
  risk_level: RiskLevel
  file_path: string
  verify_status: VerifyStatus
}

export interface AttackPathDetail extends AttackPathListItem {
  run_no: number
  items: AttackPathItem[]
}

export interface ReportData {
  report_id: number
  run_no: number
  report_markdown: string
  report_html: string
  report_file_path: string
  created_at: string
}

export interface LogItem {
  id: number
  stage_id: number | null
  worker_task_id: number | null
  log_level: 'debug' | 'info' | 'warn' | 'error'
  log_content: string
  created_at: string
}

export interface ResourcePoint {
  cpu_usage: number
  memory_usage: number
  token_count: number
  recorded_at: string
}

export interface ChatItem {
  id: number
  worker_role: WorkerRole
  message_type: 'thought' | 'analysis' | 'evidence' | 'conclusion' | 'system'
  message_text: string
  created_at: string
}

export interface SystemLogItem extends LogItem {
  project_id: number | null
}

export interface IsolationEnvItem {
  id: number
  project_id: number
  project_name: string
  env_type: string
  env_ref: string | null
  env_status: string
  last_error: string | null
  updated_at: string
}

export type ConfigMap = Record<string, unknown>

export interface StreamMessage {
  type:
    | 'project_status'
    | 'stage_status'
    | 'worker_status'
    | 'chat_message'
    | 'runtime_log'
    | 'resource_usage'
    | 'vulnerability_found'
    | 'report_ready'
  project_id: number
  timestamp: string
  data: Record<string, unknown>
}
