import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/login',
      name: 'login',
      component: () => import('@/views/LoginView.vue'),
    },
    {
      path: '/',
      component: () => import('@/layouts/AppLayout.vue'),
      children: [
        { path: '', redirect: '/chat' },
        { path: '/chat/:id?', name: 'chat', component: () => import('@/views/ChatView.vue') },
        { path: '/knowledge', name: 'documents', component: () => import('@/views/DocumentsView.vue') },
        { path: '/settings', name: 'settings', component: () => import('@/views/SettingsView.vue') },
        { path: '/memory', name: 'memory', component: () => import('@/views/MemoryView.vue') },
      ],
    },
  ],
})

router.beforeEach((to) => {
  const token = localStorage.getItem('token')
  if (!token && to.path !== '/login') {
    return '/login'
  }
  if (token && to.path === '/login') {
    return '/'
  }
})

export default router
