<template>
  <div class="settings-page">
    <h2>系统设置</h2>
    <p class="sub">检索与问答参数实时生效,无需重启服务。修改影响所有用户的问答行为,请谨慎调整。</p>

    <el-card v-loading="loading" class="form-card" shadow="never">
      <el-form label-position="top">
        <el-form-item v-for="item in items" :key="item.key" :label="item.label">
          <template v-if="item.type === 'bool'">
            <el-switch
              :model-value="item.value === 'true'"
              @change="(v: boolean | string | number) => (item.value = v ? 'true' : 'false')"
            />
          </template>
          <el-input-number
            v-else-if="item.type === 'float'"
            v-model="floatMap[item.key]"
            :step="0.05"
            :min="0"
            :max="1"
            :precision="2"
          />
          <el-input-number
            v-else-if="item.type === 'int'"
            v-model="intMap[item.key]"
            :step="1"
            :min="1"
            :max="100"
          />
          <el-input
            v-else
            v-model="item.value"
            type="textarea"
            :rows="4"
            :placeholder="`${item.key} 的默认配置`"
          />
          <div class="tip">{{ item.description || `配置键:${item.key}` }}</div>
        </el-form-item>
      </el-form>
      <el-button type="primary" :loading="saving" @click="save">保存设置</el-button>
      <el-button @click="load">重置表单</el-button>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { settingApi, type SettingItem } from '../api/admin'

const items = ref<SettingItem[]>([])
const floatMap = ref<Record<string, number>>({})
const intMap = ref<Record<string, number>>({})
const loading = ref(false)
const saving = ref(false)

async function load() {
  loading.value = true
  try {
    const { data } = await settingApi.list()
    items.value = data
    floatMap.value = {}
    intMap.value = {}
    for (const it of data) {
      if (it.type === 'float') floatMap.value[it.key] = Number(it.value)
      if (it.type === 'int') intMap.value[it.key] = Number(it.value)
    }
  } finally {
    loading.value = false
  }
}

async function save() {
  const payload = items.value.map((it) => {
    let value = it.value
    if (it.type === 'float') value = String(floatMap.value[it.key])
    if (it.type === 'int') value = String(intMap.value[it.key])
    return { key: it.key, value }
  })
  saving.value = true
  try {
    await settingApi.save(payload)
    ElMessage.success('设置已保存,即时生效')
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.settings-page {
  height: 100%;
  overflow-y: auto;
  padding: 20px 24px;
}
.settings-page h2 {
  margin: 0 0 4px;
  color: #1f2d3d;
}
.sub {
  color: #909399;
  font-size: 13px;
  margin: 0 0 16px;
}
.form-card {
  max-width: 720px;
}
.tip {
  color: #b0b7c3;
  font-size: 12px;
  margin-top: 4px;
}
</style>
