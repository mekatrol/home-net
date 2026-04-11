<script setup lang="ts">
import { storeToRefs } from 'pinia'

import { useRedirectStore } from './stores/redirects'

const redirectStore = useRedirectStore()

const { error, hasLoaded, loading, redirects, saving, success, summary, token } =
  storeToRefs(redirectStore)

const { addRedirect, addRule, loadRedirects, removeRedirect, removeRule, saveRedirects } =
  redirectStore
</script>

<template>
  <main class="shell">
    <section class="hero">
      <div>
        <p class="eyebrow">Watchdog Admin</p>
        <h1>Redirect Manager</h1>
        <p class="lede">Manage catchall delivery rules in <code>redirects_config.yaml</code>.</p>
      </div>
      <div class="summary-card">{{ summary }}</div>
    </section>

    <section class="panel auth-panel">
      <label class="field">
        <span>Web password</span>
        <input v-model="token" type="password" placeholder="Enter web.web_pwd from config.yaml">
      </label>
      <div class="auth-actions">
        <button class="secondary" @click="loadRedirects" :disabled="loading">Load</button>
        <button @click="saveRedirects" :disabled="saving || !hasLoaded">Save changes</button>
      </div>
      <p v-if="error" class="message error">{{ error }}</p>
      <p v-if="success" class="message success">{{ success }}</p>
    </section>

    <section class="panel">
      <div class="section-header">
        <div>
          <h2>Redirect destinations</h2>
          <p>Each destination gets exact-address and regex rules.</p>
        </div>
        <button @click="addRedirect">Add destination</button>
      </div>

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
  </main>
</template>
