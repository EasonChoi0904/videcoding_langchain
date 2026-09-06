<template>
  <el-container class="layout">
    <!-- 顶部栏:品牌 + 导航 + 用户区 -->
    <el-header class="header">
      <div class="left">
        <div class="logo" @click="router.push('/chat')">
          <el-icon :size="22" color="#409eff"><ChatDotRound /></el-icon>
          <span class="title">{{ t('common.appName') }}</span>
        </div>

        <el-menu
          mode="horizontal"
          :default-active="route.path"
          :ellipsis="false"
          class="nav-menu"
          router
        >
          <el-menu-item index="/chat">{{ t('nav.chat') }}</el-menu-item>
          <!-- 以下导航仅管理员可见(与后端 RBAC 双重控制) -->
          <template v-if="auth.isAdmin">
            <el-menu-item index="/kb">{{ t('nav.kbManage') }}</el-menu-item>
            <el-menu-item index="/stats">{{ t('nav.stats') }}</el-menu-item>
            <el-menu-item index="/settings">{{ t('nav.settings') }}</el-menu-item>
          </template>
        </el-menu>
      </div>

      <div class="right">
        <el-select
          :model-value="uiLang"
          class="lang-select"
          @change="onLangChange"
        >
          <el-option label="中文" value="zh" />
          <el-option label="English" value="en" />
        </el-select>

        <el-dropdown trigger="click" @command="onUserCommand">
          <span class="user-chip">
            <el-avatar :size="26" class="avatar">{{ avatarText }}</el-avatar>
            <span class="username">{{ auth.user?.username }}</span>
            <el-tag v-if="auth.isAdmin" size="small" type="danger">{{ t('common.admin') }}</el-tag>
          </span>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="password">
                <el-icon><Key /></el-icon>{{ t('common.changePassword') }}
              </el-dropdown-item>
              <el-dropdown-item divided command="logout">
                <el-icon><SwitchButton /></el-icon>{{ t('common.logout') }}
              </el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
    </el-header>

    <!-- 内容区(路由出口) -->
    <el-main class="main">
      <router-view />
    </el-main>

    <!-- 修改密码弹窗 -->
    <PasswordDialog v-model="showPassword" @changed="onPasswordChanged" />
  </el-container>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import { Key, SwitchButton } from '@element-plus/icons-vue'
import { useAuthStore } from '../stores/auth'
import { useChatStore } from '../stores/chat'
import { logout } from '../api/auth'
import PasswordDialog from '../components/PasswordDialog.vue'

const { t, locale } = useI18n()
const router = useRouter()
const route = useRoute()
const auth = useAuthStore()

const uiLang = computed(() => String(locale.value))
const avatarText = computed(() => auth.user?.username?.slice(0, 1).toUpperCase() || 'U')
const showPassword = ref(false)

function onLangChange(lang: string) {
  locale.value = lang
  localStorage.setItem('rag_ui_lang', lang)
}

async function onUserCommand(cmd: string) {
  if (cmd === 'password') {
    showPassword.value = true
  } else if (cmd === 'logout') {
    // 通知后端吊销刷新令牌,再清本地态与内存中的会话残留
    try {
      await logout(auth.refreshToken)
    } finally {
      useChatStore().clearAll()
      auth.clearSession()
      router.push('/login')
    }
  }
}

function onPasswordChanged() {
  ElMessage.success(t('common.success'))
  useChatStore().clearAll()
  auth.clearSession()
  router.push('/login')
}
</script>

<style scoped>
.layout {
  height: 100vh;
}
.header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: #fff;
  border-bottom: 1px solid #e8eaf0;
  padding: 0 20px;
  box-shadow: 0 1px 4px rgba(0, 21, 41, 0.06);
  z-index: 10;
}
.left {
  display: flex;
  align-items: center;
  gap: 8px;
}
.logo {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  margin-right: 16px;
}
.logo .title {
  font-weight: 600;
  font-size: 16px;
  color: #1f2d3d;
  white-space: nowrap;
}
.nav-menu {
  border-bottom: none;
}
.right {
  display: flex;
  align-items: center;
  gap: 14px;
}
.lang-select {
  width: 108px;
}
.user-chip {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  outline: none;
}
.avatar {
  background: #409eff;
  color: #fff;
  font-weight: 600;
}
.username {
  color: #1f2d3d;
  max-width: 120px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.main {
  padding: 0;
  overflow: hidden;
  background: #f4f6fa;
}
</style>
