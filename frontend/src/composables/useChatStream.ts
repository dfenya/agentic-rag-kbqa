import { ref } from 'vue'
import { useChatStore, setStreamingMessageId } from '@/stores/chat'
import type { SSEEvent } from '@/types/api'
import { chatSSE, resumeSSE } from '@/api/client'
import { generateId } from '@/utils/id'

export function useChatStream() {
  const store = useChatStore()
  const error = ref<string | null>(null)
  let abortController: AbortController | null = null

  function abort() {
    abortController?.abort()
    abortController = null
    store.finishStreaming()
    store.resetStreamingUI()
  }

  async function streamFromResponse(response: Response) {
    if (!response.body) throw new Error('无响应体')

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })
      const parts = buffer.split('\n\n')
      buffer = parts.pop() || ''

      for (const part of parts) {
        for (const line of part.split('\n')) {
          if (!line.startsWith('data: ')) continue
          try {
            const event: SSEEvent = JSON.parse(line.slice(6))
            store.applySSEEvent(event)
          } catch { /* malformed event, skip */ }
        }
      }
    }
  }

  async function sendMessage(message: string) {
    abort()
    store.isStreaming = true
    error.value = null
    store.resetFlow()

    store.addMessage({ id: generateId(), role: 'user', content: message })

    const assistantId = generateId()
    setStreamingMessageId(assistantId)
    store.addMessage({
      id: assistantId,
      role: 'assistant',
      content: '',
      isStreaming: true,
    })

    abortController = new AbortController()

    try {
      const response = await chatSSE(
        {
          conversation_id: store.conversationId || undefined,
          message,
          kb_id: store.kbId || undefined,
        },
        abortController.signal,
      )
      if (!response.ok) throw new Error(`HTTP ${response.status}`)
      await streamFromResponse(response)
    } catch (e: unknown) {
      if (e instanceof DOMException && e.name === 'AbortError') return
      const msg = e instanceof Error ? e.message : '连接失败'
      error.value = msg
      store.addMessage({ id: generateId(), role: 'system', content: `❌ ${msg}` })
    } finally {
      store.isStreaming = false
      store.finishStreaming()
      abortController = null
    }
  }

  async function resumeClarification(reply: string) {
    if (!store.conversationId) return
    abort()
    store.isStreaming = true
    store.resetFlow()

    store.addMessage({ id: generateId(), role: 'user', content: reply })

    const assistantId = generateId()
    setStreamingMessageId(assistantId)
    store.addMessage({
      id: assistantId,
      role: 'assistant',
      content: '',
      isStreaming: true,
    })

    abortController = new AbortController()

    try {
      const response = await resumeSSE(
        { conversation_id: store.conversationId, reply },
        abortController.signal,
      )
      if (!response.ok) throw new Error(`HTTP ${response.status}`)
      await streamFromResponse(response)
    } catch (e: unknown) {
      if (e instanceof DOMException && e.name === 'AbortError') return
      error.value = e instanceof Error ? e.message : '连接失败'
    } finally {
      store.isStreaming = false
      store.finishStreaming()
      abortController = null
    }
  }

  return { sendMessage, resumeClarification, abort, error }
}
