<template>
  <div class="detail-page">
    <div class="page-head">
      <el-button :icon="ArrowLeft" link @click="router.push('/kb')">返回</el-button>
      <h2>{{ kb?.name }}</h2>
      <el-tag v-if="kb?.category" type="info">{{ kb.category }}</el-tag>
      <span class="stat">文档 {{ kb?.doc_count || 0 }} · 分块 {{ kb?.chunk_count || 0 }}</span>
    </div>

    <el-tabs v-model="tab" class="tabs">
      <!-- ============ Tab1 文档管理 ============ -->
      <el-tab-pane label="文档管理" name="docs">
        <div class="upload-bar">
          <el-upload
            :auto-upload="false"
            multiple
            drag
            :on-change="onFilesChange"
            :show-file-list="false"
            accept=".pdf,.docx,.xlsx,.csv,.txt,.md,.html,.htm"
          >
            <div class="upload-tip">
              <el-icon :size="36" color="#c0c4cc"><UploadFilled /></el-icon>
              <p>拖拽文件到此处,或点击选择(支持 PDF / Word / Excel / CSV / TXT / MD / HTML)</p>
            </div>
          </el-upload>
          <el-checkbox v-model="replaceMode" class="replace-cb">已存在文件时覆盖重传</el-checkbox>
        </div>

        <el-table :data="docs" v-loading="docsLoading" empty-text="暂无文档">
          <el-table-column label="文件名" min-width="260">
            <template #default="{ row }">
              <span>{{ row.filename }}</span>
              <el-tag size="small" class="type-tag">{{ row.file_type }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="解析状态" width="210">
            <template #default="{ row }">
              <el-tag v-if="row.parse_status === 'done'" type="success">已完成</el-tag>
              <el-tag v-else-if="row.parse_status === 'failed'" type="danger">失败</el-tag>
              <el-tag v-else type="warning">
                {{ row.parse_status === 'pending' ? '排队中' : '解析中' }}
              </el-tag>
              <el-progress
                v-if="row.parse_status === 'parsing' && row.progress_total"
                :percentage="Math.round((row.progress_done / row.progress_total) * 100)"
                class="mini-progress"
              />
              <div v-if="row.parse_status === 'failed' && row.error_msg" class="err-tip">
                {{ row.error_msg.slice(0, 80) }}
              </div>
            </template>
          </el-table-column>
          <el-table-column label="分块数" width="80" prop="chunk_count" />
          <el-table-column label="版本" width="70" prop="version" />
          <el-table-column label="大小" width="90">
            <template #default="{ row }">{{ fmtSize(row.size_bytes) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="170" fixed="right">
            <template #default="{ row }">
              <el-button
                v-if="row.parse_status !== 'parsing'"
                size="small"
                :icon="Refresh"
                @click="onReparse(row)"
              >重新解析</el-button>
              <el-popconfirm title="删除该文档及其全部分块?" confirm-button-text="删除" @confirm="onDeleteDoc(row)">
                <template #reference>
                  <el-button size="small" type="danger" :icon="Delete" plain>删除</el-button>
                </template>
              </el-popconfirm>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <!-- ============ Tab2 分块浏览 ============ -->
      <el-tab-pane label="分块浏览" name="chunks">
        <div class="chunk-bar">
          <el-input
            v-model="chunkQuery"
            :prefix-icon="Search"
            placeholder="搜索分块内容(关键词)"
            clearable
            class="chunk-search"
            @keyup.enter="loadChunks(1)"
            @clear="loadChunks(1)"
          />
          <el-button type="primary" @click="loadChunks(1)">搜索</el-button>
          <span class="chunk-total">共 {{ chunkTotal }} 个分块</span>
        </div>
        <el-table
          :data="chunks"
          v-loading="chunksLoading"
          empty-text="暂无分块"
          class="chunk-table"
        >
          <el-table-column label="分块内容" min-width="520">
            <template #default="{ row }">
              <div class="chunk-text">{{ row.text }}</div>
            </template>
          </el-table-column>
          <el-table-column label="来源文档" width="200">
            <template #default="{ row }">{{ docName(row.doc_id) }}</template>
          </el-table-column>
          <el-table-column label="序号" width="70" prop="seq" />
          <el-table-column label="操作" width="90" fixed="right">
            <template #default="{ row }">
              <el-popconfirm title="删除该分块?" confirm-button-text="删除" @confirm="onDeleteChunk(row)">
                <template #reference>
                  <el-button size="small" type="danger" :icon="Delete" plain>删除</el-button>
                </template>
              </el-popconfirm>
            </template>
          </el-table-column>
        </el-table>
        <el-pagination
          v-model:current-page="chunkPage"
          :page-size="chunkSize"
          :total="chunkTotal"
          layout="prev, pager, next"
          class="pager"
          @current-change="loadChunks"
        />
      </el-tab-pane>

      <!-- ============ Tab3 检索调试台 ============ -->
      <el-tab-pane label="检索调试台" name="debug">
        <div class="debug-bar">
          <el-input
            v-model="debugQuestion"
            placeholder="输入测试问题,查看混合检索各阶段表现"
            clearable
            class="chunk-search"
            @keyup.enter="runDebug"
          />
          <el-button type="primary" :loading="debugLoading" @click="runDebug">开始检索</el-button>
        </div>

        <template v-if="debugResult">
          <el-alert
            v-if="debugResult.refused"
            title="判定:拒答(重排分数低于阈值,回答将明确告知未找到)"
            type="warning"
            :closable="false"
            class="debug-alert"
          />
          <el-alert
            v-else
            title="判定:正常回答(通过拒答阈值)"
            type="success"
            :closable="false"
            class="debug-alert"
          />
          <div class="threshold-line">当前拒答阈值:{{ debugResult.threshold }}</div>

          <el-collapse>
            <el-collapse-item
              title="① 向量路召回(dense 语义检索)"
              :name="'vector'"
            >
              <HitList :hits="debugResult.vector_hits" />
            </el-collapse-item>
            <el-collapse-item title="② 关键词路召回(FTS5 全文检索)" name="keyword">
              <HitList :hits="debugResult.keyword_hits" />
            </el-collapse-item>
            <el-collapse-item title="③ RRF 融合(双路排序融合取 Top10)" name="fused">
              <HitList :hits="debugResult.fused_hits" />
            </el-collapse-item>
            <el-collapse-item title="④ 交叉编码重排(最终进入大模型的引用片段)" name="rerank">
              <HitList :hits="debugResult.reranked_hits" highlight />
            </el-collapse-item>
          </el-collapse>
        </template>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup lang="ts">
import { onMounted, onBeforeUnmount, ref, defineComponent, h } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  ArrowLeft,
  Delete,
  Refresh,
  Search,
  UploadFilled,
} from '@element-plus/icons-vue'
import { chunkApi, debugApi, docApi, kbApi } from '../../api/kb'
import type {
  ChunkItem,
  DebugHit,
  DebugResult,
  DocumentItem,
  KbInfo,
} from '../../api/kb'

