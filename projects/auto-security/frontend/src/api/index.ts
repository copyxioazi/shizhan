import type {
  AttackPathDetail,
  AttackPathListItem,
  ChatItem,
  ConfigMap,
  IsolationEnvItem,
  LogItem,
  ProjectDetail,
  ProjectListItem,
  ReportData,
  ResourcePoint,
  StageItem,
  SystemLogItem,
  SystemStatus,
  User,
  VulnerabilityDetail,
  VulnerabilityListItem,
  WorkerTask,
} from '../types'
import { apiDelete, apiGet, apiPost, apiPut, http } from './client'

export const authApi = {
  status: () => apiGet<SystemStatus>('/system/status'),
  init: (body: { username: string; password: string }) =>
    apiPost<User>('/system/init', body),
  login: (body: { username: string; password: string }) =>
    apiPost<{
      token: string
      token_type: string
      expires_in: number
      user: User
    }>('/system/login', body),
  me: () => apiGet<User>('/system/me'),
}

export interface ProjectCreateBody {
  project_name: string
  source_type: 'local_path'
  source_path: string
  task_content: string
  isolation_type?: 'docker'
}

export const projectsApi = {
  list: (params?: Record<string, string | number | undefined>) =>
    apiGet<ProjectListItem[]>('/projects', { params }),
  create: (body: ProjectCreateBody) =>
    apiPost<{ id: number }>('/projects', body),
  detail: (id: number) => apiGet<ProjectDetail>(`/projects/${id}`),
  start: (id: number) =>
    apiPost<{ project_id: number; run_no: number; project_status: string }>(
      `/projects/${id}/start`,
    ),
  stop: (id: number) =>
    apiPost<{ project_id: number; project_status: string }>(
      `/projects/${id}/stop`,
    ),
  remove: (id: number) =>
    apiDelete<{ deleted: boolean; warnings: string[] }>(
      `/projects/${id}`,
      { params: { confirm: true } },
    ),
  stages: (id: number, runNo?: number) =>
    apiGet<StageItem[]>(`/projects/${id}/stages`, {
      params: runNo === undefined ? undefined : { run_no: runNo },
    }),
  workers: (id: number, params?: Record<string, number | string | undefined>) =>
    apiGet<WorkerTask[]>(`/projects/${id}/workers`, { params }),
}

export const resultsApi = {
  vulnerabilities: (
    id: number,
    params?: Record<string, string | number | undefined>,
  ) =>
    apiGet<VulnerabilityListItem[]>(`/projects/${id}/vulnerabilities`, {
      params,
    }),
  vulnerability: (id: number, vulnId: number) =>
    apiGet<VulnerabilityDetail>(`/projects/${id}/vulnerabilities/${vulnId}`),
  attackPaths: (id: number, runNo?: number) =>
    apiGet<AttackPathListItem[]>(`/projects/${id}/attack-paths`, {
      params: runNo === undefined ? undefined : { run_no: runNo },
    }),
  attackPath: (id: number, pathId: number) =>
    apiGet<AttackPathDetail>(`/projects/${id}/attack-paths/${pathId}`),
  report: (id: number, runNo?: number) =>
    apiGet<ReportData>(`/projects/${id}/report`, {
      params: runNo === undefined ? undefined : { run_no: runNo },
    }),
  downloadReport: async (id: number, runNo?: number) => {
    const response = await http.get<Blob>(
      `/projects/${id}/report/download`,
      {
        params: runNo === undefined ? undefined : { run_no: runNo },
        responseType: 'blob',
      },
    )
    const url = URL.createObjectURL(response.data)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = `report_${id}_${runNo ?? ''}.html`
    document.body.appendChild(anchor)
    anchor.click()
    anchor.remove()
    URL.revokeObjectURL(url)
  },
}

export const monitorApi = {
  logs: (
    id: number,
    params?: Record<string, string | number | undefined>,
  ) => apiGet<LogItem[]>(`/projects/${id}/logs`, { params }),
  resources: (id: number, params?: Record<string, number | undefined>) =>
    apiGet<ResourcePoint[]>(`/projects/${id}/resources`, { params }),
  messages: (id: number, params?: Record<string, number | undefined>) =>
    apiGet<ChatItem[]>(`/projects/${id}/messages`, { params }),
}

export const systemApi = {
  users: () =>
    apiGet<Array<{ id: number; username: string; role: 'admin' | 'user' }>>(
      '/system/users',
    ),
  config: () => apiGet<ConfigMap>('/system/config'),
  updateConfig: (body: ConfigMap) =>
    apiPut<ConfigMap>('/system/config', body),
  logs: (params?: Record<string, string | number | undefined>) =>
    apiGet<SystemLogItem[]>('/system/logs', { params }),
  isolationEnvs: (params?: Record<string, string | number | undefined>) =>
    apiGet<IsolationEnvItem[]>('/system/isolation-envs', { params }),
  cleanupEnv: (envId: number) =>
    apiPost<{ env_id: number; env_status: string }>(
      `/system/isolation-envs/${envId}/cleanup`,
    ),
}
