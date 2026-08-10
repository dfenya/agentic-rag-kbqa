import { defineStore } from 'pinia'
import { ref, reactive, computed } from 'vue'
import type { SSEEvent, SourceItem, RagFlowStep, RagFlowTool, MessageItem } from '@/types/api'
import * as api from '@/api/client'
import { generateId } from '@/utils/id'

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant' | 'system' | 'tool'
  content: string
  toolName?: string
  sources?: SourceItem[]
  isStreaming?: boolean
  metadata?: Record<string, string>
  // 持久化的流程步骤（从历史会话加载时恢复，供 RagFlowCard 显示）
  flowSteps?: RagFlowStep[]
}

// 模块级变量，不暴露到 Pinia store 的公共接口
let _streamingMsgId: string | null = null

export function setStreamingMessageId(id: string | null) {
  _streamingMsgId = id
}

// 工具名称中文映射
const TOOL_LABELS: Record<string, string> = {
  search_child_chunks: '检索文档片段',
  retrieve_parent_chunks: '回溯完整内容',
}

// 根据 stage 排序权重
const STAGE_ORDER: Record<string, number> = {
  load_long_term_memory: 1,
  summarize_history: 2,
  rewrite_query: 3,
  request_clarification: 4,
  agent: 5,
  llm: 6,
  aggregate_answers: 7,
}

