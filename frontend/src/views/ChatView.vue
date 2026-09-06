<template>
  <div class="chat-layout">
    <!-- ============ 左侧:会话侧边栏 ============ -->
    <aside class="sidebar">
      <el-button type="primary" class="new-chat-btn" :icon="Plus" @click="onNewChat">
        新会话
      </el-button>

      <el-input
        v-model="searchText"
        :prefix-icon="Search"
        placeholder="搜索历史会话"
        clearable
        class="search-box"
        @input="onSearchInput"
      />

      <div class="conv-list" v-loading="listLoading">
        <template v-if="visibleConvs.length">
          <div
            v-for="c in visibleConvs"
            :key="c.id"
            class="conv-item"
            :class="{ active: c.id === chat.activeConvId }"
            @click="onOpenConv(c.id)"
          >
            <div class="conv-main">
              <div class="conv-title">{{ c.title }}</div>
              <div class="conv-preview">{{ c.preview || '暂无消息' }}</div>
            </div>
            <el-dropdown
              trigger="click"
              @command="(cmd: string) => onConvCommand(cmd, c)"
              @click.stop
            >
              <el-icon class="conv-more" @click.stop><MoreFilled /></el-icon>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item command="rename">重命名</el-dropdown-item>
                  <el-dropdown-item command="export">导出对话</el-dropdown-item>
                  <el-dropdown-item command="delete" divided>删除会话</el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </div>
        </template>
        <el-empty v-else-if="!listLoading" description="暂无会话" :image-size="60" />
      </div>
    </aside>

    <!-- ============ 右侧:聊天主区 ============ -->
    <main class="chat-main">
      <template v-if="chat.activeConvId">
        <!-- 会话顶栏:标题 + 回答语言 + 知识库限定 -->
        <div class="chat-header">
          <span class="conv-title-head">{{ activeConv?.title }}</span>
          <div class="header-controls">
            <el-select
              :model-value="activeConv?.language"
              class="lang-select"
              @change="(v: string) => onLangChange(v)"
            >
              <el-option label="🌐 自动(中英)" value="auto" />
              <el-option label="中文回答" value="zh" />
              <el-option label="English" value="en" />
            </el-select>
            <el-select
              :model-value="scopeKbId"
              placeholder="全部知识库"
              clearable
              class="kb-select"
              @change="scopeKbId = ($event as number) || null"
            >
              <el-option label="全部知识库" :value="null as any" />
              <el-option v-for="kb in kbList" :key="kb.id" :label="kb.name" :value="kb.id" />
            </el-select>
          </div>
        </div>

        <!-- 消息区 -->
        <div ref="scrollBox" class="msg-area" @scroll="onScroll">
          <div v-if="chat.hasMore && !loadingMore" class="load-more" @click="loadMore">
            ↑ 加载更早消息
          </div>

          <div v-for="(msg, idx) in chat.messages" :key="msg.id" class="msg-row" :class="msg.role">
            <div class="avatar">
              <el-avatar v-if="msg.role === 'user'" :size="34" class="user-avatar">
                {{ avatarText }}
              </el-avatar>
              <el-avatar v-else :size="34" class="ai-avatar">
                <el-icon><ChatDotRound /></el-icon>
              </el-avatar>
            </div>

            <div class="msg-body">
              <div class="bubble" :class="msg.role">
                <!-- 用户消息:纯文本 -->
                <div v-if="msg.role === 'user'" class="user-text">{{ msg.content }}</div>

                <!-- 助手消息:Markdown + 引用 -->
                <template v-else>
                  <div v-if="!msg.content && msg.is_streaming" class="thinking">
                    <span class="dot" />正在思考中...
                  </div>
                  <MarkdownViewer
                    v-if="msg.content"
                    :content="msg.content"
                    :streaming="msg.is_streaming"
                    @cite="(n: number) => (highlightCite = n)"
                  />

                  <!-- 中断/失败提示 -->
                  <el-tag v-if="isAborted(msg)" type="warning" size="small" class="aborted-tag">
                    回答已中断
                  </el-tag>
                </template>
              </div>

              <!-- 操作条:仅助手消息 -->
              <div v-if="msg.role === 'assistant'" class="msg-actions">
                <template v-if="!isAborted(msg)">
                  <el-tooltip content="回答有帮助">
                    <el-icon
                      :class="['action-icon', { on: feedbackOf(msg) === 1 }]"
                      @click="sendFeedback(msg, 1)"
                    ><CaretTop /></el-icon>
                  </el-tooltip>
                  <el-tooltip content="回答不准确">
                    <el-icon
                      :class="['action-icon', 'down', { on: feedbackOf(msg) === -1 }]"
                      @click="sendFeedback(msg, -1)"
                    ><CaretBottom /></el-icon>
                  </el-tooltip>
                  <el-tooltip content="复制回答">
                    <el-icon class="action-icon" @click="copyText(msg.content)"><CopyDocument /></el-icon>
                  </el-tooltip>
                </template>
                <el-tooltip content="停止生成" v-if="streaming && isLastMsg(msg)">
                  <el-icon class="action-icon stop" @click="stopAsk"><CircleClose /></el-icon>
                </el-tooltip>
                <el-tooltip content="重新生成" v-if="!streaming && isLastMsg(msg)">
                  <el-icon class="action-icon" @click="regen"><RefreshRight /></el-icon>
                </el-tooltip>
              </div>

              <!-- 引用溯源面板 -->
              <CitationPanel
                v-if="msg.role === 'assistant' && msg.citations"
                :sources="msg.citations"
                :highlight="highlightCite"
              />
            </div>
          </div>
          <div ref="bottomAnchor" />
        </div>

        <!-- 输入区 -->
        <div class="input-area">
          <div v-if="streaming" class="streaming-bar">
            <el-icon class="is-loading"><Loading /></el-icon>
            <span>AI 正在回答,点击右侧停止...</span>
          </div>
          <el-input
            v-model="draft"
            type="textarea"
            :rows="2"
            :placeholder="streaming ? '等待回答中...' : '请输入商品问题,Enter 发送,Shift+Enter 换行'"
            resize="none"
            :disabled="streaming"
            @keydown.enter.exact.prevent="send"
          />
          <div class="input-foot">
            <span class="hint">{{ kbFilterTip }}</span>
            <el-button
              type="primary"
              :icon="Promotion"
              :loading="streaming"
              :disabled="!draft.trim()"
              @click="send"
            >
              发送
            </el-button>
          </div>
        </div>
      </template>

      <!-- 空状态:未选会话 -->
      <div v-else class="empty-main">
        <el-icon :size="56" color="#c0c4cc"><ChatDotRound /></el-icon>
        <h2>基于 LangChain 的企业级 RAG 知识库问答</h2>
        <p>支持引用溯源 · 多会话多语言 · 历史对话找回</p>
        <el-button type="primary" size="large" @click="onNewChat">开始第一个会话</el-button>
      </div>
    </main>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onBeforeUnmount, nextTick, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  CaretBottom,
  CaretTop,
  ChatDotRound,
  CircleClose,
  CopyDocument,
  Loading,
  MoreFilled,
  Plus,
  Promotion,
  RefreshRight,
  Search,
} from '@element-plus/icons-vue'
import { useAuthStore } from '../stores/auth'
import { useChatStore } from '../stores/chat'
import { askStream, convApi, type Conversation } from '../api/chat'
import { kbApi, listKbNames, type KbInfo } from '../api/kb'
import MarkdownViewer from '../components/MarkdownViewer.vue'
import CitationPanel from '../components/CitationPanel.vue'

