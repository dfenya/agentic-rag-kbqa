import { defineStore } from 'pinia'
import type { LongTermMemoryItem } from '@/types/api'
import * as api from '@/api/client'

/* 长期记忆的 Pinia store */
export const useMemoryStore = defineStore('memory', () => {
  const memories = ref<LongTermMemoryItem[]>([])
  const loading = ref(false)

  async function fetchMemories(params?: { type?: string; q?: string }) {
    loading.value = true
    try {
      memories.value = await api.getLongTimeMemories(params)
    } finally {
      loading.value = false
    }
  }

  async function removeMemory(id: string) {
    await api.deleteLongTermMemory(id)
    memories.value = memories.value.filter(m => m.id !== id)
  }

  async function updateMemoryItem(id: string, body: { content?: string; importance?: number }) {
    const updated = await api.updateLongTermMemory(id, body)
    const idx = memories.value.findIndex(m => m.id === id)
    if (idx >= 0) memories.value[idx] = updated
  }

  return { memories, loading, fetchMemories, removeMemory, updateMemoryItem }
})
