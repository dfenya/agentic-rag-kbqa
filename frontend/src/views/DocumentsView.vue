<script setup lang="ts">
import { ElMessage, ElMessageBox } from 'element-plus'
import { Delete, Loading } from '@element-plus/icons-vue'
import { useDocumentsStore } from '@/stores/documents'
import { getKnowledgeBases, createKnowledgeBase, deleteKnowledgeBase } from '@/api/client'
import type { KnowledgeBase, UploadTaskInfo } from '@/types/api'
import UploadDropzone from '@/components/documents/UploadDropzone.vue'
import { formatDateTime } from '@/utils/datetime'

const store = useDocumentsStore()

const searchQuery = ref('')
const showUpload = ref(false)
const uploading = ref(false)
const kbList = ref<KnowledgeBase[]>([])
const selectedKbId = ref<string | null>(null)
const newKbName = ref('')
const showNewKb = ref(false)

async function refresh() {
  await Promise.all([loadKBs(), loadDocs()])
}

async function loadKBs() {
  try { kbList.value = await getKnowledgeBases() } catch { /* */ }
}

async function loadDocs() {
  await store.fetchDocuments({ kb_id: selectedKbId.value || undefined })
}

onMounted(refresh)
watch(selectedKbId, loadDocs)

const filteredDocs = computed(() => {
  const q = searchQuery.value.trim().toLowerCase()
  if (!q) return store.documents
  return store.documents.filter(d => d.filename.toLowerCase().includes(q))
})

async function handleCreateKB() {
  const name = newKbName.value.trim()
  if (!name) return
  try {
    await createKnowledgeBase({ name })
    newKbName.value = ''
    showNewKb.value = false
    ElMessage.success('知识库已创建')
    await loadKBs()
  } catch (e: any) {
    const detail = e?.response?.data?.detail || e?.message || String(e)
    ElMessage.error(`创建失败: ${detail}`)
  }
}

async function handleDeleteKB(kbId: string, kbName: string) {
  ElMessageBox.confirm(`确定删除「${kbName}」及其所有文档？不可恢复。`, '删除知识库', {
    confirmButtonText: '确认删除',
    cancelButtonText: '取消',
    type: 'warning',
  }).then(async () => {
    await deleteKnowledgeBase(kbId)
    if (selectedKbId.value === kbId) selectedKbId.value = null
    await refresh()
    ElMessage.success('已删除')
  }).catch(() => {})
}

// 处理阶段标签
const phaseLabels: Record<string, string> = {
  dedup:   '去重检查',
  extract: '文本提取',
  chunk:   '文档分块',
  store:   '写入向量数据库',
  error:   '处理失败',
}

function getPhaseLabel(phase: string | null, status: string): string {
  if (status === 'ready') return '处理完成'
  if (status === 'duplicate') return '文件重复，已跳过'
  if (status === 'error') return '处理失败'
  if (!phase) return '等待中…'
  return phaseLabels[phase] || phase
}

function getFileIcon(filename: string): string {
  return filename.toLowerCase().endsWith('.pdf') ? '📄' : '📝'
}

function getProgressStatus(status: string): '' | 'success' | 'exception' | 'warning' {
  switch (status) {
    case 'ready':      return 'success'
    case 'error':      return 'exception'
    case 'duplicate':  return 'warning'
    default:           return ''
  }
}

function getTaskTagType(status: string): 'success' | 'warning' | 'danger' | 'info' {
  switch (status) {
    case 'ready':      return 'success'
    case 'processing': return 'warning'
    case 'duplicate':  return 'info'
    case 'error':      return 'danger'
    default:           return 'info'
  }
}

function getTaskTagLabel(status: string): string {
  switch (status) {
    case 'ready':      return '成功'
    case 'processing': return '处理中'
    case 'duplicate':  return '重复'
    case 'error':      return '失败'
    default:           return '等待'
  }
}

