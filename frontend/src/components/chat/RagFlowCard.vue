<template>
  <div class="rag-flow-card" v-if="steps.length">
    <el-collapse v-model="expanded">
      <el-collapse-item name="flow">
        <template #title>
          <div class="flow-header">
            <span class="flow-dot" :class="allDone ? 'done' : 'running'"></span>
            <span class="flow-title">{{ flowTitle }}</span>
            <span class="flow-summary" v-if="!allDone">{{ currentLabel }}</span>
            <span class="flow-summary done" v-else>完成 ({{ totalDuration }})</span>
          </div>
        </template>
        <div class="flow-body">
          <div
            v-for="step in steps"
            :key="step.task ? `${step.stage}:${step.task}` : step.stage"
            class="flow-step"
          >
            <!-- 步骤头部 -->
            <div class="step-header">
              <span class="step-icon" :class="step.status">
                <el-icon v-if="step.status === 'running'"><Loading /></el-icon>
                <el-icon v-else-if="step.status === 'done'"><Check /></el-icon>
                <el-icon v-else-if="step.status === 'error'"><Close /></el-icon>
                <el-icon v-else><Remove /></el-icon>
              </span>
              <span class="step-label">{{ step.label }}</span>
              <span class="step-duration" v-if="step.durationMs">{{ step.durationMs }}ms</span>
            </div>

            <!-- 意图分析：改写后的子查询 -->
            <div v-if="step.stage === 'rewrite_query' && step.queries?.length" class="step-queries">
              <div v-for="(q, qi) in step.queries" :key="qi" class="query-item">
                <span class="query-num">{{ qi + 1 }}</span>
                <span class="query-text">{{ q }}</span>
              </div>
            </div>

            <!-- Agent 步骤内的工具调用 -->
            <div v-if="step.stage === 'agent' && step.tools.length" class="step-tools">
              <div
                v-for="(tool, ti) in step.tools"
                :key="ti"
                class="tool-item"
                :class="tool.status"
              >
                <span class="tool-icon">
                  <el-icon v-if="tool.status === 'running'"><Loading /></el-icon>
                  <el-icon v-else-if="tool.status === 'done'"><Check /></el-icon>
                  <span v-else>🔧</span>
                </span>
                <span class="tool-label">{{ tool.label }}</span>
                <span class="tool-count" v-if="tool.count !== undefined">
                  {{ tool.count > 0 ? `${tool.count} 条结果` : '无结果' }}
                </span>
                <!-- 工具结果预览 -->
                <el-collapse-transition>
                  <div v-if="tool.result && tool.status === 'done'" class="tool-result">
                    <pre>{{ tool.result }}</pre>
                  </div>
                </el-collapse-transition>
              </div>
            </div>
          </div>
        </div>
      </el-collapse-item>
    </el-collapse>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import type { RagFlowStep } from '@/types/api'

const props = defineProps<{
  steps: RagFlowStep[]
}>()

const expanded = ref<string[]>(['flow'])

const allDone = computed(() =>
  props.steps.length > 0 && props.steps.every(s => s.status === 'done' || s.status === 'error')
)

// 流程标题：纯 LLM 对话（所有步骤都是 llm 阶段）显示"LLM 对话流程"，否则"RAG 查询流程"
const flowTitle = computed(() => {
  const stages = props.steps.map(s => s.stage)
  const isPlainLLM = stages.length > 0 && stages.every(s => s === 'llm')
  return isPlainLLM ? 'LLM 对话流程' : 'RAG 查询流程'
})

const currentLabel = computed(() => {
  const running = props.steps.find(s => s.status === 'running')
  return running ? running.label : ''
})

const totalDuration = computed(() => {
  const total = props.steps.reduce((sum, s) => sum + (s.durationMs || 0), 0)
  return total > 1000 ? `${(total / 1000).toFixed(1)}s` : `${total}ms`
})
</script>

<style scoped>
.rag-flow-card {
  margin: 8px 0;
  border: 1px solid var(--el-border-color-light);
  border-radius: 8px;
  background: var(--el-fill-color-light);
  overflow: hidden;
}

.rag-flow-card :deep(.el-collapse) {
  border: none;
  --el-collapse-header-bg-color: transparent;
  --el-collapse-content-bg-color: transparent;
}

.rag-flow-card :deep(.el-collapse-item__header) {
  padding: 6px 12px;
  font-size: 13px;
  border: none;
  height: auto;
  line-height: 1.5;
}

.rag-flow-card :deep(.el-collapse-item__content) {
  padding: 0 12px 8px;
}

.rag-flow-card :deep(.el-collapse-item__wrap) {
  border: none;
}

.flow-header {
  display: flex;
  align-items: center;
  gap: 8px;
}

.flow-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}

.flow-dot.running {
  background: var(--el-color-primary);
  animation: pulse 1.2s ease-in-out infinite;
}

.flow-dot.done {
  background: var(--el-color-success);
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.4; }
}

.flow-title {
  font-weight: 600;
  color: var(--el-text-color-primary);
}

.flow-summary {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}

.flow-summary.done {
  color: var(--el-color-success);
}

.flow-body {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.flow-step {
  padding: 4px 0;
}

.step-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 3px 0;
}

.step-icon {
  display: flex;
  align-items: center;
  font-size: 14px;
  width: 18px;
}

.step-icon.running {
  color: var(--el-color-primary);
}

.step-icon.done {
  color: var(--el-color-success);
}

.step-icon.error {
  color: var(--el-color-danger);
}

.step-icon.pending {
  color: var(--el-text-color-placeholder);
}

.step-label {
  font-size: 13px;
  color: var(--el-text-color-regular);
}

.step-duration {
  margin-left: auto;
  font-size: 11px;
  color: var(--el-text-color-placeholder);
  font-family: 'Fira Code', monospace;
}

.step-tools {
  margin-left: 26px;
  margin-top: 2px;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.step-queries {
  margin-left: 26px;
  margin-top: 4px;
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.query-item {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  padding: 3px 6px;
  border-radius: 4px;
  font-size: 12px;
  background: var(--el-fill-color);
  line-height: 1.5;
}

.query-num {
  flex-shrink: 0;
  width: 16px;
  height: 16px;
  border-radius: 50%;
  background: var(--el-color-primary-light-7);
  color: var(--el-color-primary);
  font-size: 10px;
  font-weight: 600;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-top: 1px;
}

.query-text {
  color: var(--el-text-color-regular);
  word-break: break-all;
}

.tool-item {
  display: flex;
  align-items: flex-start;
  flex-wrap: wrap;
  gap: 6px;
  padding: 3px 6px;
  border-radius: 4px;
  font-size: 12px;
  background: var(--el-fill-color);
}

.tool-icon {
  display: flex;
  align-items: center;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.tool-item.running .tool-icon {
  color: var(--el-color-primary);
}

.tool-item.done .tool-icon {
  color: var(--el-color-success);
}

.tool-label {
  color: var(--el-text-color-regular);
  font-weight: 500;
}

.tool-count {
  margin-left: auto;
  font-size: 11px;
  color: var(--el-text-color-secondary);
}

.tool-result {
  width: 100%;
  margin-top: 4px;
}

.tool-result pre {
  margin: 0;
  padding: 6px 8px;
  background: var(--el-bg-color);
  border-radius: 4px;
  font-size: 11px;
  line-height: 1.5;
  max-height: 120px;
  overflow-y: auto;
  white-space: pre-wrap;
  word-break: break-all;
  color: var(--el-text-color-secondary);
  border: 1px solid var(--el-border-color-lighter);
}
</style>
