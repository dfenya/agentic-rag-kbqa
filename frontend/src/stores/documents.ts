import { defineStore } from 'pinia'
import type { DocumentItem, UploadTaskInfo } from '@/types/api'
import * as api from '@/api/client'

export const useDocumentsStore = defineStore('documents', () => {
  const documents = ref<DocumentItem[]>([])
  const uploadTasks = ref<UploadTaskInfo[]>([])
  const loading = ref(false)

  async function fetchDocuments(params?: { kb_id?: string; q?: string }) {
    loading.value = true
    try {
      const data = await api.getDocuments(params)
      documents.value = data.items || []
    } finally {
      loading.value = false
    }
  }

  async function removeDocument(id: string) {
    await api.deleteDocument(id)
    documents.value = documents.value.filter(d => d.id !== id)
  }

  async function retryDocument(id: string) {
    const updated = await api.retryDocument(id)
    const idx = documents.value.findIndex(d => d.id === id)
    if (idx >= 0) documents.value[idx] = updated
    return updated
  }

  async function uploadFiles(files: File[], kb_id?: string) {
    const result = await api.uploadDocuments(files, kb_id)
    uploadTasks.value = result.tasks
    return result.upload_id
  }

  async function refreshUploadStatus(uploadId: string) {
    const data = await api.getUploadStatus(uploadId)
    uploadTasks.value = data.tasks
  }

  return {
    documents, uploadTasks, loading,
    fetchDocuments, removeDocument, retryDocument,
    uploadFiles, refreshUploadStatus,
  }
})
