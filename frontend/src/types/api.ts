/* API 的类型定义，前后端共享的数据结构 */

// ── 健康检查 ──
export interface HealthResponse {
  status: string
  version: string
  services: { qdrant: string; ollama: string; sqlite: string }
}

// ── 知识库 ──
export interface KnowledgeBase {
  id: string
  name: string
  description: string | null
  document_count: number
  created_at: string
}

export interface KBCreateRequest {
  name: string
  description?: string
}

// ── 对话 ──
export interface ChatRequest {
  conversation_id?: string
  message: string
  kb_id?: string
  model?: string
  options?: Record<string, unknown>
}

export interface ChatResumeRequest {
  conversation_id: string
  reply: string
}

// SSE 事件
export type SSEEventType = 'session' | 'status' | 'clarification' | 'tool' | 'tool_result' | 'content' | 'sources' | 'done' | 'error' | 'flow_start' | 'flow_end' | 'query_analysis'

export interface SSEEvent {
  type: SSEEventType
  conversation_id?: string
  message_id?: string
  stage?: string
  label?: string
  question?: string
  name?: string
  args?: unknown
  delta?: string
  content?: string
  items?: SourceItem[]
  code?: string
  message?: string
  task?: string
  count?: number
  duration_ms?: number
  usage?: { input_tokens: number; output_tokens: number }
  // query_analysis 事件：意图分析/改写后的子查询
  questions?: string[]
  is_clear?: boolean
  original_query?: string
}

export interface SourceItem {
  source: string
  parent_id: string
}

// ── RAG 流程展示 ──

export interface RagFlowTool {
  name: string
  label: string
  status: 'running' | 'done' | 'error'
  args?: unknown
  result?: string
  count?: number
}

export interface RagFlowStep {
  stage: string
  label: string
  status: 'pending' | 'running' | 'done' | 'error'
  durationMs?: number
  task?: string
  tools: RagFlowTool[]
  children: RagFlowStep[]
  // rewrite_query 步骤：改写后的子查询列表（意图分析结果）
  queries?: string[]
}

// ── 文档 ──
export interface DocumentItem {
  id: string
  filename: string
  kb_id: string | null
  status: string
  file_size: number
  parent_count: number
  child_count: number
  error: string | null
  created_at: string
}

// ── 上传 ──
export interface UploadTaskInfo {
  doc_id: string | null
  filename: string
  status: string
  phase: string | null
  percent: number
  duplicate_of: string | null
  error: string | null
}

// ── 会话 ──
export interface ConversationItem {
  id: string; title: string; model: string; message_count: number
  last_message_preview: string | null; created_at: string; updated_at: string
}

export interface FlowStep {
  stage: string
  label: string
  task: string | null
  duration_ms: number | null
}

export interface MessageItem {
  id: string; role: string; content: string
  sources_json: string | null
  flow_steps: FlowStep[] | null
  created_at: string
}

// ── 长期记忆 ──
export interface LongTermMemoryItem {
  id: string; type: string; content: string; keywords: string[]
  importance: number; access_count: number; created_at: string; updated_at: string
}

// ── 设置 ──
export interface AppSettings {
  llm: Record<string, unknown>
  rag: Record<string, unknown>
  memory: Record<string, unknown>
}
