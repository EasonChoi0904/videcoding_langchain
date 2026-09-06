<template>
  <div class="auth-page">
    <div class="auth-card">
      <div class="brand">
        <el-icon :size="34" color="#409eff"><ChatDotRound /></el-icon>
        <h1>{{ t('common.appName') }}</h1>
        <p>{{ t('login.subtitle') }}</p>
      </div>

      <el-form :model="form" size="large" @submit.prevent="onSubmit">
        <el-form-item>
          <el-input
            v-model="form.username"
            :placeholder="t('login.username')"
            :prefix-icon="User"
            autocomplete="username"
            clearable
          />
        </el-form-item>
        <el-form-item>
          <el-input
            v-model="form.password"
            type="password"
            show-password
            :placeholder="t('login.password')"
            :prefix-icon="Lock"
            autocomplete="current-password"
            @keyup.enter="onSubmit"
          />
        </el-form-item>
        <el-button
          type="primary"
          size="large"
          class="submit-btn"
          :loading="loading"
          @click="onSubmit"
        >
          {{ t('login.submit') }}
        </el-button>
      </el-form>

      <div class="foot">
        <router-link to="/register">{{ t('login.toRegister') }}</router-link>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { User, Lock } from '@element-plus/icons-vue'
import { useI18n } from 'vue-i18n'
import { login, getMe } from '../api/auth'
import { useAuthStore } from '../stores/auth'
import { useChatStore } from '../stores/chat'

const { t } = useI18n()
const router = useRouter()
const route = useRoute()
const auth = useAuthStore()

const form = reactive({ username: '', password: '' })
const loading = ref(false)

async function onSubmit() {
  if (!form.username || !form.password) {
    ElMessage.warning(t('login.username') + ' / ' + t('login.password'))
    return
  }
  loading.value = true
  try {
    const { data } = await login(form.username, form.password)
    // 关键顺序:先保存令牌,后续请求(如 getMe)才会携带 Authorization
    auth.updateTokens(data)
    // 清掉上一个账号在本页面内存里的会话残留,避免串号显示
    useChatStore().clearAll()
    // 拉取完整用户信息(角色决定菜单可见性)
    const me = await getMe()
    auth.saveSession(data, me.data)
    ElMessage.success(t('login.success'))
    router.push((route.query.redirect as string) || '/chat')
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
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
.brand p {
  font-size: 13px;
  color: #909399;
  margin: 0;
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
