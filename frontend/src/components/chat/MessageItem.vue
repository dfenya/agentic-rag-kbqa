<script setup lang="ts">
import { computed } from 'vue'
import type { ChatMessage } from '@/stores/chat'
import type { RagFlowStep } from '@/types/api'
import { useChatStore } from '@/stores/chat'
import MarkdownRenderer from './MarkdownRenderer.vue'
import SourceChips from './SourceChips.vue'
import RagFlowCard from './RagFlowCard.vue'
import { BRAND } from '@/config/brand'

const props = defineProps<{ message: ChatMessage; isFirstAssistant?: boolean }>()
const store = useChatStore()

const flowStepsToShow = computed<RagFlowStep[] | null>(() => {
  if (props.message.flowSteps?.length) {
    const hasNonLLM = props.message.flowSteps.some(s => s.stage !== 'llm')
    return hasNonLLM ? props.message.flowSteps : null
  }
  if (props.isFirstAssistant && store.ragFlowSteps.length > 0 && store.isFlowForCurrentConv) {
    const hasNonLLM = store.ragFlowSteps.some(s => s.stage !== 'llm')
    return hasNonLLM ? store.ragFlowSteps : null
  }
  return null
})
</script>

<template>
  <div class="message" :class="`msg-${message.role}`">
    <!-- RAG 流程卡片：基于消息自身的 flowSteps 显示，每轮对话绑定自己的流程 -->
    <RagFlowCard
      v-if="message.role === 'assistant' && flowStepsToShow && flowStepsToShow.length > 0"
      :steps="flowStepsToShow"
    />

    <!-- 用户 -->
    <div v-if="message.role === 'user'" class="msg-row msg-row--user">
      <div class="bubble user-bubble">
        {{ message.content }}
      </div>
      <div class="user-avatar">{{ BRAND.userAvatar }}</div>
    </div>

    <!-- 系统 / 错误 -->
    <div v-else-if="message.role === 'system'" class="msg-row msg-row--system">
      <div class="system-banner">
        <span class="system-icon">!</span>
        {{ message.content }}
      </div>
    </div>


    <!-- 助手 -->
    <div v-else class="msg-row msg-row--assistant">
      <div class="assistant-avatar">{{ BRAND.assistantAvatar }}</div>
      <div class="assistant-body">
        <div class="bubble assistant-bubble">
          <MarkdownRenderer :content="message.content" />
          <span v-if="message.isStreaming" class="cursor">▍</span>
        </div>
        <SourceChips
          v-if="message.sources?.length"
          :sources="message.sources"
        />
      </div>
    </div>
  </div>
</template>

<style scoped>
.message {
  animation: fade-in .3s ease-out;
}

@keyframes fade-in {
  from { opacity: 0; transform: translateY(6px); }
  to   { opacity: 1; transform: translateY(0); }
}

/* ── 行 ── */
.msg-row {
  display: flex;
  padding: 4px 0;
}

.msg-row--user {
  justify-content: flex-end;
  align-items: flex-start;
  gap: 10px;
}

.msg-row--system {
  justify-content: center;
}

.msg-row--assistant {
  align-items: flex-start;
  gap: 10px;
}

/* ── 气泡 ── */
.bubble {
  max-width: 78%;
  font-size: 14px;
  line-height: 1.72;
  word-break: break-word;
}

.user-bubble {
  background: var(--grad-primary);
  color: #fff;
  padding: 10px 16px;
  border-radius: 18px 18px 4px 18px;
  box-shadow: var(--shadow-primary);
}

.assistant-bubble {
  background: var(--el-fill-color-light);
  border: 1px solid var(--el-border-color);
  padding: 14px 18px;
  border-radius: 4px 18px 18px 18px;
  color: var(--el-text-color-primary);
  box-shadow: var(--shadow-sm);
  transition: box-shadow .25s ease, border-color .25s ease;
}

.assistant-bubble:hover {
  box-shadow: var(--shadow-md);
  border-color: var(--el-color-primary);
}

/* ── 系统横幅 ── */
.system-banner {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: var(--el-text-color-regular);
  background: #fef3c7;
  border: 1px solid #f59e0b;
  border-radius: var(--radius-md);
  padding: 8px 16px;
  max-width: 85%;
  box-shadow: var(--shadow-sm);
}

.system-icon {
  width: 20px;
  height: 20px;
  border-radius: 50%;
  background: #f59e0b;
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  font-weight: 700;
  flex-shrink: 0;
}

/* ── 助手 ── */
.assistant-avatar {
  width: 34px;
  height: 34px;
  border-radius: 10px;
  background: var(--grad-primary-soft);
  border: 1px solid var(--el-border-color);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 18px;
  flex-shrink: 0;
  margin-top: 2px;
  box-shadow: var(--shadow-sm);
}

.user-avatar {
  width: 34px;
  height: 34px;
  border-radius: 10px;
  background: var(--grad-primary-soft);
  border: 1px solid var(--el-border-color);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 18px;
  flex-shrink: 0;
  margin-top: 2px;
  box-shadow: var(--shadow-sm);
}

.assistant-body {
  min-width: 0;
  flex: 1;
}

/* ── 光标 ── */
.cursor {
  animation: blink 1s step-end infinite;
  color: var(--el-color-primary);
  font-weight: 700;
  font-size: 16px;
}

@keyframes blink {
  0%, 100% { opacity: 1; }
  50% { opacity: 0; }
}
</style>
