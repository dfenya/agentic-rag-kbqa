<script setup lang="ts">
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import hljs from 'highlight.js'

const props = defineProps<{ content: string }>()

// 配置 marked 渲染器以支持语法高亮（marked v16+ 已移除 `highlight` 选项）
const renderer = new marked.Renderer()
renderer.code = function({ text, lang }: { text: string; lang?: string }) {
  if (lang && hljs.getLanguage(lang)) {
    const highlighted = hljs.highlight(text, { language: lang }).value
    return `<pre><code class="hljs language-${lang}">${highlighted}</code></pre>`
  }
  const auto = hljs.highlightAuto(text).value
  return `<pre><code class="hljs">${auto}</code></pre>`
}

marked.setOptions({
  breaks: true,
  gfm: true,
  renderer,
})

const rendered = computed(() => {
  if (!props.content) return ''
  const raw = marked.parse(props.content) as string
  return DOMPurify.sanitize(raw, { ADD_ATTR: ['target'] })
})
</script>

<template>
  <div class="markdown-body" v-html="rendered" />
</template>
