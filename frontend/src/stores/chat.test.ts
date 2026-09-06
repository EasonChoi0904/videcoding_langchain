import { beforeEach, describe, expect, test, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useChatStore } from './chat'

// 屏蔽 convApi(http 依赖链含浏览器环境依赖);本测试只覆盖纯状态运算
vi.mock('../api/chat', () => ({
  convApi: {
    list: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
    remove: vi.fn(),
    search: vi.fn(),
    messages: vi.fn(),
    export: vi.fn(),
    feedback: vi.fn(),
  },
  askStream: vi.fn(),
}))

/** 会话状态运算测试:只测纯状态方法,不触发 API 请求。 */

describe('会话状态运算(useChatStore)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  test('新用户提问占位追加到消息流末尾', () => {
    const store = useChatStore()
    store.pushLocalUser('小米15 Pro 多少钱?')
    expect(store.messages).toHaveLength(1)
    expect(store.messages[0].role).toBe('user')
    expect(store.messages[0].content).toBe('小米15 Pro 多少钱?')
  })

  test('助手占位消息进入流式态,追加 token 后内容拼接', () => {
    const store = useChatStore()
    const idx = store.pushAssistantPlaceholder()
    expect(store.messages[idx].is_streaming).toBe(true)
    store.appendToken(idx, '小米15')
    store.appendToken(idx, ' Pro')
    store.appendToken(idx, ' 起售价 4499 元')
    expect(store.messages[idx].content).toBe('小米15 Pro 起售价 4499 元')
  })

  test('引用片段挂到助手消息上(与正文 [n] 对应)', () => {
    const store = useChatStore()
    const idx = store.pushAssistantPlaceholder()
    const sources = [{ n: 1, doc_name: '参数表.xlsx', text: 'x', score: 0.9 }]
    store.attachCitations(idx, sources)
    expect(store.messages[idx].citations).toEqual(sources)
  })

  test('流式完成后解除 is_streaming,引用默认空数组而非 null', () => {
    const store = useChatStore()
    const idx = store.pushAssistantPlaceholder()
    store.finishStreaming(idx, false)
    const m = store.messages[idx]
    expect(m.is_streaming).toBe(false)
    expect(m.citations).toEqual([])
  })

  test('拒绝回答同样正常收尾(refused 标记保留在消息上)', () => {
    const store = useChatStore()
    const idx = store.pushAssistantPlaceholder()
    store.finishStreaming(idx, true)
    expect((store.messages[idx] as any)._refused).toBe(true)
  })

  test('失败清理:移除本地临时消息(保留真实消息)', () => {
    const store = useChatStore()
    store.pushLocalUser('问题')
    const idx = store.pushAssistantPlaceholder()
    store.appendToken(idx, '部分内容')
    store.removeLocal()
    expect(store.messages).toHaveLength(0)
  })

  test('clearAll 清空会话列表与消息流(跨账号切换防串号)', () => {
    const store = useChatStore()
    store.pushLocalUser('遗留问题')
    store.conversations = [{ id: 1 } as any]
    store.activeConvId = 1
    store.clearAll()
    expect(store.messages).toHaveLength(0)
    expect(store.conversations).toHaveLength(0)
    expect(store.activeConvId).toBeNull()
    expect(store.hasMore).toBe(false)
  })

  test('消息按追加顺序保持(时间正序渲染依赖此性质)', () => {
    const store = useChatStore()
    store.pushLocalUser('第一个问题')
    store.pushAssistantPlaceholder()
    store.pushLocalUser('第二个问题')
    expect(store.messages.map((m) => m.role)).toEqual(['user', 'assistant', 'user'])
  })
})
