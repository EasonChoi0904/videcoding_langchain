import http from './http'

/** 管理端:系统设置与统计看板接口(仅管理员)。 */

export interface SettingItem {
  key: string
  value: string
  label: string
  type: 'float' | 'int' | 'text' | 'bool'
  description?: string
  updated_at?: string
}

export interface StatsOverview {
  totals: {
    users: number
    kbs: number
    docs: number
    chunks: number
    conversations: number
    messages: number
  }
  trend_7d: { date: string; count: number }[]
  avg_latency_ms: number | null
  model_usage: { model: string; count: number }[]
  feedback: { likes: number; dislikes: number; total: number }
  kb_dist: { name: string; chunks: number }[]
}

export const settingApi = {
  list: () => http.get<SettingItem[]>('/settings'),
  save: (items: { key: string; value: string }[]) => http.put('/settings', items),
}

export const statsApi = {
  overview: () => http.get<StatsOverview>('/admin/stats'),
}