const auth = useAuthStore()
const chat = useChatStore()

const draft = ref('')
const streaming = ref(false)
const listLoading = ref(false)
const searchText = ref('')
const scopeKbId = ref<number | null>(null)
const kbList = ref<KbInfo[]>([])
const highlightCite = ref<number | null>(null)
const scrollBox = ref<HTMLElement | null>(null)
const bottomAnchor = ref<HTMLElement | null>(null)
const loadingMore = ref(false)
let abortCtrl: AbortController | null = null

const avatarText = computed(() => auth.user?.username?.slice(0, 1).toUpperCase() || 'U')
const activeConv = computed(() => chat.activeConv())
const visibleConvs = computed(() => {
  const q = searchText.value.trim()
  if (!q) return chat.conversations
  return chat.conversations.filter((c) => c.title.toLowerCase().includes(q.toLowerCase()))
})
const kbFilterTip = computed(() =>
  scopeKbId.value
    ? `当前限定在「${kbList.value.find((k) => k.id === scopeKbId.value)?.name}」内检索`
    : '',
)

function isLastMsg(msg: { id: string }) {
  return chat.messages[chat.messages.length - 1]?.id === msg.id
}

/** citations 为 null = 生成中断(后端约定) */
function isAborted(msg: any) {
  return msg.role === 'assistant' && msg.citations === null
}

const feedbackMap = new Map<string, 1 | -1>()
function feedbackOf(msg: any) {
  return feedbackMap.get(msg.id) || 0
}

// ==================== 会话管理 ====================
async function refreshList() {
  listLoading.value = true
  try {
    await chat.refreshList()
  } finally {
    listLoading.value = false
  }
}

async function onNewChat() {
  const conv = await chat.createConversation()
  if (conv) await refreshList()
  scrollBottom()
}

async function onOpenConv(id: number) {
  if (streaming.value) return ElMessage.warning('请先停止当前回答')
  streaming.value = false
  abortCtrl?.abort()
  await chat.loadMessages(id)
  await refreshList()
  scrollBottom()
}

