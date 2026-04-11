<script setup lang="ts">
import { storeToRefs } from 'pinia'
import { useRouter } from 'vue-router'

import { useRedirectStore } from '@/stores/redirects'

const redirectStore = useRedirectStore()
const router = useRouter()

const { error, loading, success, token } = storeToRefs(redirectStore)

async function signIn(): Promise<void> {
  const signedIn = await redirectStore.loadAdminData()
  if (signedIn) {
    void router.push('/redirects')
  }
}
</script>

<template>
  <main class="shell shell-narrow">
    <section class="hero hero-signin">
      <div>
        <p class="eyebrow">Watchdog Admin</p>
        <h1>Sign In</h1>
        <p class="lede">Use the configured web password to access dropped emails and redirects.</p>
      </div>
    </section>

    <section class="panel auth-panel auth-panel-stacked">
      <label class="field">
        <span>Web password</span>
        <input
          v-model="token"
          type="password"
          placeholder="Enter web.web_pwd from config.yaml"
          @keyup.enter="signIn"
        >
      </label>
      <div class="auth-actions">
        <button @click="signIn" :disabled="loading">Sign in</button>
      </div>
      <p v-if="error" class="message error">{{ error }}</p>
      <p v-if="success" class="message success">{{ success }}</p>
    </section>
  </main>
</template>
