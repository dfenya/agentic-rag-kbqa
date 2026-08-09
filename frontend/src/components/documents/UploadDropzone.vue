<script setup lang="ts">
import { ElMessage } from 'element-plus'

const emit = defineEmits<{ upload: [files: File[]] }>()
const isDragging = ref(false)
const fileInputRef = ref<HTMLInputElement | null>(null)

const ALLOWED_EXTS = ['.pdf', '.md']

function isAllowed(filename: string): boolean {
  return ALLOWED_EXTS.some(ext => filename.toLowerCase().endsWith(ext))
}

function triggerFilePicker() {
  fileInputRef.value?.click()
}

function handleFileChange(e: Event) {
  const target = e.target as HTMLInputElement
  if (target.files?.length) {
    const files = Array.from(target.files)
    const valid = files.filter(f => isAllowed(f.name))
    const invalid = files.filter(f => !isAllowed(f.name))
    if (invalid.length) {
      ElMessage.warning(`仅支持 PDF / Markdown 文件，已忽略 ${invalid.length} 个不支持的文件`)
    }
    if (valid.length) emit('upload', valid)
    target.value = ''
  }
}

function handleDrop(e: DragEvent) {
  isDragging.value = false
  const files = Array.from(e.dataTransfer?.files || [])
  const valid = files.filter(f => isAllowed(f.name))
  const invalid = files.filter(f => !isAllowed(f.name))
  if (invalid.length) {
    ElMessage.warning(`仅支持 PDF / Markdown 文件，已忽略 ${invalid.length} 个不支持的文件`)
  }
  if (valid.length) emit('upload', valid)
}
</script>

<template>
  <div
    class="dropzone"
    :class="{ 'dropzone--active': isDragging }"
    @dragover.prevent="isDragging = true"
    @dragleave.prevent="isDragging = false"
    @drop.prevent="handleDrop"
    @click="triggerFilePicker"
  >
    <div class="dropzone-icon">
      <el-icon :size="48"><Upload /></el-icon>
    </div>
    <p class="dropzone-text">
      拖拽 PDF 或 Markdown 文件到此处，或<span class="dropzone-link">点击选择文件</span>
    </p>
    <p class="dropzone-hint">支持 .pdf / .md 格式，单个文件不超过 50MB</p>
    <input
      ref="fileInputRef"
      type="file"
      multiple
      accept=".pdf,.md"
      class="dropzone-input-hidden"
      @change="handleFileChange"
    />
  </div>
</template>

<style scoped>
.dropzone {
  border: 2px dashed var(--el-border-color);
  border-radius: 16px;
  padding: 40px 24px;
  text-align: center;
  cursor: pointer;
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  background: var(--el-fill-color-light);
  position: relative;
  overflow: hidden;
}

.dropzone--active {
  border-color: var(--el-color-primary);
  transform: scale(1.01);
  box-shadow: 0 0 0 4px var(--el-color-primary-light-5);
}

.dropzone-icon {
  margin-bottom: 8px;
  color: var(--el-text-color-secondary);
  transition: color 0.3s;
}

.dropzone:hover .dropzone-icon,
.dropzone--active .dropzone-icon {
  color: var(--el-color-primary);
}

.dropzone-text {
  margin: 0 0 4px;
  font-size: 15px;
  color: var(--el-text-color-regular);
  position: relative;
}

.dropzone-link {
  color: var(--el-color-primary);
  font-weight: 500;
}

.dropzone-hint {
  margin: 0;
  font-size: 12px;
  color: var(--el-text-color-secondary);
  position: relative;
}

.dropzone-input-hidden {
  display: none;
}
</style>
