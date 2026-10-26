import axios, { type AxiosRequestConfig } from 'axios'

export const TOKEN_KEY = 'ase.token'
export const USER_KEY = 'ase.user'

interface ApiEnvelope<T> {
  code: number
  message: string
  data: T
}

export const http = axios.create({
  baseURL: '/api',
  timeout: 30000,
})

http.interceptors.request.use((config) => {
  const token = localStorage.getItem(TOKEN_KEY)
  if (token) {
    config.headers = config.headers ?? {}
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

http.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error?.response?.status === 401) {
      localStorage.removeItem(TOKEN_KEY)
      localStorage.removeItem(USER_KEY)
      if (!window.location.pathname.startsWith('/login')) {
        window.location.href = '/login'
      }
    }
    const message =
      error?.response?.data?.message || error?.message || '请求失败，请稍后重试'
    return Promise.reject(new Error(message))
  },
)

async function unwrap<T>(
  promise: Promise<{ data: ApiEnvelope<T> }>,
): Promise<T> {
  const response = await promise
  const payload = response.data
  if (payload.code !== 0) {
    throw new Error(payload.message || '请求失败')
  }
  return payload.data
}

export function apiGet<T>(url: string, config?: AxiosRequestConfig): Promise<T> {
  return unwrap<T>(http.get<ApiEnvelope<T>>(url, config))
}

export function apiPost<T>(
  url: string,
  body?: unknown,
  config?: AxiosRequestConfig,
): Promise<T> {
  return unwrap<T>(http.post<ApiEnvelope<T>>(url, body, config))
}

export function apiPut<T>(url: string, body?: unknown): Promise<T> {
  return unwrap<T>(http.put<ApiEnvelope<T>>(url, body))
}

export function apiDelete<T>(url: string, config?: AxiosRequestConfig): Promise<T> {
  return unwrap<T>(http.delete<ApiEnvelope<T>>(url, config))
}
