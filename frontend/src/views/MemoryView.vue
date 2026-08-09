<script setup lang="ts">
import { ElMessage, ElMessageBox } from 'element-plus'
import { Delete } from '@element-plus/icons-vue'
import { useMemoryStore } from '@/stores/memory'
import { formatDateTime } from '@/utils/datetime'

const store = useMemoryStore()
const filterType = ref<string>('all')

onMounted(() => store.fetchMemories())

const filtered = computed(() =>
  filterType.value && filterType.value !== 'all'
    ? store.memories.filter(m => m.type === filterType.value)
    : store.memories
)

async function handleDelete(id: string) {
  try {
    await ElMessageBox.confirm('确定删除此记忆？', '删除记忆', {
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      type: 'warning',
    })
  } catch { return }
  try {
    await store.removeMemory(id)
    await store.fetchMemories()
    ElMessage.success('已删除')
  } catch (e: any) {
    ElMessage.error(`删除失败: ${e?.message || e}`)
  }
}

const typeLabel: Record<string, string> = {
  user_preference: '用户偏好',
  faq_pattern: '高频问题',
  conversation_summary: '对话摘要',
}

const typeColor: Record<string, string> = {
  user_preference: 'info',
  faq_pattern: 'success',
  conversation_summary: 'warning',
}
</script>

<template>
  <div class="mem-view">
    <div class="page-top">
      <div>
        <h2>🧠 长期记忆</h2>
        <p class="sub">系统自动从对话中提取，用于个性化问答</p>
      </div>
    </div>

    <!-- 统计 -->
    <div class="stats">
      <div class="stat"><span class="n">{{ store.memories.length }}</span> 总计</div>
      <div class="stat"><span class="n">{{ store.memories.filter(m => m.type === 'user_preference').length }}</span> 偏好</div>
      <div class="stat"><span class="n">{{ store.memories.filter(m => m.type === 'faq_pattern').length }}</span> FAQ</div>
      <div class="stat"><span class="n">{{ store.memories.filter(m => m.type === 'conversation_summary').length }}</span> 摘要</div>
    </div>

    <!-- 筛选 -->
    <el-radio-group v-model="filterType" size="default" class="filter">
      <el-radio-button value="all">全部</el-radio-button>
      <el-radio-button value="user_preference">用户偏好</el-radio-button>
      <el-radio-button value="faq_pattern">高频问题</el-radio-button>
      <el-radio-button value="conversation_summary">对话摘要</el-radio-button>
    </el-radio-group>

    <el-table v-if="filtered.length" :data="filtered" v-loading="store.loading" size="default" stripe class="table">
      <el-table-column label="类型" prop="type" width="100">
        <template #default="{ row }">
          <el-tag :type="typeColor[row.type] || 'info'" size="default" effect="light" round>
            {{ typeLabel[row.type] || row.type }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="内容" prop="content" show-overflow-tooltip />
      <el-table-column label="来源会话" width="160">
        <template #default="{ row }">
          <template v-if="row.conversation_title">
            <el-tooltip :content="row.source_conversation_id" placement="top" :show-after="400">
              <span class="conv-link">{{ row.conversation_title }}</span>
            </el-tooltip>
          </template>
          <span v-else class="no-conv">-</span>
        </template>
      </el-table-column>
      <el-table-column label="重要性" prop="importance" width="72" align="center">
        <template #default="{ row }">
          <el-tag :type="row.importance >= .7 ? 'danger' : row.importance >= .4 ? 'warning' : 'success'" size="default" effect="plain">
            {{ row.importance.toFixed(1) }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="访问" prop="access_count" width="52" align="center" />
      <el-table-column label="更新时间" width="170">
        <template #default="{ row }">
          {{ formatDateTime(row.updated_at) }}
        </template>
      </el-table-column>
      <el-table-column label="删除操作" width="80" align="center">
        <template #default="{ row }">
          <el-button text size="default" type="danger" @click="handleDelete(row.id)">
            <el-icon><Delete /></el-icon>
          </el-button>
        </template>
      </el-table-column>
    </el-table>
    <el-empty v-else-if="!store.loading" description="暂无长期记忆 · 多轮对话后自动生成" class="empty" />
  </div>
</template>

<style scoped>
.mem-view { height: 100%; padding: 24px 32px; overflow-y: auto; }
.page-top { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 20px; }
.page-top h2 {
  margin: 0 0 4px; font-size: 20px; font-weight: 700;
  background: var(--grad-primary);
  -webkit-background-clip: text; background-clip: text;
  -webkit-text-fill-color: transparent;
}
.sub { margin: 0; color: var(--el-text-color-secondary); font-size: 13px; }

.stats { display: flex; gap: 12px; margin-bottom: 18px; }
.stat {
  background: var(--el-fill-color-light); border: 1px solid var(--el-border-color);
  border-radius: 10px; padding: 10px 16px; font-size: 12px; color: var(--el-text-color-secondary);
  box-shadow: var(--shadow-sm);
  transition: all .25s ease;
}
/* 统计卡片 hover 上浮 + 加深阴影 */
.stat:hover {
  transform: translateY(-2px);
  box-shadow: var(--shadow-md);
}
/* 统计数字：渐变文字 */
.stat .n {
  font-size: 20px; font-weight: 700; margin-right: 4px;
  background: var(--grad-primary);
  -webkit-background-clip: text; background-clip: text;
  -webkit-text-fill-color: transparent;
}

.filter { margin-bottom: 14px; }
.table { margin-top: 4px; }
.empty { margin-top: 60px; }
.conv-link {
  cursor: pointer;
  color: var(--el-color-primary);
  font-size: 13px;
}
.no-conv {
  color: var(--el-text-color-placeholder);
}
</style>
