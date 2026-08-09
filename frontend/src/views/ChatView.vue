<script setup lang="ts">
import { useRoute, useRouter } from 'vue-router'
import { useChatStore } from '@/stores/chat'
import { useConversationsStore } from '@/stores/conversations'
import { useChatStream } from '@/composables/useChatStream'
import { getKnowledgeBases, deleteConversation } from '@/api/client'
import type { KnowledgeBase } from '@/types/api'
import { BRAND } from '@/config/brand'
import MessageItem from '@/components/chat/MessageItem.vue'
import ChatInput from '@/components/chat/ChatInput.vue'
import ClarificationCard from '@/components/chat/ClarificationCard.vue'

const route = useRoute()
const router = useRouter()
const chatStore = useChatStore()
const conversationsStore = useConversationsStore()
const { sendMessage, resumeClarification, abort, error } = useChatStream()

const inputMessage = ref('')
const messagesRef = ref<HTMLElement | null>(null)
const kbList = ref<KnowledgeBase[]>([])

async function loadKBs() {
  try { kbList.value = await getKnowledgeBases() } catch { /* 忽略 */ }
}

onMounted(loadKBs)

// 切走空对话时自动清理：避免侧边栏堆积无消息的空会话。
// 判定依据是会话的 message_count（后端持久化值），而非内存中的 messages，
// 这样即使用户点了「清空对话」清掉内存视图，有消息的会话也不会被误删。
async function cleanupEmptyConv(convId: string | null) {
  if (!convId) return
  const conv = conversationsStore.conversations.find(c => c.id === convId)
  if (!conv || conv.message_count > 0) return
  conversationsStore.removeConversation(convId)
  try {
    await deleteConversation(convId)
  } catch { /* 已删除或不存在：忽略 */ }
}

// 离开对话页（切到知识库/记忆/设置等）时，中止仍在进行的流：
// 组件卸载后 useChatStream 的闭包会丢失，不中止就会留下孤儿请求继续污染 store
onBeforeUnmount(() => {
  if (chatStore.isStreaming) {
    abort()
  }
  // 离开页面时，若当前是空对话则清理（不 await：组件已卸载，后台删除即可）
  cleanupEmptyConv(chatStore.conversationId)
})

const hasClarification = computed(() => {
  return chatStore.messages.some(m => m.metadata?.node === 'clarification')
})

// 新消息时自动滚动到底部
watch(
  () => chatStore.messages.length,
  () => nextTick(() => {
    if (messagesRef.value) {
      messagesRef.value.scrollTop = messagesRef.value.scrollHeight
    }
  }),
)

// 内容更新时也滚动（流式输出）
watch(
  () => chatStore.messages.map(m => m.content).join('|'),
  () => nextTick(() => {
    if (messagesRef.value) {
      messagesRef.value.scrollTop = messagesRef.value.scrollHeight
    }
  }),
)

// 路由参数变化：从侧边栏点击历史对话时加载消息
watch(() => route.params.id, async (id, oldId) => {
  // 切换前：若离开的是空对话（message_count=0），自动清理
  if (oldId && typeof oldId === 'string' && oldId !== id) {
    await cleanupEmptyConv(oldId)
  }
  // 切换前仅清理流式 UI 状态（不要清空 messages，因为 loadMessages 会用 DB 数据覆盖）
  // 同时：abort 只是关闭前端 SSE 连接，后端后台线程会继续跑完并持久化
  chatStore.resetStreamingUI()
  if (id && typeof id === 'string') {
    // 切换到其他会话前，先中止当前正在进行的 SSE 流
    // （后端不会 cancel，后台线程继续执行直到持久化完成）
    abort()
    await chatStore.loadMessages(id)
  } else {
    // 回到新对话页面：彻底清空
    chatStore.resetAllState()
  }
}, { immediate: true })

// 新对话发送消息后，后端返回 conversation_id，自动更新 URL 并刷新侧边栏
watch(() => chatStore.conversationId, (newId) => {
  if (newId && route.params.id !== newId) {
    // replace 而非 push：避免历史记录中残留 /chat → /chat/:id 两条
    router.replace({ name: 'chat', params: { id: newId } })
    // 立即刷新侧边栏，让新对话出现在列表中
    conversationsStore.fetchConversations()
  }
})

const selectedKb = computed(() =>
  kbList.value.find(k => k.id === chatStore.kbId)
)

async function handleSend() {
  const msg = inputMessage.value.trim()
  if (!msg || chatStore.isStreaming) return
  inputMessage.value = ''
  // 乐观更新侧边栏：立即反映用户消息（标题/预览/计数/置顶），零延迟反馈
  conversationsStore.touchConversation(chatStore.conversationId, msg)
  await sendMessage(msg)
  // 流结束后同步后端真实状态（标题、预览、sources 计数等）
  conversationsStore.fetchConversations()
}

async function handleClarification(reply: string) {
  await resumeClarification(reply)
}

function handleKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    handleSend()
  }
}
</script>

