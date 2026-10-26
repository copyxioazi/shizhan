import { useEffect, useRef, useState } from 'react'
import { TOKEN_KEY } from '../api/client'
import type { StreamMessage } from '../types'

export type ConnectionStatus = 'connecting' | 'connected' | 'reconnecting' | 'disconnected'

const RECONNECT_DELAYS = [1000, 2000, 4000, 8000, 16000]

export function useProjectStream(
  projectId: number | undefined,
  onMessage: (message: StreamMessage) => void,
): ConnectionStatus {
  const [status, setStatus] = useState<ConnectionStatus>('connecting')
  const handlerRef = useRef(onMessage)
  handlerRef.current = onMessage

  useEffect(() => {
    if (!projectId) {
      setStatus('disconnected')
      return
    }
    const token = localStorage.getItem(TOKEN_KEY)
    if (!token) {
      setStatus('disconnected')
      return
    }

    let closed = false
    let attempt = 0
    let socket: WebSocket | null = null
    let reconnectTimer: number | undefined
    let pingTimer: number | undefined

    const clearTimers = () => {
      if (reconnectTimer) window.clearTimeout(reconnectTimer)
      if (pingTimer) window.clearInterval(pingTimer)
      reconnectTimer = undefined
      pingTimer = undefined
    }

    const connect = () => {
      if (closed) return
      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
      const url = `${protocol}//${window.location.host}/api/projects/${projectId}/stream?token=${encodeURIComponent(token)}`
      setStatus(attempt === 0 ? 'connecting' : 'reconnecting')
      socket = new WebSocket(url)

      socket.onopen = () => {
        if (closed) return
        attempt = 0
        setStatus('connected')
        pingTimer = window.setInterval(() => {
          if (socket?.readyState === WebSocket.OPEN) {
            socket.send(JSON.stringify({ type: 'ping' }))
          }
        }, 30000)
      }

      socket.onmessage = (event) => {
        try {
          const message = JSON.parse(event.data) as { type?: string }
          if (message.type === 'pong') return
          handlerRef.current(message as StreamMessage)
        } catch {
          // 忽略非 JSON 消息
        }
      }

      socket.onclose = (event) => {
        if (pingTimer) window.clearInterval(pingTimer)
        pingTimer = undefined
        if (closed) return
        if ([4401, 4403, 4404].includes(event.code)) {
          setStatus('disconnected')
          return
        }
        const delay = RECONNECT_DELAYS[Math.min(attempt, RECONNECT_DELAYS.length - 1)]
        attempt += 1
        setStatus('reconnecting')
        reconnectTimer = window.setTimeout(connect, delay)
      }

      socket.onerror = () => {
        socket?.close()
      }
    }

    connect()
    return () => {
      closed = true
      clearTimers()
      if (socket && socket.readyState === WebSocket.OPEN) {
        socket.close()
      }
    }
  }, [projectId])

  return status
}
