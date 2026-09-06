import axios, { AxiosError } from 'axios'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '../stores/auth'
import router from '../router'

// 全局 axios 实例:baseURL=/api(开发环境由 Vite 代理到后端 8000)
const http = axios.create({ baseURL: '/api', timeout: 120000 })

// 请求拦截:自动携带访问令牌
http.interceptors.request.use((config) => {
  const auth = useAuthStore()
  if (auth.accessToken) {
    config.headers.Authorization = `Bearer ${auth.accessToken}`
  }
  return config
})

// 响应拦截:统一错误提示 + 401 静默刷新后重试一次
http.interceptors.response.use(
  (resp) => resp,
  async (error: AxiosError) => {
    const auth = useAuthStore()
    const original: any = error.config

    // 访问令牌过期且尚未重试过 → 尝试用刷新令牌换新
    if (error.response?.status === 401 && !original._retried && auth.refreshToken) {
      original._retried = true
      try {
        const { data } = await axios.post('/api/auth/refresh', {
          refresh_token: auth.refreshToken,
        })
        auth.updateTokens(data)
        original.headers.Authorization = `Bearer ${data.access_token}`
        return http(original)
      } catch {
        // 刷新失败(令牌被吊销/过期)→ 清空登录态回登录页
        auth.clearSession()
        router.push('/login')
        return Promise.reject(error)
      }
    }

    // 业务错误提示(不提示无意义的网络取消)
    const detail: any = (error.response?.data as any)?.detail
    const msg = typeof detail === 'string' ? detail : error.message || '请求失败'
    if (msg !== 'canceled' && !axios.isCancel(error)) {
      ElMessage.error(msg)
    }
    return Promise.reject(error)
  },
)

export default http