<template>
  <div class="chat-view">
    <!-- 头部 -->
    <header class="chat-header">
      <div class="header-left">
        <div class="header-info">
          <h1 class="header-title">{{ BRAND.chatHeaderTitle }}</h1>
          <span class="header-status">
            <template v-if="chatStore.isStreaming">
              <span class="pulse-dot" /> 正在回答…
            </template>
            <template v-else-if="chatStore.currentStage">
              <span class="pulse-dot" /> {{ chatStore.currentStage }}
            </template>
            <template v-else-if="selectedKb">
              {{ BRAND.kbSubtitleTemplate.replace('%NAME%', selectedKb.name) }}
            </template>
            <template v-else>
              {{ BRAND.noKbSubtitle }}
            </template>
          </span>
        </div>
      </div>
      <div class="header-right">
        <el-select
          v-model="chatStore.kbId"
          placeholder="选择知识库"
          clearable
          size="large"
          style="width: 240px"
          @focus="loadKBs"
        >
          <template #prefix>
            <span style="margin-right:4px">📚</span>
          </template>
          <el-option
            v-for="k in kbList"
            :key="k.id"
            :label="`📁 ${k.name}（${k.document_count} 篇文档）`"
            :value="k.id"
          />
        </el-select>
      </div>
    </header>

    <!-- 消息区 -->
    <div ref="messagesRef" class="messages-area">
      <!-- 空状态 -->
      <div v-if="chatStore.messages.length === 0" class="empty-state">
        <div class="empty-icon">{{ BRAND.emptyIcon }}</div>
        <h2 class="empty-title">{{ BRAND.emptyTitle }}</h2>
        <p class="empty-desc">{{ BRAND.emptyDesc }}</p>
        <div class="quick-actions">
          <button
            v-for="q in BRAND.quickQuestions"
            :key="q"
            class="quick-chip"
            :disabled="chatStore.isStreaming"
            @click="inputMessage = q; handleSend()"
          >
            {{ q }}
          </button>
        </div>
      </div>

      <!-- 消息列表 -->
      <div v-else class="message-list">
        <template v-for="(msg, idx) in chatStore.messages" :key="msg.id">
          <MessageItem
            :message="msg"
            :is-first-assistant="
              msg.role === 'assistant'
              && (idx === 0 || chatStore.messages[idx - 1]?.role === 'user')
            "
          />
        </template>

        <ClarificationCard
          v-if="hasClarification && !chatStore.isStreaming"
          @submit="handleClarification"
        />
      </div>

      <!-- 错误提示 -->
      <div v-if="error" class="error-toast">
        <el-alert :title="error" type="error" show-icon @close="error = null" />
      </div>
    </div>

    <!-- 输入区 -->
    <div class="chat-footer">
      <ChatInput
        v-model="inputMessage"
        :disabled="chatStore.isStreaming"
        :is-streaming="chatStore.isStreaming"
        @send="handleSend"
        @keydown="handleKeydown"
        @stop="abort"
      />
    </div>
  </div>
</template>

<style scoped>
.chat-view {
  height: 100%;
  display: flex;
  flex-direction: column;
}

/* ── 头部 ── */
.chat-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 20px;
  border-bottom: 1px solid var(--el-border-color);
  flex-shrink: 0;
  backdrop-filter: blur(16px) saturate(180%);
  -webkit-backdrop-filter: blur(16px) saturate(180%);
  background: var(--el-bg-color);
  gap: 16px;
  z-index: 10;
}

/* 深色模式：头部适配 */
html.dark .chat-header {
  background: var(--el-bg-color);
  border-bottom-color: var(--el-border-color);
}

.header-left {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

.header-info {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.header-title {
  font-size: 16px;
  font-weight: 600;
  color: var(--el-text-color-primary);
  margin: 0;
  white-space: nowrap;
}

.header-status {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  display: flex;
  align-items: center;
  gap: 6px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.pulse-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #18a058;
  flex-shrink: 0;
  animation: pulse 1.2s ease-in-out infinite;
}

@keyframes pulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.4; transform: scale(0.75); }
}

.header-right {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

/* ── 消息区 ── */
.messages-area {
  flex: 1;
  overflow-y: auto;
  padding: 20px 24px;
  scroll-behavior: smooth;
}

/* ── 空状态 ── */
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  text-align: center;
  padding: 0 32px;
}

.empty-icon {
  font-size: 48px;
  width: 88px;
  height: 88px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 24px;
  background: var(--grad-primary-soft);
  box-shadow: var(--shadow-md);
  margin-bottom: 20px;
  animation: float 3s ease-in-out infinite;
}

@keyframes float {
  0%, 100% { transform: translateY(0); }
  50% { transform: translateY(-8px); }
}

.empty-title {
  font-size: 28px;
  font-weight: 700;
  margin: 0 0 8px;
  background: var(--grad-primary);
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
}

.empty-desc {
  color: var(--el-text-color-secondary);
  margin: 0 0 28px;
  max-width: 420px;
  font-size: 14px;
  line-height: 1.7;
}

.quick-actions {
  display: flex;
  flex-direction: column;
  gap: 10px;
  justify-content: center;
  max-width: 480px;
  width: 100%;
}

.quick-chip {
  padding: 12px 18px;
  border: 1px solid var(--el-border-color);
  border-radius: 14px;
  background: var(--el-fill-color-light);
  color: var(--el-text-color-regular);
  font-size: 13px;
  cursor: pointer;
  transition: all .25s ease;
  font-family: inherit;
  line-height: 1.4;
  text-align: left;
  box-shadow: var(--shadow-sm);
}
.quick-chip:hover {
  border-color: var(--el-color-primary);
  color: var(--el-color-primary);
  background: var(--grad-primary-soft);
  transform: translateY(-2px);
  box-shadow: var(--shadow-md);
}
.quick-chip:disabled {
  opacity: .5;
  cursor: not-allowed;
}

/* ── 消息列表 ── */
.message-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

/* ── 错误提示 ── */
.error-toast {
  margin-top: 12px;
}

/* ── 底部 ── */
.chat-footer {
  flex-shrink: 0;
  padding: 12px 24px 16px;
  border-top: 1px solid var(--el-border-color);
  background: var(--el-bg-color);
}

/* 深色模式：底部适配 */
html.dark .chat-footer {
  background: var(--el-bg-color);
  border-top-color: var(--el-border-color);
}
</style>
