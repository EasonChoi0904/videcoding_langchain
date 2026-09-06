<template>
  <!-- el-config-provider:让 Element Plus 组件文案跟随 UI 语言实时切换 -->
  <el-config-provider :locale="elementLocale">
    <router-view />
  </el-config-provider>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import en from 'element-plus/es/locale/lang/en'

const { locale } = useI18n()
const elementLocale = computed(() => (locale.value === 'en' ? en : zhCn))
</script>
