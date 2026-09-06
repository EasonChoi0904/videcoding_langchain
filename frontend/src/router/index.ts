import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '../stores/auth'

/**
 * 路由与权限守卫:
 * - requiresAuth:必须登录
 * - requiresAdmin:必须管理员(知识库管理相关页面)
 */
const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/login',
      name: 'login',
      component: () => import('../views/LoginView.vue'),
      meta: { guestOnly: true, title: '登录' },
    },
    {
      path: '/register',
      name: 'register',
      component: () => import('../views/RegisterView.vue'),
      meta: { guestOnly: true, title: '注册' },
    },
    {
      path: '/',
      component: () => import('../layouts/MainLayout.vue'),
      children: [
        {
          path: '',
          redirect: '/chat',
        },
        {
          path: 'chat',
          name: 'chat',
          component: () => import('../views/ChatView.vue'),
          meta: { requiresAuth: true, title: '智能问答' },
        },
        {
          path: 'kb',
          name: 'kb',
          component: () => import('../views/kb/KbListView.vue'),
          meta: { requiresAuth: true, requiresAdmin: true, title: '知识库管理' },
        },
        {
          path: 'kb/:id',
          name: 'kb-detail',
          component: () => import('../views/kb/KbDetailView.vue'),
          meta: { requiresAuth: true, requiresAdmin: true, title: '知识库详情' },
        },
        {
          path: 'stats',
          name: 'stats',
          component: () => import('../views/StatsView.vue'),
          meta: { requiresAuth: true, requiresAdmin: true, title: '统计看板' },
        },
        {
          path: 'settings',
          name: 'settings',
          component: () => import('../views/SettingsView.vue'),
          meta: { requiresAuth: true, requiresAdmin: true, title: '系统设置' },
        },
      ],
    },
    { path: '/:pathMatch(.*)*', redirect: '/chat' },
  ],
})

router.beforeEach((to) => {
  const auth = useAuthStore()

  // 已登录用户访问登录/注册页 → 直接进问答页
  if (to.meta.guestOnly && auth.isLoggedIn) {
    return { name: 'chat' }
  }
  // 需要登录
  if (to.meta.requiresAuth && !auth.isLoggedIn) {
    return { name: 'login', query: { redirect: to.fullPath } }
  }
  // 需要管理员
  if (to.meta.requiresAdmin && !auth.isAdmin) {
    return { name: 'chat' }
  }
  return true
})

router.afterEach((to) => {
  document.title = `${to.meta.title || ''} · RAG 知识库问答`
})

export default router