export const useChatStore = defineStore('chat', () => {
  const messages = reactive<ChatMessage[]>([])
  const isStreaming = ref(false)
  const currentStage = ref('')
  const conversationId = ref<string | null>(null)
  const kbId = ref<string | null>(null)
  const ragFlowSteps = reactive<RagFlowStep[]>([])
  // 标记 ragFlowSteps 所属的会话 ID，防止跨会话污染
  const _flowConvId = ref<string | null>(null)
  // 轮询定时器（用于切回仍在后台处理的会话时轮询加载）
  let _pollingTimer: number | null = null

  function resetFlow() {
    ragFlowSteps.splice(0, ragFlowSteps.length)
    _flowConvId.value = null
  }

  function _stopPolling() {
    if (_pollingTimer) {
      clearInterval(_pollingTimer)
      _pollingTimer = null
    }
  }

  // 切换会话时：仅清理流式 UI 状态和 flow，保留 messages（后台可能还在处理）
  function resetStreamingUI() {
    isStreaming.value = false
    currentStage.value = ''
    _streamingMsgId = null
    resetFlow()
    _stopPolling()
  }

  // 彻底清空所有会话相关状态（点"新对话"时使用）
  function resetAllState() {
    messages.splice(0, messages.length)
    isStreaming.value = false
    currentStage.value = ''
    conversationId.value = null
    kbId.value = null
    _streamingMsgId = null
    resetFlow()
    _stopPolling()
  }

  // 将后端持久化的 flow_steps 转换为前端 RagFlowStep 格式
  function _convertFlowSteps(apiSteps: { stage: string; label: string; task: string | null; duration_ms: number | null }[]): RagFlowStep[] {
    return apiSteps.map(s => ({
      stage: s.stage,
      label: s.label,
      status: 'done' as const,
      durationMs: s.duration_ms ?? undefined,
      task: s.task || undefined,
      tools: [],
      children: [],
    }))
  }

  function _upsertStep(stage: string, label: string, task?: string | null) {
    const key = task ? `${stage}:${task}` : stage
    const existing = ragFlowSteps.find(s => (s.task ? `${s.stage}:${s.task}` : s.stage) === key)
    if (existing) {
      existing.status = 'running'
      return existing
    }
    const step: RagFlowStep = { stage, label, status: 'running', task: task || undefined, tools: [], children: [] }
    ragFlowSteps.push(step)
    ragFlowSteps.sort((a, b) => (STAGE_ORDER[a.stage] || 99) - (STAGE_ORDER[b.stage] || 99))
    return step
  }

  function _findStep(stage: string, task?: string | null): RagFlowStep | undefined {
    const key = task ? `${stage}:${task}` : stage
    return ragFlowSteps.find(s => (s.task ? `${s.stage}:${s.task}` : s.stage) === key)
  }

  function _ensureAgentStep(task?: string | null): RagFlowStep {
    const existing = _findStep('agent', task) || _findStep('agent')
    if (existing) return existing
    const step: RagFlowStep = { stage: 'agent', label: '检索知识库', status: 'running', task: task || undefined, tools: [], children: [] }
    ragFlowSteps.push(step)
    ragFlowSteps.sort((a, b) => (STAGE_ORDER[a.stage] || 99) - (STAGE_ORDER[b.stage] || 99))
    return step
  }

  function addFlowTool(name: string, args: unknown, task?: string | null) {
    const target = _ensureAgentStep(task)
    target.tools.push({ name, label: TOOL_LABELS[name] || name, status: 'running' as const, args })
  }

  function addFlowToolResult(name: string, content: string, task?: string | null, count?: number) {
    const target = _ensureAgentStep(task)
    const tool = [...target.tools].reverse().find(t => t.name === name && t.status === 'running')
    if (tool) {
      tool.status = 'done'
      tool.result = content
      tool.count = count
    }
  }

  function addMessage(msg: ChatMessage) {
    messages.push(msg)
  }

  function getLastAssistant(): ChatMessage | undefined {
    for (let i = messages.length - 1; i >= 0; i--) {
      if (messages[i].role === 'assistant') return messages[i]
    }
    return undefined
  }

  function appendToAssistant(content: string) {
    const msg = _streamingMsgId ? messages.find(m => m.id === _streamingMsgId) : getLastAssistant()
    if (msg) msg.content += content
  }

  function finishStreaming() {
    const msg = _streamingMsgId ? messages.find(m => m.id === _streamingMsgId) : getLastAssistant()
    if (msg) msg.isStreaming = false
    _streamingMsgId = null
  }

  function clearMessages() {
    messages.splice(0, messages.length)
    currentStage.value = ''
    conversationId.value = null
    kbId.value = null
    _streamingMsgId = null
    resetFlow()
  }

  // 判断会话是否"后台处理中"：最后一条是 user，且整条消息列表无任何 assistant（说明正在等第一个回复）
  // 或者：最后一条 user 之后的消息全是 user（没有 assistant），即最后一个非 user 消息也是 user，
  // 简化为：整个 messages 里，user 数量比 assistant 多 1（单轮对话就是处理中）
  function _isProcessing(msgs: ChatMessage[]): boolean {
    if (!msgs.length) return false
    if (msgs[msgs.length - 1].role !== 'user') return false
    const userCount = msgs.filter(m => m.role === 'user').length
    const assistantCount = msgs.filter(m => m.role === 'assistant').length
    // 1 user + 0 assistant = 初始提问后台处理中
    // 2 user + 1 assistant = 第二轮提问后台处理中
    return userCount - assistantCount === 1
  }

  // 从后端加载某个会话的历史消息，填充到 messages 中
  // 如果检测到该会话仍在"处理中"（user 最后、无对应 assistant），自动开启轮询，
  // 直到后端完成持久化才停止，保证用户切回来能看到完整结果
  async function loadMessages(convId: string) {
    conversationId.value = convId
    currentStage.value = ''
    _streamingMsgId = null
    resetFlow()
    _stopPolling()
    kbId.value = null

    async function doLoad(): Promise<ChatMessage[]> {
      try {
        const raw: MessageItem[] = await api.getConversationMessages(convId)
        return raw.map(m => {
          const msg: ChatMessage = {
            id: m.id,
            role: (['user', 'assistant', 'system', 'tool'].includes(m.role) ? m.role : 'system') as ChatMessage['role'],
            content: m.content,
          }
          if (m.sources_json) {
            try { msg.sources = JSON.parse(m.sources_json) } catch { /* 忽略解析失败 */ }
          }
          if (m.flow_steps && m.flow_steps.length > 0) {
            msg.flowSteps = _convertFlowSteps(m.flow_steps)
          }
          return msg
        })
      } catch {
        return []
      }
    }

    const loaded = await doLoad()
    messages.splice(0, messages.length, ...loaded)

    // 切回仍在后台处理的会话：开启轮询直到 assistant 消息出现
    if (_isProcessing(messages)) {
      isStreaming.value = true
      currentStage.value = '后台处理中…'
      let attempt = 0
      const MAX_ATTEMPTS = 90  // 约 3 分钟兜底
      _pollingTimer = window.setInterval(async () => {
        attempt++
        const latest = await doLoad()
        // 如果该会话已被切走，conversationId 会变，直接停
        if (conversationId.value !== convId) {
          _stopPolling()
          return
        }
        messages.splice(0, messages.length, ...latest)
        if (!_isProcessing(latest) || attempt >= MAX_ATTEMPTS) {
          _stopPolling()
          isStreaming.value = false
          currentStage.value = ''
        }
      }, 2000)
    }
  }

  function applySSEEvent(event: SSEEvent) {
    switch (event.type) {
      case 'session':
        conversationId.value = event.conversation_id ?? null
        break

      case 'status':
        currentStage.value = event.label || event.stage || ''
        break

      case 'flow_start':
        if (event.stage && event.label) {
          // 绑定流程数据到当前会话，防止跨会话污染
          if (!_flowConvId.value && conversationId.value) {
            _flowConvId.value = conversationId.value
          }
          _upsertStep(event.stage, event.label, event.task)
        }
        break

      case 'flow_end': {
        if (event.stage) {
          const step = _findStep(event.stage, event.task)
          if (step) {
            step.status = 'done'
            step.durationMs = event.duration_ms
          }
        }
        break
      }

      case 'query_analysis': {
        const step = _findStep('rewrite_query')
        if (step && event.questions?.length) {
          step.queries = event.questions
        }
        break
      }

      case 'clarification': {
        const msg: ChatMessage = {
          id: generateId(),
          role: 'assistant',
          content: event.question || '',
          metadata: { node: 'clarification' },
        }
        messages.push(msg)
        isStreaming.value = false
        _streamingMsgId = null
        break
      }

      case 'tool': {
        // 保留旧的消息卡片（兼容），同时更新 flow
        const hasPending = messages.some(
          m => m.role === 'tool' && m.toolName === event.name && !m.content
        )
        if (!hasPending) {
          messages.push({
            id: generateId(),
            role: 'tool',
            content: '',
            toolName: event.name,
          })
        }
        addFlowTool(event.name || 'unknown', event.args, event.task)
        break
      }

      case 'tool_result': {
        const tool = [...messages].reverse().find(
          m => m.role === 'tool' && m.toolName === event.name && !m.content
        )
        if (tool) {
          tool.content = event.content || '(无结果)'
        }
        addFlowToolResult(event.name || 'unknown', event.content || '', event.task, event.count)
        break
      }

      case 'content':
        appendToAssistant(event.delta || '')
        break

      case 'sources':
        if (event.sources?.length) {
          const msg = _streamingMsgId
            ? messages.find(m => m.id === _streamingMsgId)
            : getLastAssistant()
          if (msg) msg.sources = event.sources
        }
        break

      case 'done': {
        if (ragFlowSteps.length > 0) {
          const last = getLastAssistant()
          if (last && !last.flowSteps) {
            last.flowSteps = [...ragFlowSteps]
          }
        }
        finishStreaming()
        isStreaming.value = false
        currentStage.value = ''
        break
      }

      case 'error':
        messages.push({ id: generateId(), role: 'system' as const, content: `❌ ${event.message || '发生错误'}` })
        finishStreaming()
        isStreaming.value = false
        break
    }
  }

  // 判断流程数据是否属于当前会话（防止跨会话污染）
  const isFlowForCurrentConv = computed(() => {
    return !_flowConvId.value || _flowConvId.value === conversationId.value
  })

  return {
    messages, isStreaming, currentStage, conversationId, kbId, ragFlowSteps,
    isFlowForCurrentConv,
    addMessage, getLastAssistant, appendToAssistant, finishStreaming,
    clearMessages, loadMessages, applySSEEvent, resetFlow, resetAllState, resetStreamingUI,
  }
})
