<script setup lang="ts">
import type { SourceItem } from '@/types/api'

defineProps<{ sources: SourceItem[] }>()
</script>

<template>
  <div class="sources">
    <div class="sources-label">📚 依据：</div>
    <div class="sources-list">
      <el-tag
        v-for="(s, i) in sources"
        :key="i"
        type="info"
        size="default"
        effect="plain"
        class="source-chip"
      >
        {{ s.source }}
      </el-tag>
    </div>
  </div>
</template>

<style scoped>
.sources {
  margin-top: 10px;
  padding-top: 8px;
  border-top: 1px solid var(--el-border-color);
  display: flex;
  align-items: flex-start;
  gap: 6px;
  flex-wrap: wrap;
  animation: fade-in .3s ease-out;
}
.sources-label {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  flex-shrink: 0;
}
.sources-list {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}
.source-chip {
  cursor: default;
  transition: all .2s ease;
}
.source-chip:hover {
  transform: translateY(-1px);
  box-shadow: var(--shadow-sm);
}
</style>
