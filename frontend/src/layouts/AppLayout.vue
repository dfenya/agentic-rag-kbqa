<script setup lang="ts">
import { ref, provide } from 'vue'
import { RouterView } from 'vue-router'
import Sidebar from '@/components/common/Sidebar.vue'

// 侧边栏折叠状态提升到布局层，供 Sidebar 和 ChatView 共享
const sidebarCollapsed = ref(false)
provide('sidebarCollapsed', sidebarCollapsed)
</script>

<template>
  <el-container class="app-layout">
    <Sidebar />
    <el-main class="main-content">
      <RouterView v-slot="{ Component }">
        <Transition name="page" mode="out-in">
          <component :is="Component" />
        </Transition>
      </RouterView>
    </el-main>
  </el-container>
</template>

<style scoped>
.app-layout {
  height: 100vh;
}
.main-content {
  height: 100vh;
  overflow: hidden;
  padding: 0;
}
</style>
