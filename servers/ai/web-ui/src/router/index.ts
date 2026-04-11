import { createRouter, createWebHistory } from 'vue-router'

import AdminLayout from '@/layouts/AdminLayout.vue'
import { pinia } from '@/pinia'
import { useRedirectStore } from '@/stores/redirects'
import DroppedEmailsView from '@/views/DroppedEmailsView.vue'
import RedirectConfigView from '@/views/RedirectConfigView.vue'
import SignInView from '@/views/SignInView.vue'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/',
      redirect: '/sign-in',
    },
    {
      path: '/sign-in',
      name: 'sign-in',
      component: SignInView,
      meta: { guestOnly: true },
    },
    {
      path: '/',
      component: AdminLayout,
      meta: { requiresAuth: true },
      children: [
        {
          path: 'dropped',
          name: 'dropped-emails',
          component: DroppedEmailsView,
        },
        {
          path: 'redirects',
          name: 'redirect-config',
          component: RedirectConfigView,
        },
      ],
    },
  ],
})

router.beforeEach((to) => {
  const redirectStore = useRedirectStore(pinia)

  if (to.meta.requiresAuth && !redirectStore.isAuthenticated) {
    return { name: 'sign-in' }
  }

  if (to.meta.guestOnly && redirectStore.isAuthenticated) {
    return { name: 'dropped-emails' }
  }

  return true
})

export default router