// 阶段命中列表小组件(局部注册,保持页面单文件可读)
const HitList = defineComponent({
  props: { hits: { type: Array as () => DebugHit[], default: () => [] }, highlight: Boolean },
  setup(props) {
    return () =>
      props.hits.length
        ? h(
            'div',
            props.hits.map((hit, i) =>
              h(
                'div',
                { class: 'hit-item' },
                [
                  h('span', { class: 'hit-rank' }, String(i + 1)),
                  h('span', { class: 'hit-score' }, hit.score.toFixed(4)),
                  h('span', { class: 'hit-text' }, hit.text),
                ],
              ),
            ),
          )
        : h('div', { class: 'hit-empty' }, '该阶段无命中')
  },
})

const route = useRoute()
const router = useRouter()
const kbId = Number(route.params.id)

const kb = ref<KbInfo | null>(null)
const tab = ref('docs')

// ---- 文档 ----
const docs = ref<DocumentItem[]>([])
const docsLoading = ref(false)
const replaceMode = ref(false)
let pollTimer: ReturnType<typeof setInterval> | null = null

// ---- 分块 ----
const chunks = ref<ChunkItem[]>([])
const chunksLoading = ref(false)
const chunkQuery = ref('')
const chunkPage = ref(1)
const chunkSize = 20
const chunkTotal = ref(0)

// ---- 调试 ----
const debugQuestion = ref('')
const debugLoading = ref(false)
const debugResult = ref<DebugResult | null>(null)

function fmtSize(bytes: number) {
  if (bytes < 1024) return `${bytes}B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)}KB`
  return `${(bytes / 1024 / 1024).toFixed(1)}MB`
}

function docName(docId: number) {
  return docs.value.find((d) => d.id === docId)?.filename || `文档#${docId}`
}

async function loadKb() {
  const { data } = await kbApi.get(kbId)
  kb.value = data
}

