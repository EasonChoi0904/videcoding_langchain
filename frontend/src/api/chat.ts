import http from './http'
import { useAuthStore } from '../stores/auth'

/** 会话 / 消息 / SSE 流式问答接口。 */

export interface Conversation {
  id: number
  title: string
  language: 'zh' | 'en' | 'auto'
  summary_text?: string | null
  message_count: number
  last_active_at: string
  created_at: string
  updated_at: string
  preview?: string | null
}

export interface Citation {
  n: number
  chunk_id: string
  kb_id?: number
  kb_name?: string
  doc_name?: string
  location?: string
  text: string
  score: number
}

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  /** null = 生成中断的半截消息(可重新生成);[] 或列表 = 正常完成 */
  citations: Citation[] | null
  is_streaming: boolean
  latency_ms?: number | null
  model?: string | null
  created_at: string
}

export interface MsgPage {
  items: ChatMessage[]
  next_cursor: string | null
}

export const convApi = {
  list: () => http.get<Conversation[]>('/conversations'),
  create: (data: { title?: string; language?: string }) =>
    http.post<Conversation>('/conversations', data),
  update: (id: number, data: { title?: string; language?: string }) =>
    http.patch<Conversation>(`/conversations/${id}`, data),
  remove: (id: number) => http.delete(`/conversations/${id}`),
  search: (q: string) => http.get<Conversation[]>('/conversations/search', { params: { q } }),
  messages: (id: number, cursor?: string | null) =>
    http.get<MsgPage>(`/conversations/${id}/messages`, {
      params: cursor ? { cursor, limit: 50 } : { limit: 50 },
    }),
  export: (id: number) => http.get<{ filename: string; content: string }>(`/conversations/${id}/export`),
  feedback: (messageId: string, value: 1 | -1, comment?: string) =>
    http.post(`/messages/${messageId}/feedback`, { value, comment }),
}

export interface AskEvents {
  onCitations?: (sources: Citation[], cached: boolean) => void
  onToken?: (delta: string) => void
  onDone?: (info: { message_id: string; conversation_id: number; refused: boolean; title?: string | null }) => void
  onError?: (code: string, message: string) => void
}

/**
 * 解析单块 SSE 报文并分发到事件回调(纯函数,便于单元测试)。
 * 报文格式:event: <name>\ndata: <json>\n\n
 */
export function handleSseBlock(block: string, events: AskEvents): void {
  const m = block.match(/^event: (\S+)\ndata: (.+)$/ms)
  if (!m) return
  const event = m[1]
  let data: any
  try {
    data = JSON.parse(m[2])
  } catch {
    return // 畸形 JSON 忽略,不影响后续块
  }
  if (event === 'citations') events.onCitations?.(data.sources || [], !!data.cached)
  else if (event === 'token') events.onToken?.(data.delta || '')
  else if (event === 'done')
    events.onDone?.({
      message_id: data.message_id,
      conversation_id: data.conversation_id,
      refused: !!data.refused,
      title: data.title,
    })
  else if (event === 'error') events.onError?.(data.code || 'UNKNOWN', data.message || '未知错误')
}

/** 发起流式问答(fetch 读流;支持 AbortController 停止) */
export async function askStream(
  convId: number,
  content: string,
  kbId: number | null,
  signal: AbortSignal,
  events: AskEvents,
): Promise<void> {
  const auth = useAuthStore()
  const resp = await fetch(`/api/chat/${convId}/ask`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${auth.accessToken}`,
    },
    body: JSON.stringify({ content, kb_id: kbId }),
    signal,
  })

  if (!resp.ok || !resp.body) {
    let detail = `请求失败(HTTP ${resp.status})`
    try {
      const data = await resp.json()
      if (data?.detail) detail = typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail)
    } catch {
      /* 非 JSON 错误体 */
    }
    if (resp.status === 401) {
      detail = '登录已过期,请重新登录'
    }
    events.onError?.('HTTP', detail)
    return
  }

  const reader = resp.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buf = ''

  const dispatch = (block: string) => handleSseBlock(block, events)

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buf += decoder.decode(value, { stream: true })
    // SSE 块以空行分隔,逐块取出
    let idx: number
    while ((idx = buf.indexOf('\n\n')) >= 0) {
      const block = buf.slice(0, idx)
      buf = buf.slice(idx + 2)
      if (block.trim()) dispatch(block)
    }
  }
  if (buf.trim()) dispatch(buf) // 末尾残留块
}
