import { createI18n } from 'vue-i18n'
import zh from './zh'
import en from './en'

/**
 * 前端 UI 国际化(zh/en)。注意:这与"会话回答语言"是两个独立概念:
 * UI 语言是全局显示偏好;会话语言控制 AI 用哪种语言回答,见会话设置。
 */
export const i18n = createI18n({
  legacy: false,
  locale: localStorage.getItem('rag_ui_lang') || 'zh',
  fallbackLocale: 'zh',
  messages: { zh, en },
})

export function setUiLang(lang: 'zh' | 'en') {
  i18n.global.locale.value = lang
  localStorage.setItem('rag_ui_lang', lang)
  // Element Plus 组件语言由 App.vue 中的 el-config-provider 响应式跟随
}
