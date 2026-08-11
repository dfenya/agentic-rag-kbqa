<script setup lang="ts">
const props = defineProps<{
  modelValue: string
  disabled: boolean
  isStreaming: boolean
}>()

const emit = defineEmits<{
  'update:modelValue': [value: string]
  send: []
  stop: []
  keydown: [e: KeyboardEvent]
}>()

const localValue = computed({
  get: () => props.modelValue,
  set: (v) => emit('update:modelValue', v),
})

function handleSend() {
  if (!localValue.value.trim() || props.disabled) return
  emit('send')
}
</script>

<template>
  <div class="chat-input">
    <div class="input-wrapper">
      <el-input
        v-model="localValue"
        type="textarea"
        placeholder="输入问题，Enter 发送，Shift+Enter 换行…"
        :autosize="{ minRows: 1, maxRows: 5 }"
        :disabled="disabled"
        resize="none"
        @keydown="emit('keydown', $event)"
        class="input-field"
      />
      <div class="input-btns">
        <button
          v-if="isStreaming"
          class="btn btn-stop"
          @click="emit('stop')"
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="6" width="12" height="12" rx="2"/></svg>
          停止
        </button>
        <button
          v-else
          class="btn btn-send"
          :disabled="!localValue.trim()"
          @click="handleSend"
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg>
          发送
        </button>
      </div>
    </div>
    <div class="input-hint">
      <template v-if="isStreaming">
        <span class="live-dot" /> AI 生成中
      </template>

    </div>
  </div>
</template>

<style scoped>
.chat-input {
  max-width: 820px;
  margin: 0 auto;
}

/* 输入框 + 按钮同一水平线 */
.input-wrapper {
  display: flex;
  align-items: flex-end;
  gap: 10px;
  background: var(--el-fill-color-light);
  border: 1.5px solid var(--el-border-color);
  border-radius: 18px;
  padding: 8px 8px 8px 14px;
  box-shadow: var(--shadow-sm);
  transition: border-color .25s ease, box-shadow .25s ease;
}

.input-wrapper:focus-within {
  border-color: var(--el-color-primary);
  box-shadow: var(--shadow-primary), 0 0 0 3px rgba(37, 99, 235, .12);
}

.input-field {
  flex: 1;
}

.input-field :deep(.el-textarea__inner) {
  font-size: 14px;
  line-height: 1.6;
  min-height: 28px;
  box-shadow: none;
  background: transparent;
  border: none;
  padding: 4px 0;
}

/* 提示文字移到下方居中 */
.input-hint {
  text-align: center;
  font-size: 11px;
  color: var(--el-text-color-secondary);
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 6px 0 2px;
}

.live-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #18a058;
  animation: dot-pulse 1s infinite;
}

@keyframes dot-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: .3; }
}

/* 按钮组 */
.input-btns {
  display: flex;
  gap: 8px;
  flex-shrink: 0;
}

.btn {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 9px 20px;
  border: none;
  border-radius: 22px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: all .25s ease;
  font-family: inherit;
  line-height: 1;
  white-space: nowrap;
}

.btn-send {
  background: var(--grad-primary);
  color: #fff;
  box-shadow: var(--shadow-primary);
}
.btn-send:hover:not(:disabled) {
  transform: translateY(-1px);
  box-shadow: var(--shadow-primary-hover);
}
.btn-send:disabled {
  opacity: .4;
  cursor: not-allowed;
  box-shadow: none;
}

.btn-stop {
  background: var(--grad-warm);
  color: #fff;
  box-shadow: 0 6px 20px rgba(245, 158, 11, .28);
}
.btn-stop:hover {
  filter: brightness(.95);
  transform: translateY(-1px);
  box-shadow: 0 10px 28px rgba(245, 158, 11, .38);
}
</style>