async function onConvCommand(cmd: string, conv: Conversation) {
  if (cmd === 'rename') {
    const { value } = await ElMessageBox.prompt('输入新的会话标题', '重命名', {
      inputValue: conv.title,
      inputValidator: (v: string) => (v?.trim() ? true : '标题不能为空'),
    })
    await convApi.update(conv.id, { title: value.trim() })
    await refreshList()
    ElMessage.success('已重命名')
  } else if (cmd === 'export') {
    const { data } = await convApi.export(conv.id)
    downloadText(data.filename, data.content)
    ElMessage.success('已导出为 Markdown')
  } else if (cmd === 'delete') {
    await ElMessageBox.confirm('删除会话将同时删除全部消息记录,确定?', '删除会话', {
      type: 'warning',
      confirmButtonText: '删除',
    })
    await chat.removeConversation(conv.id)
    await refreshList()
    ElMessage.success('会话已删除')
  }
}

function onLangChange(v: string) {
  if (!chat.activeConvId) return
  convApi.update(chat.activeConvId, { language: v as any }).then(() => refreshList())
}

// ==================== 提问 ====================
async function send() {
  const q = draft.value.trim()
  if (!q || streaming.value || !chat.activeConvId) return
  streaming.value = true
  draft.value = ''
  chat.pushLocalUser(q)
  const idx = chat.pushAssistantPlaceholder()
  scrollBottom()

  abortCtrl = new AbortController()
  try {
    await askStream(chat.activeConvId, q, scopeKbId.value, abortCtrl.signal, {
      onCitations: (sources) => {
        chat.attachCitations(idx, sources)
        scrollBottom()
      },
      onToken: () => scrollBottomIfNear(),
      onDone: async (info) => {
        chat.finishStreaming(idx, info.refused)
        // 服务器真实消息入列,移除本地占位再重载,保证引用/状态一致
        if (info.message_id) {
          await chat.loadMessages(chat.activeConvId!)
        }
        if (info.title) await refreshList()
        streaming.value = false
        scrollBottom()
      },
      onError: (code, message) => {
        chat.removeLocal()
        streaming.value = false
        ElMessage.error(message || `问答失败(${code})`)
      },
    })
  } catch (e: any) {
    // 主动停止不算错误
    if (e?.name !== 'AbortError') {
      ElMessage.error('网络异常,请重试')
      chat.removeLocal()
    }
    streaming.value = false
  }
}

function stopAsk() {
  abortCtrl?.abort()
  // 服务器端在断连时会把半截消息落库并解除流式标记
  setTimeout(async () => {
    streaming.value = false
    if (chat.activeConvId) await chat.loadMessages(chat.activeConvId)
  }, 800)
}

async function regen() {
  // 重新生成:取最后一条用户提问重发(服务端会自动顶替上一轮半截消息)
  const lastUser = [...chat.messages].reverse().find((m) => m.role === 'user')
  if (!lastUser) return
  draft.value = lastUser.content
  await send()
}

async function sendFeedback(msg: any, value: 1 | -1) {
  feedbackMap.set(msg.id, value)
  try {
    // 后端按"一条消息一个反馈"覆盖写,重复点击仅切换方向
    await convApi.feedback(msg.id, value)
    ElMessage.success(value === 1 ? '感谢认可 👍' : '感谢反馈,我们会改进 🙏')
  } catch {
    feedbackMap.delete(msg.id)
  }
}

// ==================== 辅助 ====================
function copyText(text: string) {
  navigator.clipboard?.writeText(text)
  ElMessage.success('已复制')
}

