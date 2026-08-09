import axios from 'axios'
import type {
  ChatRequest, ChatResumeRequest,
  ConversationItem, MessageItem,
  DocumentItem,
  UploadTaskInfo,
  LongTermMemoryItem,
  KnowledgeBase, KBCreateRequest,
  AppSettings,
  HealthResponse,
} from '@/types/api'

const api = axios.create({
  baseURL: '/api/v1',
  timeout: 120000,
  headers: { 'Content-Type': 'application/json' },
})

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

api.interceptors.response.use(
  (res) => res,
  (err) => {
    const isAuthRequest = err.config?.url?.startsWith('/auth/')
    if (err.response?.status === 401 && !isAuthRequest) {
      localStorage.removeItem('token')
      localStorage.removeItem('user')
      window.location.href = '/login'
    }
    return Promise.reject(err)
  }
)

// ── 系统 ──
export async function getHealth(): Promise<HealthResponse> {
  const { data } = await api.get('/health')
  return data
}

// ── 认证 ──
export async function registerUser(username: string, password: string) {
  const { data } = await api.post('/auth/register', { username, password })
  return data as { access_token: string; user_id: string; username: string }
}

export async function loginUser(username: string, password: string) {
  const { data } = await api.post('/auth/login', { username, password })
  return data as { access_token: string; user_id: string; username: string }
}

function authHeaders(): Record<string, string> {
  const token = localStorage.getItem('token')
  return token ? { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` } : { 'Content-Type': 'application/json' }
}

// ── 对话 (SSE 流用 fetch 原生支持) ──
export function chatSSE(req: ChatRequest, signal?: AbortSignal): Promise<Response> {
  return fetch('/api/v1/chat/stream', {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify(req),
    signal,
  })
}

export function resumeSSE(req: ChatResumeRequest, signal?: AbortSignal): Promise<Response> {
  return fetch('/api/v1/chat/resume', {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify(req),
    signal,
  })
}

// ── 会话 ──
export async function getConversations(params?: { q?: string }) {
  const { data } = await api.get('/conversations', { params })
  return data as { items: ConversationItem[]; total: number }
}

// 创建空对话（豆包式：点「新对话」即刻落库，侧边栏即时显示）
export async function createConversation(body?: { title?: string; model?: string }) {
  const { data } = await api.post('/conversations', body ?? {})
  return data as ConversationItem
}

export async function getConversationMessages(id: string) {
  const { data } = await api.get(`/conversations/${id}/messages`)
  return data as MessageItem[]
}

export async function updateConversation(id: string, body: { title?: string }) {
  const { data } = await api.patch(`/conversations/${id}`, body)
  return data as ConversationItem
}

export async function deleteConversation(id: string) {
  await api.delete(`/conversations/${id}`)
}

// ── 知识库 ──
export async function getKnowledgeBases(): Promise<KnowledgeBase[]> {
  const { data } = await api.get('/knowledge-bases')
  return data
}

export async function createKnowledgeBase(body: KBCreateRequest): Promise<KnowledgeBase> {
  const { data } = await api.post('/knowledge-bases', body)
  return data
}

export async function deleteKnowledgeBase(id: string): Promise<void> {
  await api.delete(`/knowledge-bases/${id}`)
}

// ── 文档 ──
export async function getDocuments(params?: { kb_id?: string; q?: string; page?: number; page_size?: number }) {
  const { data } = await api.get('/documents', { params })
  return data as { items: DocumentItem[]; total: number }
}

export async function deleteDocument(id: string) {
  await api.delete(`/documents/${id}`)
}

export async function retryDocument(id: string) {
  const { data } = await api.post(`/documents/${id}/retry`)
  return data as DocumentItem
}

// ── 上传 ──
export async function uploadDocuments(files: File[], kb_id?: string): Promise<{ upload_id: string; tasks: UploadTaskInfo[] }> {
  const form = new FormData()
  files.forEach(f => form.append('files', f))
  const qs = kb_id ? `?kb_id=${encodeURIComponent(kb_id)}` : ''
  const { data } = await api.post(`/documents${qs}`, form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
  return data
}
export async function getUploadStatus(uploadId: string) {
  const { data } = await api.get(`/uploads/${uploadId}`)
  return data as { tasks: UploadTaskInfo[] }
}

export function getUploadSSE(uploadId: string): EventSource {
  const token = localStorage.getItem('token') || ''
  return new EventSource(`/api/v1/uploads/${uploadId}/events?token=${encodeURIComponent(token)}`)
}

// ── 长期记忆 ──
export async function getLongTimeMemories(params?: { type?: string; q?: string }) {
  const { data } = await api.get('/memories', { params })
  return data as LongTermMemoryItem[]
}

export async function updateLongTermMemory(id: string, body: { content?: string; importance?: number }) {
  const { data } = await api.patch(`/memories/${id}`, body)
  return data as LongTermMemoryItem
}

export async function deleteLongTermMemory(id: string) {
  await api.delete(`/memories/${id}`)
}
// ── 设置 ──
export async function getSettings() {
  const { data } = await api.get('/settings')
  return data as AppSettings
}

export async function updateSettings(partial: Record<string, unknown>) {
  const { data } = await api.put('/settings', partial)
  return data
}

// ── 模型 ──
export async function getModels() {
  const { data } = await api.get('/models')
  return data as { name: string; size: number; modified_at: string }[]
}

export async function getCurrentModel() {
  const { data } = await api.get('/models/current')
  return data as { model: string }
}
