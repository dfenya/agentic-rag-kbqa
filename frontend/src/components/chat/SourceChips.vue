<script setup lang="ts">
import type { SourceItem } from '@/types/api'

defineProps<{ sources: SourceItem[] }>()
</script>

<template>
  <div class="sources" v-if="sources.length">
    <div class="sources-label">来源</div>
    <div class="sources-list">
      <el-popover
        v-for="(s, i) in sources"
        :key="i"
        placement="top"
        :width="320"
        trigger="hover"
        :show-after="300"
      >
        <template #reference>
          <el-tag type="info" size="default" effect="plain" class="source-chip">
            {{ s.source }}
            <span class="source-id">({{ s.parent_id.slice(0, 8) }})</span>
          </el-tag>
        </template>
        <div class="source-pop">
          <div class="source-pop-title">{{ s.source }}</div>
          <div class="source-pop-id">parent_id: {{ s.parent_id }}</div>
        </div>
      </el-popover>
    </div>
  </div>
</template>

<style scoped>
.sources {
  margin-top: 10px;
  padding-top: 8px;
  border-top: 1px solid var(--el-border-color-lighter);
  display: flex;
  align-items: flex-start;
  gap: 8px;
  flex-wrap: wrap;
}
.sources-label {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  flex-shrink: 0;
  padding-top: 2px;
}
.sources-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.source-chip {
  cursor: pointer;
}
.source-id {
  font-size: 11px;
  color: var(--el-text-color-placeholder);
  margin-left: 2px;
}
.source-pop-title {
  font-weight: 600;
  margin-bottom: 4px;
}
.source-pop-id {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  font-family: monospace;
}
</style>
