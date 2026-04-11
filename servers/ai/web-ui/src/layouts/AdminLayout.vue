<script setup lang="ts">
import { computed } from 'vue'
import { RouterLink, RouterView, useRouter } from 'vue-router'
import { storeToRefs } from 'pinia'

import { useRedirectStore } from '@/stores/redirects'

const redirectStore = useRedirectStore()
const router = useRouter()

const { summary } = storeToRefs(redirectStore)

const navItems = computed(() => [
  { label: 'Dropped Emails', to: '/dropped' },
  { label: 'Redirect Configuration', to: '/redirects' },
])

function signOut(): void {
  redirectStore.signOut()
  void router.push('/sign-in')
}
</script>

<template>
  <main class="shell">
    <header class="topbar">
      <div>
        <p class="eyebrow">Watchdog Admin</p>
        <h1 class="page-title">Email Console</h1>
      </div>
      <div class="topbar-actions">
        <nav class="topnav" aria-label="Primary">
          <RouterLink
            v-for="item in navItems"
            :key="item.to"
            :to="item.to"
            class="topnav-link"
            active-class="is-active"
          >
            {{ item.label }}
          </RouterLink>
        </nav>
        <div class="summary-card">{{ summary }}</div>
        <button class="secondary" @click="signOut">Sign out</button>
      </div>
    </header>

    <RouterView />
  </main>
</template>
