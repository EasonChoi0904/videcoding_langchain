<template>
  <div class="stats-page" v-loading="loading">
    <!-- 规模卡片 -->
    <div class="stat-grid">
      <div v-for="card in totalCards" :key="card.key" class="stat-card">
        <div class="num">{{ data?.totals[card.key] }}</div>
        <div class="label">{{ card.label }}</div>
      </div>
    </div>

    <div class="panels">
      <!-- 近 7 天问答趋势 -->
      <el-card class="panel" shadow="never">
        <template #header>近 7 天问答量</template>
        <div class="bar-chart">
          <div v-for="d in data?.trend_7d" :key="d.date" class="bar-col">
            <div class="bar-val">{{ d.count }}</div>
            <div class="bar-track">
              <div
                class="bar-fill"
                :style="{ height: barHeight(d.count) }"
                :title="`${d.date}: ${d.count} 条`"
              />
            </div>
            <div class="bar-date">{{ d.date.slice(5) }}</div>
          </div>
        </div>
      </el-card>

      <!-- 运行表现 -->
      <el-card class="panel" shadow="never">
        <template #header>运行表现</template>
        <div class="kv">
          <div class="kv-item">
            <span>平均回答耗时</span>
            <b>{{ data?.avg_latency_ms != null ? `${data.avg_latency_ms} ms` : '—' }}</b>
          </div>
          <div class="kv-item">
            <span>用户反馈 👍 / 👎</span>
            <b>{{ data?.feedback.total || 0 }} 条</b>
          </div>
          <div class="likes-line">
            <el-progress
              :percentage="feedbackRate"
              :stroke-width="12"
              color="#67c23a"
              :format="() => `👍 ${data?.feedback.likes || 0}`"
            />
            <span class="dislike-count">👎 {{ data?.feedback.dislikes || 0 }}</span>
          </div>
          <el-divider />
          <div class="model-list">
            <div v-for="m in data?.model_usage" :key="m.model" class="model-line">
              <span>{{ m.model }}</span>
              <b>{{ m.count }}</b>
            </div>
          </div>
        </div>
      </el-card>

      <!-- 知识库规模分布 -->
      <el-card class="panel wide" shadow="never">
        <template #header>知识库分块分布</template>
        <div v-if="data?.kb_dist.length" class="kb-bar">
          <div v-for="kb in data.kb_dist" :key="kb.name" class="kb-line">
            <span class="kb-name" :title="kb.name">{{ kb.name }}</span>
            <el-progress
              :percentage="kbPercent(kb.chunks)"
              :stroke-width="14"
              :format="() => String(kb.chunks)"
            />
          </div>
        </div>
        <el-empty v-else description="暂无知识库数据" :image-size="60" />
      </el-card>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { statsApi, type StatsOverview } from '../api/admin'

const data = ref<StatsOverview | null>(null)
const loading = ref(false)

const totalCards = [
  { key: 'users', label: '注册用户' },
  { key: 'kbs', label: '知识库' },
  { key: 'docs', label: '上传文档' },
  { key: 'chunks', label: '分块总数' },
  { key: 'conversations', label: '用户会话' },
  { key: 'messages', label: '累计问答' },
] as const

const maxTrend = computed(() => Math.max(...(data.value?.trend_7d.map((d) => d.count) || [1]), 1))
function barHeight(n: number) {
  return `${Math.max((n / maxTrend.value) * 100, 2)}%`
}
const feedbackRate = computed(() => {
  const f = data.value?.feedback
  if (!f?.total) return 0
  return Math.round((f.likes / f.total) * 100)
})
function kbPercent(n: number) {
  const max = Math.max(...(data.value?.kb_dist.map((k) => k.chunks) || [1]), 1)
  return Math.round((n / max) * 100)
}

onMounted(async () => {
  loading.value = true
  try {
    const { data: d } = await statsApi.overview()
    data.value = d
  } finally {
    loading.value = false
  }
})
</script>

<style scoped>
.stats-page {
  height: 100%;
  overflow-y: auto;
  padding: 20px 24px;
}
.stat-grid {
  display: grid;
  grid-template-columns: repeat(6, 1fr);
  gap: 14px;
  margin-bottom: 18px;
}
.stat-card {
  background: #fff;
  border-radius: 10px;
  padding: 16px 10px;
  text-align: center;
  box-shadow: 0 1px 4px rgba(0, 21, 41, 0.05);
}
.stat-card .num {
  font-size: 26px;
  font-weight: 700;
  color: #409eff;
}
.stat-card .label {
  color: #909399;
  font-size: 12.5px;
  margin-top: 4px;
}
.panels {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px;
}
.panel.wide {
  grid-column: 1 / -1;
}
.bar-chart {
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  height: 190px;
  gap: 6px;
  padding: 6px 4px 0;
}
.bar-col {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  height: 100%;
}
.bar-val {
  font-size: 12px;
  color: #606266;
  margin-bottom: 2px;
}
.bar-track {
  flex: 1;
  width: 70%;
  max-width: 46px;
  display: flex;
  align-items: flex-end;
}
.bar-fill {
  width: 100%;
  background: linear-gradient(180deg, #79bbff, #409eff);
  border-radius: 4px 4px 0 0;
  transition: height 0.4s;
  min-height: 3px;
}
.bar-date {
  font-size: 11px;
  color: #909399;
  margin-top: 4px;
}
.kv-item {
  display: flex;
  justify-content: space-between;
  margin-bottom: 10px;
  color: #606266;
}
.kv-item b {
  color: #1f2d3d;
}
.likes-line {
  display: flex;
  align-items: center;
  gap: 10px;
}
.dislike-count {
  font-size: 12px;
  color: #909399;
  white-space: nowrap;
}
.model-line {
  display: flex;
  justify-content: space-between;
  font-size: 13px;
  color: #606266;
  padding: 3px 0;
}
.model-line b {
  color: #1f2d3d;
}
.kb-line {
  display: flex;
  align-items: center;
  gap: 12px;
  margin: 8px 0;
}
.kb-name {
  width: 150px;
  font-size: 13px;
  color: #303133;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.kb-line .el-progress {
  flex: 1;
}
@media (max-width: 1200px) {
  .stat-grid {
    grid-template-columns: repeat(3, 1fr);
  }
}
</style>
