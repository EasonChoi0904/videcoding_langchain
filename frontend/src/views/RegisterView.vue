<template>
  <div class="auth-page">
    <div class="auth-card">
      <div class="brand">
        <el-icon :size="34" color="#67c23a"><UserFilled /></el-icon>
        <h1>{{ t('register.title') }}</h1>
      </div>

      <el-form :model="form" size="large">
        <el-form-item>
          <el-input
            v-model="form.username"
            :placeholder="t('register.username')"
            clearable
            maxlength="32"
          />
        </el-form-item>
        <el-form-item>
          <el-input
            v-model="form.password"
            type="password"
            show-password
            :placeholder="t('register.password')"
          />
        </el-form-item>
        <el-form-item>
          <el-input
            v-model="form.confirm"
            type="password"
            show-password
            :placeholder="t('register.confirmPassword')"
            @keyup.enter="onSubmit"
          />
        </el-form-item>
        <el-button
          type="success"
          size="large"
          class="submit-btn"
          :loading="loading"
          @click="onSubmit"
        >
          {{ t('register.submit') }}
        </el-button>
      </el-form>

      <div class="foot">
        <router-link to="/login">{{ t('register.toLogin') }}</router-link>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { UserFilled } from '@element-plus/icons-vue'
import { useI18n } from 'vue-i18n'
import { register } from '../api/auth'

const { t } = useI18n()
const router = useRouter()

const form = reactive({ username: '', password: '', confirm: '' })
const loading = ref(false)

async function onSubmit() {
  if (form.password !== form.confirm) {
    ElMessage.warning(t('register.pwdNotMatch'))
    return
  }
  loading.value = true
  try {
    await register(form.username, form.password)
    ElMessage.success(t('common.success'))
    router.push('/login')
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
/* 与登录页共用一套样式 */
.auth-page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #e8f3ff 0%, #f5f8ff 50%, #eef3fb 100%);
}
.auth-card {
  width: 400px;
  background: #fff;
  border-radius: 12px;
  padding: 36px 36px 24px;
  box-shadow: 0 8px 30px rgba(30, 60, 140, 0.12);
}
.brand {
  text-align: center;
  margin-bottom: 24px;
}
.brand h1 {
  font-size: 20px;
  margin: 10px 0 4px;
  color: #1f2d3d;
}
.submit-btn {
  width: 100%;
}
.foot {
  text-align: center;
  margin-top: 14px;
}
.foot a {
  color: #409eff;
  text-decoration: none;
  font-size: 14px;
}
</style>
