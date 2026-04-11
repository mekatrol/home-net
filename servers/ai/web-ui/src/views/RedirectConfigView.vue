<script setup lang="ts">
import { onMounted } from 'vue'
import { storeToRefs } from 'pinia'

import { useRedirectStore } from '@/stores/redirects'

const redirectStore = useRedirectStore()

const { error, redirects, saving, success } = storeToRefs(redirectStore)

const { addRedirect, addRule, loadRedirects, removeRedirect, removeRule, saveRedirects } =
  redirectStore

onMounted(() => {
  void loadRedirects()
})
</script>

<template>
  <section class="panel">
    <div class="section-header">
      <div>
        <h2>Redirect destinations</h2>
        <p>Each destination gets exact-address and regex rules.</p>
      </div>
      <div class="auth-actions">
        <button class="secondary" @click="loadRedirects">Reload</button>
        <button @click="saveRedirects" :disabled="saving">Save changes</button>
        <button @click="addRedirect">Add destination</button>
      </div>
    </div>

    <p v-if="error" class="message error section-message">{{ error }}</p>
    <p v-if="success" class="message success section-message">{{ success }}</p>

    <div v-if="!redirects.length" class="empty-state">
      No redirect destinations yet. Add one to get started.
    </div>

    <article
      v-for="(redirect, redirectIndex) in redirects"
      :key="`${redirect.catchall_email}-${redirectIndex}`"
      class="redirect-card"
    >
      <div class="redirect-header">
        <label class="field grow">
          <span>Catchall destination</span>
          <input
            v-model="redirect.catchall_email"
            type="email"
            placeholder="finance@example.com"
          >
        </label>
        <button class="danger" @click="removeRedirect(redirectIndex)">Delete</button>
      </div>

      <div class="rules">
        <div v-for="(rule, ruleIndex) in redirect.rules" :key="ruleIndex" class="rule-row">
          <label class="field compact">
            <span>Type</span>
            <select v-model="rule.type">
              <option value="exact">Exact</option>
              <option value="regex">Regex</option>
            </select>
          </label>
          <label class="field grow">
            <span>Value</span>
            <input
              v-model="rule.value"
              type="text"
              :placeholder="rule.type === 'regex' ? '^invoice-.*$' : 'accounts'"
            >
          </label>
          <button class="ghost" @click="removeRule(redirectIndex, ruleIndex)">Remove</button>
        </div>
      </div>

      <button class="secondary" @click="addRule(redirectIndex)">Add rule</button>
    </article>
  </section>
</template>
