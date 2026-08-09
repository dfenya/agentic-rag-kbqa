<script setup lang="ts">
import { ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import {
  ChatDotRound,
  Document,
  Setting,
  Plus,
  Collection,
  Fold,
  Expand,
  Loading,
  Delete,
} from '@element-plus/icons-vue'
import { useConversationsStore } from '@/stores/conversations'
import { useChatStore } from '@/stores/chat'
import { formatDateTime } from '@/utils/datetime'
import { BRAND } from '@/config/brand'

const router = useRouter()
const route = useRoute()
const conversationsStore = useConversationsStore()
const chatStore = useChatStore()

const collapsed = inject('sidebarCollapsed', ref(false))
const creating = ref(false)

onMounted(() => conversationsStore.fetchConversations())

const menuOptions = [
  { label: '对话',   path: '/chat',     icon: ChatDotRound },
  { label: '知识库', path: '/knowledge', icon: Document },
  { label: '记忆',   path: '/memory',    icon: Collection },
  { label: '设置',   path: '/settings',  icon: Setting },
]

// 当前激活的菜单路径（/chat/:id 也高亮「对话」）
const activePath = computed(() => {
  const p = route.path
  if (p.startsWith('/chat')) return '/chat'
  if (p.startsWith('/knowledge')) return '/knowledge'
  if (p.startsWith('/memory')) return '/memory'
  if (p.startsWith('/settings')) return '/settings'
  return '/chat'
})

// 豆包式新建：先在后端落库创建空对话，再导航到该对话。
// createConversation 会乐观插入到侧边栏头部，因此点完即刻可见。
async function newConversation() {
  if (creating.value) return
  creating.value = true
  try {
    const conv = await conversationsStore.createConversation()
    if (conv) {
      router.push({ name: 'chat', params: { id: conv.id } })
    }
  } finally {
    creating.value = false
  }
}

async function deleteConversation(id: string) {
  await conversationsStore.deleteConversation(id)
  if (route.params.id === id) {
    // 删除当前对话后，自动新建一个空对话并进入（豆包式体验）
    const conv = await conversationsStore.createConversation()
    if (conv) {
      router.push({ name: 'chat', params: { id: conv.id } })
    } else {
      chatStore.clearMessages()
      router.push({ name: 'chat' })
    }
  }
}

function formatTime(dateStr: string) {
  return formatDateTime(dateStr)
}
</script>

<template>
  <el-aside :width="collapsed ? '64px' : '260px'" class="sidebar">
    <!-- 折叠按钮 -->
    <div class="toggle-bar" :class="{ collapsed }">
      <el-button text size="default" @click="collapsed = !collapsed" class="toggle-btn">
        <el-icon :size="18"><Fold v-if="!collapsed" /><Expand v-else /></el-icon>
      </el-button>
    </div>

    <!-- 品牌 -->
    <div class="brand-area" :class="{ collapsed }">
      <div class="brand" @click="newConversation">
        <span class="brand-logo">{{ BRAND.sidebarLogo }}</span>
        <div v-if="!collapsed" class="brand-text">
          <div class="brand-name">{{ BRAND.sidebarName }}</div>
          <div class="brand-ver">{{ BRAND.sidebarVersion }}</div>
        </div>
      </div>

      <!-- 展开：完整按钮 -->
      <el-button
        v-if="!collapsed"
        type="primary" class="new-btn"
        @click="newConversation"
      >
        <template #icon><el-icon><Plus /></el-icon></template>
        新对话
      </el-button>

      <!-- 折叠：仅图标按钮 -->
      <div v-else class="collapsed-actions">
        <el-button type="primary" circle size="default" @click="newConversation">
          <el-icon><Plus /></el-icon>
        </el-button>
      </div>
    </div>

    <!-- 历史对话（仅展开时） -->
    <div v-if="!collapsed" class="conv-section">
      <div class="section-label">
        历史对话
        <el-icon v-if="conversationsStore.loading" class="is-loading" :size="12">
          <Loading />
        </el-icon>
      </div>
      <el-scrollbar class="conv-list">
        <div
          v-for="conv in conversationsStore.conversations"
          :key="conv.id"
          class="conv-item"
          :class="{ active: route.params.id === conv.id }"
          @click="router.push({ name: 'chat', params: { id: conv.id } })"
        >
          <div class="conv-main">
            <div class="conv-title">{{ conv.title || '新对话' }}</div>
            <div class="conv-preview">{{ conv.last_message_preview || '暂无消息' }}</div>
          </div>
          <div class="conv-right">
            <span class="conv-time">{{ formatTime(conv.updated_at) }}</span>
            <button class="conv-del" @click.stop="deleteConversation(conv.id)" title="删除">
              <el-icon :size="14"><Delete /></el-icon>
            </button>
          </div>
        </div>
        <div v-if="!conversationsStore.loading && !conversationsStore.conversations.length" class="conv-empty">
          暂无对话记录
        </div>
      </el-scrollbar>
    </div>

    <!-- 导航：使用 Element Plus 的 el-menu，原生支持折叠（折叠时仅显示图标） -->
    <el-menu
      :default-active="activePath"
      :collapse="collapsed"
      :collapse-transition="false"
      router
      class="nav-menu"
    >
      <el-menu-item
        v-for="m in menuOptions"
        :key="m.path"
        :index="m.path"
      >
        <el-icon><component :is="m.icon" /></el-icon>
        <template #title>{{ m.label }}</template>
      </el-menu-item>
    </el-menu>

    <!-- 底部（仅展开时） -->
    <div v-if="!collapsed" class="sidebar-foot">
      Ollama · 本地模型
    </div>
  </el-aside>
</template>

<style scoped>
.sidebar {
  display: flex;
  flex-direction: column;
  height: 100vh;
  background: var(--el-bg-color-page);
  transition: width .25s ease;
  overflow: hidden;
}

/* 折叠按钮 */
.toggle-bar {
  display: flex;
  justify-content: flex-end;
  padding: 8px 10px 0;
}
.toggle-bar.collapsed {
  justify-content: center;
  padding: 8px 0 0;
}
.toggle-btn {
  color: var(--el-text-color-secondary);
  transition: all .2s;
}
.toggle-btn:hover {
  color: var(--el-color-primary);
  transform: scale(1.1);
}

/* 品牌 */
.brand-area {
  padding: 4px 14px 14px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.brand-area.collapsed {
  padding: 4px 8px 8px;
  align-items: center;
  gap: 10px;
}

.brand {
  display: flex;
  align-items: center;
  gap: 10px;
  cursor: pointer;
  transition: opacity .2s;
}
.brand:hover { opacity: .85; }

.brand-logo {
  font-size: 26px;
  line-height: 1;
  flex-shrink: 0;
  width: 38px;
  height: 38px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 10px;
  background: var(--grad-primary-soft);
  box-shadow: var(--shadow-sm);
}

.brand-text {
  min-width: 0;
}

.brand-name {
  font-size: 16px;
  font-weight: 700;
  background: var(--grad-primary);
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
  line-height: 1.3;
}

.brand-ver {
  font-size: 10px;
  color: var(--el-text-color-secondary);
  letter-spacing: .5px;
}

.new-btn {
  border-radius: 12px;
  box-shadow: var(--shadow-primary);
  transition: all .25s;
}
.new-btn:hover {
  box-shadow: var(--shadow-primary-hover);
  transform: translateY(-1px);
}

.collapsed-actions {
  display: flex;
  justify-content: center;
}

/* 历史对话（仅展开时） */
.conv-section {
  flex: 1;
  padding: 0 10px;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.section-label {
  font-size: 10px;
  font-weight: 700;
  color: var(--el-text-color-secondary);
  padding: 6px 10px 8px;
  text-transform: uppercase;
  letter-spacing: 1px;
  display: flex;
  align-items: center;
  gap: 6px;
}

.conv-list {
  flex: 1;
  min-height: 0;
}

.conv-item {
  padding: 10px 12px;
  border-radius: 10px;
  cursor: pointer;
  display: flex;
  justify-content: space-between;
  gap: 8px;
  transition: all .2s ease;
  margin-bottom: 1px;
  position: relative;
}
.conv-item:hover {
  background: var(--el-fill-color);
  transform: translateX(2px);
}
.conv-item.active {
  background: var(--grad-primary-soft);
  border-left: 3px solid var(--el-color-primary);
  padding-left: 9px;
}

.conv-main { flex: 1; min-width: 0; }

.conv-title {
  font-size: 13px; font-weight: 500;
  color: var(--el-text-color-primary);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}

.conv-preview {
  font-size: 11px; color: var(--el-text-color-secondary);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  margin-top: 2px;
}

.conv-right {
  display: flex; flex-direction: column;
  align-items: flex-end; gap: 4px; flex-shrink: 0;
}

.conv-time { font-size: 10px; color: var(--el-text-color-secondary); }

.conv-del {
  background: none; border: none; cursor: pointer;
  color: var(--el-text-color-secondary); padding: 2px; border-radius: 4px;
  opacity: 0; transition: all .15s; display: flex;
}
.conv-item:hover .conv-del { opacity: .5; }
.conv-item:hover .conv-del:hover { opacity: 1; color: #ef4444; }

.conv-empty {
  text-align: center; color: var(--el-text-color-secondary);
  font-size: 12px; padding: 24px 0;
}

/* 导航：el-menu 定制（背景透明，继承 sidebar 的背景色） */
.nav-menu {
  border-right: none;
  border-top: 1px solid var(--el-border-color);
  padding: 6px 8px;
  background: transparent;
}
.nav-menu:not(.el-menu--collapse) {
  width: 100%;
}
.nav-menu :deep(.el-menu-item) {
  height: 42px;
  line-height: 42px;
  border-radius: 10px;
  margin-bottom: 2px;
}
/* 折叠状态下图标居中 */
.nav-menu.el-menu--collapse :deep(.el-menu-item) {
  text-align: center;
  padding: 0 !important;
  justify-content: center !important;
}
.nav-menu.el-menu--collapse :deep(.el-menu-item .el-icon) {
  margin: 0 !important;
}
.nav-menu.el-menu--collapse :deep(.el-menu-tooltip__trigger) {
  padding: 0 !important;
  width: 100% !important;
  justify-content: center !important;
}
.nav-menu :deep(.el-menu-item.is-active) {
  background: var(--grad-primary-soft);
  color: var(--el-color-primary);
  font-weight: 600;
}
html.dark .nav-menu :deep(.el-menu-item.is-active) {
  color: var(--el-color-primary-light-5);
}

/* 底部 */
.sidebar-foot {
  padding: 8px 14px 12px;
  text-align: center; font-size: 10px;
  color: var(--el-text-color-secondary); letter-spacing: .5px;
}
</style>
