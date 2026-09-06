import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { LoginResult, UserInfo } from '../api/auth'

// 令牌持久化键:刷新页面 / 重新登录都能恢复登录态
const ACCESS_KEY = 'rag_access_token'
const REFRESH_KEY = 'rag_refresh_token'
const USER_KEY = 'rag_user'

export const useAuthStore = defineStore('auth', () => {
  const accessToken = ref(localStorage.getItem(ACCESS_KEY) || '')
  const refreshToken = ref(localStorage.getItem(REFRESH_KEY) || '')
  const user = ref<UserInfo | null>(JSON.parse(localStorage.getItem(USER_KEY) || 'null'))

  const isLoggedIn = computed(() => !!accessToken.value)
  const isAdmin = computed(() => user.value?.role === 'admin')

  /** 保存令牌对与用户信息(登录/刷新成功后调用) */
  function saveSession(result: LoginResult, userInfo: UserInfo) {
    accessToken.value = result.access_token
    refreshToken.value = result.refresh_token
    user.value = userInfo
    localStorage.setItem(ACCESS_KEY, result.access_token)
    localStorage.setItem(REFRESH_KEY, result.refresh_token)
    localStorage.setItem(USER_KEY, JSON.stringify(userInfo))
  }

  /** 仅更新令牌(静默刷新场景,用户信息不动) */
  function updateTokens(result: LoginResult) {
    accessToken.value = result.access_token
    refreshToken.value = result.refresh_token
    localStorage.setItem(ACCESS_KEY, result.access_token)
    localStorage.setItem(REFRESH_KEY, result.refresh_token)
  }

  /** 登出:清空本地态并跳转登录页 */
  function clearSession() {
    accessToken.value = ''
    refreshToken.value = ''
    user.value = null
    localStorage.removeItem(ACCESS_KEY)
    localStorage.removeItem(REFRESH_KEY)
    localStorage.removeItem(USER_KEY)
  }

  return { accessToken, refreshToken, user, isLoggedIn, isAdmin, saveSession, updateTokens, clearSession }
})
