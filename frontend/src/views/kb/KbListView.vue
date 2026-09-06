<template>
  <div class="kb-page">
    <!-- 工具栏 -->
    <div class="toolbar">
      <h2>知识库管理</h2>
      <el-button type="primary" :icon="Plus" @click="openDialog()">新建知识库</el-button>
    </div>

    <!-- 知识库卡片列表 -->
    <el-empty v-if="loading && !kbs.length" description="加载中..." />
    <div v-else-if="kbs.length" class="kb-grid">
      <el-card
        v-for="kb in kbs"
        :key="kb.id"
        class="kb-card"
        shadow="hover"
        @click="goDetail(kb)"
      >
        <div class="kb-head">
          <el-icon :size="26" color="#409eff"><Collection /></el-icon>
          <div class="kb-name">
            <div class="name-line">
              <span class="name">{{ kb.name }}</span>
              <el-tag v-if="kb.category" size="small" type="info">{{ kb.category }}</el-tag>
            </div>
            <div class="stats">
              文档 {{ kb.doc_count }} · 分块 {{ kb.chunk_count }}
            </div>
          </div>
        </div>
        <p class="desc">{{ kb.description || '暂无描述' }}</p>
        <div class="kb-actions" @click.stop>
          <el-button size="small" :icon="Edit" @click="openDialog(kb)">编辑</el-button>
          <el-popconfirm
            title="删除知识库将清空其全部文档与向量数据,确定?"
            confirm-button-text="删除"
            @confirm="onDelete(kb)"
          >
            <template #reference>
              <el-button size="small" type="danger" :icon="Delete" plain>删除</el-button>
            </template>
          </el-popconfirm>
        </div>
      </el-card>
    </div>
    <el-empty v-else description="暂无知识库,点击右上角创建" />

    <!-- 新建/编辑弹窗 -->
    <el-dialog
      v-model="dialogVisible"
      :title="editing ? '编辑知识库' : '新建知识库'"
      width="460px"
    >
      <el-form :model="form" label-width="80px">
        <el-form-item label="名称" required>
          <el-input v-model="form.name" maxlength="128" placeholder="如:手机数码商品库" />
        </el-form-item>
        <el-form-item label="类目标签">
          <el-input v-model="form.category" maxlength="64" placeholder="如:3C数码 / 家电 / 服饰" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input
            v-model="form.description"
            type="textarea"
            :rows="3"
            maxlength="500"
            placeholder="这个知识库存放什么内容?"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="onSave">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Plus, Edit, Delete, Collection } from '@element-plus/icons-vue'
import { kbApi, type KbInfo } from '../../api/kb'

const router = useRouter()
const kbs = ref<KbInfo[]>([])
const loading = ref(false)
const saving = ref(false)
const dialogVisible = ref(false)
const editing = ref<KbInfo | null>(null)
const form = reactive({ name: '', category: '', description: '' })

async function load() {
  loading.value = true
  try {
    const { data } = await kbApi.list()
    kbs.value = data
  } finally {
    loading.value = false
  }
}

function openDialog(kb?: KbInfo) {
  editing.value = kb || null
  form.name = kb?.name || ''
  form.category = kb?.category || ''
  form.description = kb?.description || ''
  dialogVisible.value = true
}

async function onSave() {
  if (!form.name.trim()) return ElMessage.warning('请填写知识库名称')
  saving.value = true
  try {
    if (editing.value) {
      await kbApi.update(editing.value.id, { ...form })
    } else {
      await kbApi.create({ ...form })
    }
    ElMessage.success('保存成功')
    dialogVisible.value = false
    load()
  } finally {
    saving.value = false
  }
}

async function onDelete(kb: KbInfo) {
  await kbApi.remove(kb.id)
  ElMessage.success('已删除')
  load()
}

function goDetail(kb: KbInfo) {
  router.push(`/kb/${kb.id}`)
}

onMounted(load)
</script>

<style scoped>
.kb-page {
  height: 100%;
  overflow-y: auto;
  padding: 20px 24px;
}
.toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 18px;
}
.toolbar h2 {
  margin: 0;
  color: #1f2d3d;
}
.kb-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 16px;
}
.kb-card {
  cursor: pointer;
}
.kb-head {
  display: flex;
  gap: 12px;
  align-items: flex-start;
}
.name-line {
  display: flex;
  align-items: center;
  gap: 8px;
}
.kb-name .name {
  font-size: 16px;
  font-weight: 600;
  color: #1f2d3d;
}
.kb-name .stats {
  font-size: 12px;
  color: #909399;
  margin-top: 4px;
}
.desc {
  color: #606266;
  font-size: 13px;
  min-height: 38px;
  margin: 10px 0 6px;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.kb-actions {
  display: flex;
  justify-content: flex-end;
  gap: 4px;
  border-top: 1px solid #f0f2f5;
  padding-top: 10px;
}
</style>
