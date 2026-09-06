import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import en from 'element-plus/es/locale/lang/en'
import 'element-plus/dist/index.css'
import * as Icons from '@element-plus/icons-vue'

import App from './App.vue'
import router from './router'
import { i18n } from './i18n'

const app = createApp(App)

// Element Plus 组件库(全局注册,方便毕设快速迭代)
app.use(createPinia())
app.use(router)
app.use(i18n)
app.use(ElementPlus, { locale: i18n.global.locale.value === 'en' ? en : zhCn })

// 图标全量注册:模板中可直接 <el-icon><ChatDotRound /></el-icon>
for (const [name, comp] of Object.entries(Icons)) {
  app.component(name, comp)
}

app.mount('#app')
