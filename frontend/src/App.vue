<script setup lang="ts">
import { useDark, useToggle } from '@vueuse/core'

const isDark = useDark()
const toggleDark = useToggle(isDark)

// 暴露给设置页使用
provide('isDark', isDark)
provide('toggleDark', toggleDark)
</script>

<template>
  <el-config-provider>
    <RouterView />
  </el-config-provider>
</template>
