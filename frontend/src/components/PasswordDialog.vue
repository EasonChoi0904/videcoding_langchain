<template>
  <el-dialog
    :model-value="modelValue"
    :title="t('common.changePassword')"
    width="420px"
    :close-on-click-modal="false"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <el-form :model="form" label-width="90px" @submit.prevent="onSubmit">
      <el-form-item :label="t('password.old')">
        <el-input v-model="form.old" type="password" show-password />
      </el-form-item>
      <el-form-item :label="t('password.news')">
        <el-input v-model="form.news" type="password" show-password />
      </el-form-item>
      <el-form-item :label="t('password.confirm')">
        <el-input v-model="form.confirm" type="password" show-password />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="emit('update:modelValue', false)">{{ t('common.cancel') }}</el-button>
      <el-button type="primary" :loading="loading" @click="onSubmit">
        {{ t('password.submit') }}
      </el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { useI18n } from 'vue-i18n'
import { changePassword } from '../api/auth'

const props = defineProps<{ modelValue: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [boolean]; changed: [] }>()

const { t } = useI18n()
const form = reactive({ old: '', news: '', confirm: '' })
const loading = ref(false)

async function onSubmit() {
  if (!form.old || !form.news) {
    ElMessage.warning(t('password.old') + ' / ' + t('password.news'))
    return
  }
  if (form.news !== form.confirm) {
    ElMessage.warning(t('register.pwdNotMatch'))
    return
  }
  loading.value = true
  try {
    await changePassword(form.old, form.news)
    emit('changed')
    ElMessage.success(t('common.success'))
    emit('update:modelValue', false)
  } finally {
    loading.value = false
  }
}
</script>
