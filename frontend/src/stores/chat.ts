import { defineStore } from 'pinia'
import { ref } from 'vue'
import { convApi, type ChatMessage, type Conversation } from '../api/chat'

/**
 * 会话状态:会话列表 + 当前会话的消息流。
 * 消息在本地先以"占位"渲染(流式期间实时追加),done/error 后同步真实 id。
 */
export const useChatStore = defineStore('chat', () => {
  const conversations = ref<Conversation[]>([])
  const activeConvId = ref<number | null>(null)
  /** 消息按时间序 */
  const messages = ref<ChatMessage[]>([])
  const loadingMessages = ref(false)
  const hasMore = ref(false)
  const nextCursor = ref<string | null>(null)

  const activeConv = (): Conversation | undefined =>
    conversations.value.find((c) => c.id === activeConvId.value)

  async function refreshList() {
    const { data } = await convApi.list()
    conversations.value = data
  }

  async function createConversation(language = 'auto'): Promise<Conversation> {
    const { data } = await convApi.create({ language })
    conversations.value.unshift(data)
    activeConvId.value = data.id
    messages.value = []
    hasMore.value = false
    nextCursor.value = null
    return data
  }

  async function loadMessages(convId: number) {
    activeConvId.value = convId
    loadingMessages.value = true
    try {
      const { data } = await convApi.messages(convId)
      messages.value = data.items
      nextCursor.value = data.next_cursor
      hasMore.value = !!data.next_cursor
    } finally {
      loadingMessages.value = false
    }
  }

  /** 向上翻页加载更早消息 */
  async function loadEarlier() {
    if (!activeConvId.value || !nextCursor.value) return
    const { data } = await convApi.messages(activeConvId.value, nextCursor.value)
    messages.value = [...data.items, ...messages.value]
    nextCursor.value = data.next_cursor
    hasMore.value = !!data.next_cursor
  }

  /** 本地追加用户提问占位(流式结束后由服务器回查真实消息) */
  function pushLocalUser(question: string) {
    messages.value.push({
      id: `local-${Date.now()}`,
      role: 'user',
      content: question,
      citations: [],
      is_streaming: false,
      created_at: new Date().toISOString(),
    })
  }

  /** 助手占位消息:返回其索引 */
  function pushAssistantPlaceholder(): number {
    const msg: ChatMessage = {
      id: `streaming-${Date.now()}`,
      role: 'assistant',
      content: '',
      citations: [],
      is_streaming: true,
      created_at: new Date().toISOString(),
    }
    messages.value.push(msg)
    return messages.value.length - 1
  }

  function appendToken(idx: number, delta: string) {
    messages.value[idx].content += delta
  }

  function attachCitations(idx: number, sources: any[]) {
    messages.value[idx].citations = sources
  }

  function finishStreaming(idx: number, refused: boolean) {
    const m = messages.value[idx]
    m.is_streaming = false
    m.citations = m.citations || []
    ;(m as any)._refused = refused
  }

  /** 删除本轮本地临时消息(用户提问占位 + 助手流式占位;重试/失败清理用) */
  function removeLocal() {
    messages.value = messages.value.filter(
      (m) => !m.id.startsWith('local-') && !m.id.startsWith('streaming-'),
    )
  }

  async function removeConversation(id: number) {
    await convApi.remove(id)
    conversations.value = conversations.value.filter((c) => c.id !== id)
    if (activeConvId.value === id) {
      activeConvId.value = null
      messages.value = []
    }
  }

  /** 清空全部会话状态(登录/登出时调用,防止不同账号的会话串显) */
  function clearAll() {
    conversations.value = []
    activeConvId.value = null
    messages.value = []
    hasMore.value = false
    nextCursor.value = null
  }

  return {
    conversations,
    activeConvId,
    messages,
    loadingMessages,
    hasMore,
    nextCursor,
    activeConv,
    refreshList,
    createConversation,
    loadMessages,
    loadEarlier,
    pushLocalUser,
    pushAssistantPlaceholder,
    appendToken,
    attachCitations,
    finishStreaming,
    removeLocal,
    removeConversation,
    clearAll,
  }
})