async function handleUpload(files: File[]) {
  showUpload.value = false
  uploading.value = true
  store.uploadTasks = []
  try {
    // 上传文件，后端立即返回 upload_id（任务状态为 pending）
    const uploadId = await store.uploadFiles(files, selectedKbId.value || undefined)
    // 轮询上传状态，直到所有任务处理完成（非 pending/processing）
    const tasks = await pollUploadStatus(uploadId)
    await refresh()
    // 根据后端实际处理结果显示提示
    const success = tasks.filter(t => t.status === 'ready' || t.status === 'duplicate')
    const failed = tasks.filter(t => t.status === 'error')
    const pending = tasks.filter(t => t.status === 'pending' || t.status === 'processing')
    if (pending.length > 0) {
      ElMessage.warning(`处理超时 · ${pending.length} 个文件仍在处理中，请稍后刷新查看`)
    } else if (failed.length === 0) {
      ElMessage.success(`上传完成 · 成功 ${success.length} 个文件`)
    } else if (success.length === 0) {
      ElMessage.error(`上传失败 · ${failed.length} 个文件处理失败`)
    } else {
      ElMessage.warning(`部分成功 · 成功 ${success.length} 个，失败 ${failed.length} 个`)
    }
  } catch (e: any) {
    ElMessage.error(e?.message || '上传失败')
  } finally {
    uploading.value = false
  }
}

// 轮询上传任务状态，直到全部完成或超时
async function pollUploadStatus(uploadId: string): Promise<UploadTaskInfo[]> {
  const maxAttempts = 120
  for (let i = 0; i < maxAttempts; i++) {
    await store.refreshUploadStatus(uploadId)
    const tasks = store.uploadTasks
    const allDone = tasks.length > 0 && tasks.every(t => t.status !== 'pending' && t.status !== 'processing')
    if (allDone) return tasks
    await new Promise(r => setTimeout(r, 1000))
  }
  return store.uploadTasks
}

async function handleDeleteDoc(id: string, filename: string) {
  try {
    await ElMessageBox.confirm(`确定删除「${filename}」？`, '删除文档', {
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      type: 'warning',
    })
  } catch { return }
  try {
    await store.removeDocument(id)
    await loadDocs()
    await loadKBs()
    ElMessage.success('已删除')
  } catch (e: any) {
    ElMessage.error(`删除失败: ${e?.message || e}`)
  }
}

function fmtSize(b: number) {
  if (b < 1024) return `${b} B`
  if (b < 1024 * 1024) return `${(b / 1024).toFixed(1)} KB`
  return `${(b / (1024 * 1024)).toFixed(1)} MB`
}

function fmtDate(s: string) {
  return formatDateTime(s)
}

// 状态映射（el-tag 类型：success/warning/danger/info）
const statusMap: Record<string, { type: 'success' | 'warning' | 'danger' | 'info'; label: string }> = {
  ready:      { type: 'success', label: '就绪' },
  processing: { type: 'warning', label: '处理中' },
  duplicate:  { type: 'info',    label: '重复' },
  error:      { type: 'danger',  label: '失败' },
}
</script>

