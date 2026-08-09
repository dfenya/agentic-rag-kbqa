import { defineStore } from 'pinia'
import type { ConversationItem } from '@/types/api'
import * as api from '@/api/client'

export const useConversationsStore = defineStore('conversations', () => {
  const conversations = ref<ConversationItem[]>([])
  const loading = ref(false)

  async function fetchConversations() {
    loading.value = true
    try {
      const data = await api.getConversations()
      conversations.value = data.items || []
    } catch (e) {
      console.error('Failed to fetch conversations:', e)
    } finally {
      loading.value = false
    }
  }

  // 创建空对话：落库后乐观插入到列表头部（零延迟显示，不发全量请求）
  async function createConversation(): Promise<ConversationItem | null> {
    try {
      const conv = await api.createConversation()
      // 去重后置顶：避免重复 id
      conversations.value = [conv, ...conversations.value.filter(c => c.id !== conv.id)]
      return conv
    } catch (e) {
      console.error('Failed to create conversation:', e)
      return null
    }
  }

  // 发送消息时的乐观更新：立即反映用户消息到侧边栏（标题/预览/计数），
  // 待流结束后由 fetchConversations 同步后端真实状态
  function touchConversation(id: string | null, userMsg: string) {
    if (!id) return
    const conv = conversations.value.find(c => c.id === id)
    if (!conv) return
    if (!conv.title || conv.title === '新对话') {
      conv.title = userMsg.slice(0, 50)
    }
    conv.last_message_preview = userMsg
    conv.message_count = (conv.message_count || 0) + 1
    conv.updated_at = new Date().toISOString()
    // 置顶：最新活跃的对话排在最前
    conversations.value = [conv, ...conversations.value.filter(c => c.id !== id)]
  }

  // 从列表移除（用于空对话切走时的自动清理）
  function removeConversation(id: string) {
    conversations.value = conversations.value.filter(c => c.id !== id)
  }

  async function deleteConversation(id: string) {
    await api.deleteConversation(id)
    conversations.value = conversations.value.filter(c => c.id !== id)
  }

  return {
    conversations, loading,
    fetchConversations, createConversation, touchConversation,
    removeConversation, deleteConversation,
  }
})
