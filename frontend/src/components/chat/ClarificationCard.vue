<script setup lang="ts">
const emit = defineEmits<{ submit: [reply: string] }>()
const reply = ref('')

function handleSubmit() {
  if (!reply.value.trim()) return
  emit('submit', reply.value.trim())
  reply.value = ''
}
</script>

<template>
  <div class="clarification-card">
    <el-card shadow="never">
      <template #header>系统需要更多信息</template>
      <p class="clarification-text">系统需要您补充更多信息才能准确回答。请在下方输入补充说明：</p>
      <el-input
        v-model="reply"
        type="textarea"
        placeholder="补充您的具体情况..."
        :autosize="{ minRows: 2, maxRows: 4 }"
      />
      <el-button type="primary" size="default" style="margin-top: 8px" @click="handleSubmit">
        提交补充
      </el-button>
    </el-card>
  </div>
</template>

<style scoped>
.clarification-card {
  margin: 12px 0;
  max-width: 500px;
  animation: fade-in .3s ease-out;
  border-radius: var(--radius-lg);
  overflow: hidden;
  box-shadow: var(--shadow-md);
}
.clarification-text {
  font-size: 13px;
  color: var(--el-text-color-regular);
  margin: 0 0 8px;
}
</style>
