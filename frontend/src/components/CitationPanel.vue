<template>
  <!-- 引用溯源面板:展示本次回答引用的知识库片段(来源文件/片段/相关度) -->
  <div v-if="sources && sources.length" class="citation-panel">
    <div class="cp-head" @click="expanded = !expanded">
      <span class="cp-title">
        <el-icon :size="13"><Paperclip /></el-icon>
        参考了 {{ sources.length }} 条知识库片段
      </span>
      <el-icon class="chevron" :class="{ open: expanded }"><ArrowDown /></el-icon>
    </div>
    <el-collapse-transition>
      <div v-show="expanded" class="cp-body">
        <div
          v-for="src in sources"
          :key="src.n"
          :id="`cite-card-${src.n}`"
          class="cite-card"
          :class="{ flash: flashN === src.n }"
          @click="flashN = src.n"
        >
          <div class="cite-meta">
            <span class="cite-n">[{{ src.n }}]</span>
            <span class="cite-file">
              <el-icon :size="12"><Document /></el-icon>
              {{ src.doc_name || '未知来源' }}
            </span>
            <el-tag v-if="src.kb_name" size="small" type="info" class="kb-tag">{{ src.kb_name }}</el-tag>
            <span v-if="src.location" class="cite-loc">{{ src.location }}</span>
            <span class="cite-score">{{ src.score.toFixed(2) }}</span>
          </div>
          <div class="cite-text">{{ src.text }}</div>
        </div>
      </div>
    </el-collapse-transition>
  </div>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { Paperclip, ArrowDown, Document } from '@element-plus/icons-vue'
import type { Citation } from '../api/chat'

const props = defineProps<{ sources: Citation[] | null; highlight?: number | null }>()
const expanded = ref(true)
const flashN = ref<number | null>(null)

// 点击正文上标 [n] → 定位到对应片段卡片
watch(
  () => props.highlight,
  (n) => {
    if (!n) return
    flashN.value = n
    setTimeout(() => {
      const el = document.getElementById(`cite-card-${n}`)
      el?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
    }, 60)
    setTimeout(() => (flashN.value = null), 1600)
  },
)
</script>

<style scoped>
.citation-panel {
  margin-top: 10px;
  border: 1px solid #e4e9f2;
  border-radius: 8px;
  background: #fafbfd;
}
.cp-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  cursor: pointer;
  user-select: none;
}
.cp-title {
  display: flex;
  align-items: center;
  gap: 5px;
  color: #606266;
  font-size: 12.5px;
}
.chevron {
  transition: transform 0.2s;
  color: #909399;
}
.chevron.open {
  transform: rotate(180deg);
}
.cp-body {
  padding: 0 12px 10px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-height: 320px;
  overflow-y: auto;
}
.cite-card {
  border: 1px solid #eef1f6;
  background: #fff;
  border-radius: 6px;
  padding: 8px 10px;
  transition: box-shadow 0.25s;
}
.cite-card.flash {
  box-shadow: 0 0 0 2px #409eff66;
}
.cite-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  font-size: 12px;
  color: #606266;
  margin-bottom: 4px;
}
.cite-n {
  color: #409eff;
  font-weight: 700;
}
.cite-file {
  display: flex;
  align-items: center;
  gap: 3px;
  color: #303133;
  font-weight: 500;
}
.cite-loc {
  color: #909399;
}
.cite-score {
  margin-left: auto;
  color: #e6a23c;
  font-family: monospace;
  background: #fdf6ec;
  border-radius: 8px;
  padding: 0 7px;
  font-size: 11px;
}
.cite-text {
  font-size: 13px;
  color: #4b5563;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
</style>