<template>
  <div class="docs-page">
    <div class="page-top">
      <div>
        <h2>📚 知识库</h2>
        <p class="sub">管理知识库和文档，构建专属问答数据库</p>
      </div>
      <el-button size="default" @click="showNewKb = true">+ 新建知识库</el-button>
    </div>

    <!-- 新建知识库对话框 -->
    <el-dialog v-model="showNewKb" title="新建知识库" width="400px">
      <el-input v-model="newKbName" placeholder="输入名称" maxlength="128" />
      <template #footer>
        <el-button @click="showNewKb = false">取消</el-button>
        <el-button type="primary" @click="handleCreateKB">创建</el-button>
      </template>
    </el-dialog>

    <!-- 知识库卡片 -->
    <div class="kb-row" v-if="kbList.length">
      <div
        v-for="kb in kbList" :key="kb.id"
        class="kb-card" :class="{ on: selectedKbId === kb.id }"
        @click="selectedKbId = kb.id"
      >
        <span class="kb-icon">📁</span>
        <div class="kb-body">
          <span class="kb-name">{{ kb.name }}</span>
          <span class="kb-n">{{ kb.document_count }} 篇文档</span>
        </div>
        <button class="kb-x" @click.stop="handleDeleteKB(kb.id, kb.name)">
          <el-icon :size="14"><Delete /></el-icon>
        </button>
      </div>
    </div>
    <el-empty v-else description="暂无知识库" class="kb-empty" />

    <!-- 选中的知识库 -->
    <template v-if="selectedKbId">
      <div class="toolbar">
        <el-input v-model="searchQuery" placeholder="搜索文档…" clearable size="default" style="width:220px">
          <template #prefix>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><path d="M15.5 14h-.79l-.28-.27A6.471 6.471 0 0 0 16 9.5 6.5 6.5 0 1 0 9.5 16c1.61 0 3.09-.59 4.23-1.57l.27.28v.79l5 4.99L20.49 19l-4.99-5zm-6 0C7.01 14 5 11.99 5 9.5S7.01 5 9.5 5 14 7.01 14 9.5 11.99 14 9.5 14z"/></svg>
          </template>
        </el-input>
        <el-button size="default" :disabled="uploading" @click="showUpload = !showUpload">
          {{ showUpload ? '收起' : '+ 上传文件' }}
        </el-button>
      </div>

      <Transition name="slide">
        <UploadDropzone v-if="showUpload" @upload="handleUpload" />
      </Transition>

      <!-- 上传进度弹窗（模态，阻止用户切换页面） -->
      <el-dialog
        v-model="uploading"
        title="正在处理文件…"
        width="500px"
        align-center
        :close-on-click-modal="false"
        :close-on-press-escape="false"
        :show-close="false"
        class="upload-dialog"
      >
        <div v-if="!store.uploadTasks.length" class="upload-item-phase" style="padding: 8px 0;">
          <el-icon class="is-loading" :size="14"><Loading /></el-icon>
          正在上传文件…
        </div>
        <div
          v-for="task in store.uploadTasks"
          :key="task.filename"
          class="upload-item"
        >
          <div class="upload-item-top">
            <span class="upload-item-icon">{{ getFileIcon(task.filename) }}</span>
            <span class="upload-item-name">{{ task.filename }}</span>
            <el-tag :type="getTaskTagType(task.status)" size="small" effect="light" round>
              {{ getTaskTagLabel(task.status) }}
            </el-tag>
          </div>
          <el-progress
            :percentage="Math.round(task.percent * 100)"
            :status="getProgressStatus(task.status)"
            :stroke-width="6"
            :show-text="false"
          />
          <div class="upload-item-phase">
            {{ getPhaseLabel(task.phase, task.status) }}
          </div>
          <div v-if="task.error" class="upload-item-error">{{ task.error }}</div>
        </div>
      </el-dialog>

      <el-table v-if="filteredDocs.length" :data="filteredDocs" size="default" class="doc-table">
        <el-table-column label="文件" prop="filename" show-overflow-tooltip>
          <template #default="{ row }">
            {{ getFileIcon(row.filename) }} {{ row.filename }}
          </template>
        </el-table-column>
        <el-table-column label="大小" prop="file_size" width="80">
          <template #default="{ row }">{{ fmtSize(row.file_size) }}</template>
        </el-table-column>
        <el-table-column label="状态" prop="status" width="90">
          <template #default="{ row }">
            <el-tooltip v-if="row.error" :content="row.error" placement="left">
              <el-tag :type="statusMap[row.status]?.type || 'info'" size="default" effect="light" round>
                {{ statusMap[row.status]?.label || row.status }}
              </el-tag>
            </el-tooltip>
            <el-tag v-else :type="statusMap[row.status]?.type || 'info'" size="default" effect="light" round>
              {{ statusMap[row.status]?.label || row.status }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="时间" prop="created_at" width="170">
          <template #default="{ row }">{{ fmtDate(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="删除操作" width="80" align="center">
          <template #default="{ row }">
            <el-button text size="default" type="danger" @click="handleDeleteDoc(row.id, row.filename)">
              <el-icon><Delete /></el-icon>
            </el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-else description="此知识库暂无文档 · 上传 PDF 或 Markdown 文件" class="doc-empty" />
    </template>
  </div>
</template>

<style scoped>
.docs-page { height: 100%; padding: 24px 32px; overflow-y: auto; }

.page-top {
  display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 20px;
}
.page-top h2 {
  margin: 0 0 4px; font-size: 20px; font-weight: 700;
  background: var(--grad-primary);
  -webkit-background-clip: text; background-clip: text;
  -webkit-text-fill-color: transparent;
}
.sub { margin: 0; color: var(--el-text-color-secondary); font-size: 13px; }

/* 知识库卡片 */
.kb-row { display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 24px; }
.kb-card {
  display: flex; align-items: flex-start; gap: 10px;
  padding: 10px 14px; border-radius: 10px;
  border: 1.5px solid var(--el-border-color);
  cursor: pointer; transition: all .25s ease; min-width: 170px;
  box-shadow: var(--shadow-sm);
}
.kb-card:hover {
  transform: translateY(-2px);
  border-color: var(--el-color-primary);
  box-shadow: var(--shadow-md);
}
/* 选中态：柔和蓝色渐变背景 + 蓝色边框 */
.kb-card.on {
  border-color: var(--el-color-primary);
  background: var(--grad-primary-soft);
  box-shadow: var(--shadow-sm);
}
.kb-icon { font-size: 20px; }
.kb-body { display: flex; flex-direction: column; flex: 1; }
.kb-name { font-size: 13px; font-weight: 500; }
.kb-n { font-size: 11px; color: var(--el-text-color-secondary); }
.kb-x {
  background: none; border: none; cursor: pointer; color: var(--el-text-color-secondary);
  opacity: 0; transition: opacity .15s; padding: 2px;
  display: flex; align-items: center;
  align-self: flex-end;
}
.kb-card:hover .kb-x { opacity: .5; }
.kb-card:hover .kb-x:hover { opacity: 1; color: #ef4444; }

.kb-empty { margin-top: 32px; }

/* 工具栏 */
.toolbar { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; gap: 12px; }

/* 过渡动画 */
.slide-enter-active, .slide-leave-active { transition: all .3s ease; overflow: hidden; }
.slide-enter-from, .slide-leave-to { opacity: 0; max-height: 0; margin-bottom: 0; }
.slide-enter-to, .slide-leave-from { max-height: 200px; margin-bottom: 16px; }

.doc-table { margin-top: 4px; }
.doc-empty { margin-top: 40px; }

/* 上传进度弹窗内容样式 */
.upload-item {
  padding: 12px 0;
  border-top: 1px solid var(--el-border-color-lighter);
}
.upload-item:first-of-type {
  border-top: none;
  padding-top: 0;
}
.upload-item-top {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}
.upload-item-icon { font-size: 18px; flex-shrink: 0; }
.upload-item-name {
  flex: 1;
  font-size: 13px;
  font-weight: 500;
  color: var(--el-text-color-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.upload-item-phase {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  margin-top: 4px;
}
.upload-item-error {
  font-size: 12px;
  color: var(--el-color-danger);
  margin-top: 4px;
  word-break: break-all;
}

/* 空状态图标容器：柔和蓝色渐变背景 + 阴影 + 大圆角 */
.hint-icon {
  display: flex; align-items: center; justify-content: center;
  width: 80px; height: 80px; border-radius: var(--radius-lg);
  background: var(--grad-primary-soft);
  box-shadow: var(--shadow-md);
  font-size: 40px;
}
</style>