async function loadDocs() {
  docsLoading.value = true
  try {
    const { data } = await docApi.list(kbId)
    docs.value = data
    // 存在进行中的解析任务 → 轮询进度
    const running = data.some((d) => d.parse_status === 'pending' || d.parse_status === 'parsing')
    if (running) startPolling()
    else stopPolling()
  } finally {
    docsLoading.value = false
  }
}

function startPolling() {
  if (pollTimer) return
  pollTimer = setInterval(loadDocs, 2000)
}
function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

async function onFilesChange(file: { raw?: File }) {
  if (!file.raw) return
  try {
    await docApi.upload(kbId, file.raw, replaceMode.value)
    ElMessage.success(`已上传并加入解析队列`)
  } catch (e: any) {
    // 409 已存在 → 提示是否覆盖重传
    if (e.response?.status === 409 && !replaceMode.value) {
      // eslint-disable-next-line no-alert
      if (window.confirm('该文件已上传过。点击"确定"将覆盖旧版本重新解析?')) {
        try {
          await docApi.upload(kbId, file.raw, true)
          ElMessage.success('已覆盖重传')
        } catch {
          /* http 层已提示 */
        }
      }
    }
  }
  loadDocs()
  loadKb()
}

async function onReparse(row: DocumentItem) {
  await docApi.reparse(row.id)
  ElMessage.success('已重新入队')
  loadDocs()
}

async function onDeleteDoc(row: DocumentItem) {
  await docApi.remove(row.id)
  ElMessage.success('已删除')
  loadDocs()
  loadKb()
}

async function loadChunks(page = 1) {
  chunkPage.value = page
  chunksLoading.value = true
  try {
    const { data } = await chunkApi.list(kbId, {
      page,
      size: chunkSize,
      q: chunkQuery.value || undefined,
    })
    chunks.value = data.items
    chunkTotal.value = data.total
  } finally {
    chunksLoading.value = false
  }
}

async function onDeleteChunk(row: ChunkItem) {
  await chunkApi.remove(row.id)
  ElMessage.success('已删除')
  loadChunks(chunkPage.value)
  loadKb()
}

async function runDebug() {
  if (!debugQuestion.value.trim()) return
  debugLoading.value = true
  try {
    const { data } = await debugApi.search({
      question: debugQuestion.value.trim(),
      kb_id: kbId,
    })
    debugResult.value = data
  } finally {
    debugLoading.value = false
  }
}

onMounted(() => {
  loadKb()
  loadDocs()
  loadChunks(1)
})
onBeforeUnmount(stopPolling)
</script>

<style scoped>
.detail-page {
  height: 100%;
  overflow-y: auto;
  padding: 16px 24px 40px;
  background: #fff;
}
.page-head {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 4px;
}
.page-head h2 {
  margin: 0;
}
.page-head .stat {
  color: #909399;
  font-size: 13px;
}
.tabs {
  margin-top: 6px;
}
.upload-bar {
  margin-bottom: 16px;
}
.upload-tip {
  padding: 18px 0;
  text-align: center;
  color: #909399;
}
.replace-cb {
  margin-top: 8px;
}
.type-tag {
  margin-left: 8px;
}
.mini-progress {
  width: 130px;
  margin-top: 4px;
}
.err-tip {
  color: #f56c6c;
  font-size: 12px;
  margin-top: 2px;
  max-width: 200px;
  word-break: break-all;
}
.chunk-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
}
.chunk-search {
  max-width: 420px;
}
.chunk-total {
  color: #909399;
  font-size: 13px;
  margin-left: 6px;
}
.chunk-text {
  max-height: 68px;
  overflow: hidden;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  font-size: 13px;
  line-height: 1.5;
}
.pager {
  margin-top: 14px;
  justify-content: flex-end;
}
.debug-bar {
  display: flex;
  gap: 10px;
  margin-bottom: 14px;
}
.debug-alert {
  margin-bottom: 8px;
}
.threshold-line {
  color: #909399;
  font-size: 12px;
  margin-bottom: 10px;
}
/* 命中列表样式(hit-item 由 JSX 生成,需全局可命中,见下) */
:deep(.hit-item) {
  display: flex;
  gap: 10px;
  padding: 8px 6px;
  border-bottom: 1px dashed #ebeef5;
  font-size: 13px;
  align-items: baseline;
}
:deep(.hit-rank) {
  color: #909399;
  min-width: 18px;
  text-align: right;
}
:deep(.hit-score) {
  color: #e6a23c;
  font-family: monospace;
  min-width: 64px;
}
:deep(.hit-text) {
  flex: 1;
  color: #303133;
}
:deep(.hit-empty) {
  color: #c0c4cc;
  font-size: 13px;
  padding: 6px;
}
</style>
