<script setup lang="ts">
import { getSettings } from '@/api/client'

const token = localStorage.getItem('token')
if (token) {
  getSettings().then(s => {
    if (s.dark_mode) {
      document.documentElement.classList.add('dark')
    }
  }).catch(() => {})
}
</script>

<template>
  <el-config-provider>
    <RouterView />
  </el-config-provider>
</template>
