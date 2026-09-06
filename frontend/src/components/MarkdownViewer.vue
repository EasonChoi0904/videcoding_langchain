<template>
  <!-- Markdown 渲染(安全模式):
       1. markdown-it 关闭 html 内联(LLM 输出按纯文本处理,防 XSS)
       2. 渲染后把正文 [n] 引用标注替换为可点击上标
  -->
  <div
    class="md-body"
    :class="{ streaming }"
    v-html="rendered"
    @click="onClick"
  ></div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import MarkdownIt from 'markdown-it'
import hljs from 'highlight.js'

const props = defineProps<{ content: string; streaming?: boolean }>()
const emit = defineEmits<{ cite: [n: number] }>()

const CITE_TOKEN = '@@CITE@@' // 渲染占位符(纯文本,不会被 markdown 语法吞掉)

const md: MarkdownIt = new MarkdownIt({
  html: false, // 关键:不允许原始 HTML,模型输出按文本转义
  linkify: true,
  breaks: true,
  highlight: (code: string, lang: string): string => {
    if (lang && hljs.getLanguage(lang)) {
      try {
        return `<pre class="hljs"><code>${hljs.highlight(code, { language: lang }).value}</code></pre>`
      } catch {
        /* 回退默认渲染 */
      }
    }
    return `<pre class="hljs"><code>${md.utils.escapeHtml(code)}</code></pre>`
  },
})

const rendered = computed(() => {
  // 1. [n] → 占位 token(避免被 markdown 的链接语法 [x](y) 干扰)
  const cites: number[] = []
  const tokenized = props.content.replace(/\[(\d{1,2})\]/g, (_m, n: string) => {
    cites.push(Number(n))
    return CITE_TOKEN
  })
  // 2. 渲染 markdown(此时占位符是不可被解释的纯文本)
  let html = md.render(tokenized)
  // 3. 占位 → 可点击上标(注入内容仅来自我们自己的受控 token)
  for (const n of cites) {
    html = html.replace(
      CITE_TOKEN,
      `<sup class="cite-tag" data-n="${n}">[${n}]</sup>`,
    )
  }
  return html
})

function onClick(e: MouseEvent) {
  const target = (e.target as HTMLElement).closest('.cite-tag') as HTMLElement | null
  if (target?.dataset.n) {
    emit('cite', Number(target.dataset.n))
  }
}
</script>

<style scoped>
.md-body {
  line-height: 1.7;
  font-size: 14.5px;
  word-break: break-word;
}
.md-body.streaming {
  cursor: text;
}
.md-body :deep(p) {
  margin: 0.4em 0;
}
.md-body :deep(h1),
.md-body :deep(h2),
.md-body :deep(h3) {
  margin: 0.8em 0 0.4em;
  font-size: 1.15em;
}
.md-body :deep(ul),
.md-body :deep(ol) {
  padding-left: 1.4em;
  margin: 0.4em 0;
}
.md-body :deep(pre) {
  background: #f6f8fa;
  border-radius: 6px;
  padding: 10px 12px;
  overflow-x: auto;
}
.md-body :deep(code:not(pre code)) {
  background: #f0f2f5;
  border-radius: 3px;
  padding: 1px 5px;
  font-size: 0.92em;
}
.md-body :deep(table) {
  border-collapse: collapse;
  margin: 8px 0;
}
.md-body :deep(td),
.md-body :deep(th) {
  border: 1px solid #dfe3ea;
  padding: 5px 10px;
}
.cite-tag {
  color: #409eff;
  font-weight: 600;
  cursor: pointer;
  user-select: none;
  margin: 0 1px;
}
.cite-tag:hover {
  background: #e8f3ff;
  border-radius: 3px;
}
</style>