function downloadText(filename: string, content: string) {
  const blob = new Blob([content], { type: 'text/markdown;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

let nearBottom = true
function scrollBottomIfNear() {
  if (nearBottom) scrollBottom()
}
function scrollBottom() {
  nextTick(() => bottomAnchor.value?.scrollIntoView({ behavior: 'smooth' }))
}
function onScroll() {
  const el = scrollBox.value
  if (!el) return
  nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 80
}

async function loadMore() {
  loadingMore.value = true
  try {
    await chat.loadEarlier()
  } finally {
    loadingMore.value = false
  }
}

function onSearchInput() {
  /* 实时过滤在 computed 中完成 */
}

async function loadKbs() {
  try {
    // 管理员走完整列表(含统计);普通用户走公共只读列表(仅名称,用于检索范围选择)
    const { data } = auth.isAdmin ? await kbApi.list() : await listKbNames()
    kbList.value = data as KbInfo[]
  } catch {
    kbList.value = []
  }
}

onMounted(async () => {
  await refreshList()
  await loadKbs()
  // 默认选中最近会话
  if (chat.conversations.length && !chat.activeConvId) {
    await chat.loadMessages(chat.conversations[0].id)
    scrollBottom()
  }
})
onBeforeUnmount(() => abortCtrl?.abort())
</script>

<style scoped>
.chat-layout {
  display: flex;
  height: 100%;
}
/* ===== 侧边栏 ===== */
.sidebar {
  width: 272px;
  min-width: 272px;
  background: #fff;
  border-right: 1px solid #e8eaf0;
  display: flex;
  flex-direction: column;
  padding: 12px;
  gap: 10px;
}
.new-chat-btn {
  width: 100%;
}
.search-box {
  width: 100%;
}
.conv-list {
  flex: 1;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.conv-item {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 9px 10px;
  border-radius: 8px;
  cursor: pointer;
  transition: background 0.15s;
}
.conv-item:hover {
  background: #f2f6fc;
}
.conv-item.active {
  background: #e8f3ff;
}
.conv-main {
  flex: 1;
  min-width: 0;
}
.conv-title {
  font-size: 13.5px;
  color: #1f2d3d;
  font-weight: 500;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.conv-preview {
  font-size: 12px;
  color: #a0a6b4;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  margin-top: 2px;
}
.conv-more {
  color: #b0b7c3;
  cursor: pointer;
  flex-shrink: 0;
}
.conv-more:hover {
  color: #409eff;
}

/* ===== 聊天主区 ===== */
.chat-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
  background: #f7f9fc;
}
.chat-header {
  height: 52px;
  background: #fff;
  border-bottom: 1px solid #e8eaf0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 18px;
  flex-shrink: 0;
}
.conv-title-head {
  font-weight: 600;
  color: #1f2d3d;
  font-size: 15px;
  max-width: 45%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.header-controls {
  display: flex;
  gap: 8px;
}
.lang-select {
  width: 132px;
}
.kb-select {
  width: 170px;
}

/* ===== 消息区 ===== */
.msg-area {
  flex: 1;
  overflow-y: auto;
  padding: 18px 6% 10px;
  display: flex;
  flex-direction: column;
  gap: 18px;
}
.load-more {
  align-self: center;
  color: #409eff;
  font-size: 12.5px;
  cursor: pointer;
  padding: 4px 12px;
  border-radius: 12px;
  background: #fff;
}
.load-more:hover {
  background: #e8f3ff;
}
.msg-row {
  display: flex;
  gap: 10px;
  max-width: 92%;
}
.msg-row.user {
  align-self: flex-end;
  flex-direction: row-reverse;
}
.user-avatar {
  background: #67c23a;
  color: #fff;
}
.ai-avatar {
  background: #409eff;
  color: #fff;
}
.msg-body {
  min-width: 0;
  max-width: 100%;
  flex: 1;
}
.msg-row.user .msg-body {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
}
.bubble {
  padding: 10px 14px;
  border-radius: 12px;
  font-size: 14px;
  box-shadow: 0 1px 3px rgba(0, 21, 41, 0.06);
}
.bubble.user {
  background: #409eff;
  color: #fff;
  border-top-right-radius: 3px;
}
.bubble.assistant {
  background: #fff;
  border-top-left-radius: 3px;
}
.user-text {
  white-space: pre-wrap;
  word-break: break-word;
  line-height: 1.6;
}
.thinking {
  display: flex;
  align-items: center;
  gap: 8px;
  color: #909399;
  font-size: 13px;
}
.dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #409eff;
  animation: pulse 1s infinite ease-in-out;
}
@keyframes pulse {
  0%, 100% { opacity: 0.25; }
  50% { opacity: 1; }
}
.aborted-tag {
  margin-top: 8px;
}
.msg-actions {
  display: flex;
  gap: 12px;
  margin-top: 6px;
  padding: 0 4px;
  opacity: 0;
  transition: opacity 0.2s;
}
.msg-row:hover .msg-actions {
  opacity: 1;
}
.action-icon {
  color: #a8aec0;
  cursor: pointer;
  font-size: 15px;
}
.action-icon:hover,
.action-icon.on {
  color: #409eff;
}
.action-icon.down.on {
  color: #e6a23c;
}
.action-icon.stop:hover {
  color: #f56c6c;
}

/* ===== 输入区 ===== */
.input-area {
  background: #fff;
  border-top: 1px solid #e8eaf0;
  padding: 10px 6% 14px;
  flex-shrink: 0;
}
.streaming-bar {
  display: flex;
  align-items: center;
  gap: 6px;
  color: #409eff;
  font-size: 12.5px;
  margin-bottom: 6px;
}
.input-foot {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 8px;
}
.hint {
  color: #b0b7c3;
  font-size: 12px;
}

/* ===== 空状态 ===== */
.empty-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  color: #6b7280;
}
.empty-main h2 {
  margin: 10px 0 0;
  color: #303133;
}
</style>
