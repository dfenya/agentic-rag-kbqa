import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      component: () => import('@/layouts/AppLayout.vue'),
      children: [
        {
          path: '',
          redirect: '/chat',
        },
        {
          // /chat 和 /chat/:id 共用同一个路由和组件实例，避免导航时组件重建导致消息丢失
          path: '/chat/:id?',
          name: 'chat',
          component: () => import('@/views/ChatView.vue'),
        },
        {
          path: '/knowledge',
          name: 'documents',
          component: () => import('@/views/DocumentsView.vue'),
        },
        {
          path: '/settings',
          name: 'settings',
          component: () => import('@/views/SettingsView.vue'),
        },
        {
          path: '/memory',
          name: 'memory',
          component: () => import('@/views/MemoryView.vue'),
        },
      ],
    },
  ],
})

export default router
