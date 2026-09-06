import http from './http'

/** 知识库管理相关接口(全部仅管理员可用,后端 403 兜底)。 */

export interface KbInfo {
  id: number
  name: string
  description?: string | null
  category?: string | null
  doc_count: number
  chunk_count: number
  created_at: string
  updated_at: string
}

export interface DocumentItem {
  id: number
  kb_id: number
  filename: string
  file_type: string
  size_bytes: number
  parse_status: 'pending' | 'parsing' | 'done' | 'failed'
  progress_done: number
  progress_total: number
  error_msg?: string | null
  version: number
  chunk_count: number
  sha256: string
  created_at: string
  finished_at?: string | null
}

export interface ChunkItem {
  id: string
  doc_id: number
  kb_id: number
  seq: number
  text: string
  meta_json?: string | null
  created_at: string
}

export interface Page<T> {
  items: T[]
  total: number
}

export interface DebugHit {
  chunk_id: string
  score: number
  source?: string
  text: string
}

export interface DebugResult {
  vector_hits: DebugHit[]
  keyword_hits: DebugHit[]
  fused_hits: DebugHit[]
  reranked_hits: DebugHit[]
  refused: boolean
  threshold: number
}

// ==================== 知识库 ====================
/** 登录用户(含普通用户)可用的知识库名列表,供问答页选择检索范围 */
export function listKbNames() {
  return http.get<{ id: number; name: string }[]>('/kb/public')
}

export const kbApi = {
  list: () => http.get<KbInfo[]>('/kb'),
  get: (id: number) => http.get<KbInfo>(`/kb/${id}`),
  create: (data: Partial<KbInfo>) => http.post<KbInfo>('/kb', data),
  update: (id: number, data: Partial<KbInfo>) => http.patch<KbInfo>(`/kb/${id}`, data),
  remove: (id: number) => http.delete(`/kb/${id}`),
}

// ==================== 文档 ====================
export const docApi = {
  list: (kbId: number) => http.get<DocumentItem[]>(`/documents/kb/${kbId}`),
  get: (id: number) => http.get<DocumentItem>(`/documents/${id}`),
  remove: (id: number) => http.delete(`/documents/${id}`),
  reparse: (id: number) => http.post<DocumentItem>(`/documents/${id}/reparse`),
  /** 上传单个文件;replace=true 表示已存在时覆盖重传 */
  upload: (kbId: number, file: File, replace = false) => {
    const form = new FormData()
    form.append('file', file)
    return http.post<DocumentItem>(`/documents/kb/${kbId}/upload?replace=${replace}`, form, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 0, // 大文件上传不限时
    })
  },
}

// ==================== 分块 ====================
export const chunkApi = {
  list: (kbId: number, params: { page?: number; size?: number; q?: string }) =>
    http.get<Page<ChunkItem>>(`/chunks/kb/${kbId}`, { params }),
  remove: (chunkId: string) => http.delete(`/chunks/${chunkId}`),
}

// ==================== 检索调试 ====================
export const debugApi = {
  search: (data: { question: string; kb_id?: number | null }) =>
    http.post<DebugResult>('/debug/search', data),
}
