import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

export type RedirectRuleType = 'exact' | 'regex'

export interface RedirectRule {
  type: RedirectRuleType
  value: string
}

export interface RedirectEntry {
  catchall_email: string
  rules: RedirectRule[]
}

interface RedirectApiResponse {
  redirects: RedirectEntry[]
}

const TOKEN_STORAGE_KEY = 'redirect-manager-token'

function createEmptyRule(): RedirectRule {
  return {
    type: 'exact',
    value: '',
  }
}

function createEmptyRedirect(): RedirectEntry {
  return {
    catchall_email: '',
    rules: [createEmptyRule()],
  }
}

function cloneRedirectEntry(redirect: RedirectEntry): RedirectEntry {
  return {
    catchall_email: redirect.catchall_email ?? '',
    rules: Array.isArray(redirect.rules)
      ? redirect.rules.map((rule) => ({
          type: rule.type === 'regex' ? 'regex' : 'exact',
          value: rule.value ?? '',
        }))
      : [],
  }
}

async function readError(response: Response): Promise<string> {
  try {
    const payload = (await response.json()) as Record<string, string>
    return payload.error ?? payload.reason ?? response.statusText
  } catch {
    return response.statusText
  }
}

export const useRedirectStore = defineStore('redirects', () => {
  const token = ref<string>(localStorage.getItem(TOKEN_STORAGE_KEY) ?? '')
  const redirects = ref<RedirectEntry[]>([])
  const hasLoaded = ref(false)
  const loading = ref(false)
  const saving = ref(false)
  const error = ref('')
  const success = ref('')

  const summary = computed(() => {
    const catchallCount = redirects.value.length
    const ruleCount = redirects.value.reduce((count, redirect) => count + redirect.rules.length, 0)
    return `${catchallCount} destinations, ${ruleCount} rules`
  })

  function clearMessages(): void {
    error.value = ''
    success.value = ''
  }

  function authHeaders(): HeadersInit {
    return token.value
      ? {
          Authorization: `Bearer ${token.value}`,
          'Content-Type': 'application/json',
        }
      : { 'Content-Type': 'application/json' }
  }

  async function loadRedirects(): Promise<void> {
    clearMessages()
    loading.value = true
    try {
      const response = await fetch('/api/redirects', {
        headers: authHeaders(),
      })
      if (!response.ok) {
        throw new Error(await readError(response))
      }

      const payload = (await response.json()) as RedirectApiResponse
      redirects.value = payload.redirects.map(cloneRedirectEntry)
      hasLoaded.value = true
      localStorage.setItem(TOKEN_STORAGE_KEY, token.value)
    } catch (err) {
      error.value = err instanceof Error ? err.message : 'Failed to load redirects.'
    } finally {
      loading.value = false
    }
  }

  async function saveRedirects(): Promise<void> {
    clearMessages()
    if (!hasLoaded.value) {
      error.value = 'Load the current redirects before saving changes.'
      return
    }

    saving.value = true
    try {
      const response = await fetch('/api/redirects', {
        method: 'PUT',
        headers: authHeaders(),
        body: JSON.stringify({
          redirects: redirects.value.map((redirect) => ({
            catchall_email: redirect.catchall_email.trim(),
            rules: redirect.rules.map((rule) => ({
              type: rule.type,
              value: rule.value.trim(),
            })),
          })),
        }),
      })
      if (!response.ok) {
        throw new Error(await readError(response))
      }

      const payload = (await response.json()) as RedirectApiResponse
      redirects.value = payload.redirects.map(cloneRedirectEntry)
      localStorage.setItem(TOKEN_STORAGE_KEY, token.value)
      success.value = 'Redirect settings saved.'
    } catch (err) {
      error.value = err instanceof Error ? err.message : 'Failed to save redirects.'
    } finally {
      saving.value = false
    }
  }

  function addRedirect(): void {
    redirects.value.push(createEmptyRedirect())
  }

  function removeRedirect(index: number): void {
    redirects.value.splice(index, 1)
  }

  function addRule(redirectIndex: number): void {
    redirects.value[redirectIndex]?.rules.push(createEmptyRule())
  }

  function removeRule(redirectIndex: number, ruleIndex: number): void {
    redirects.value[redirectIndex]?.rules.splice(ruleIndex, 1)
  }

  return {
    addRedirect,
    addRule,
    error,
    hasLoaded,
    loadRedirects,
    loading,
    redirects,
    removeRedirect,
    removeRule,
    saveRedirects,
    saving,
    success,
    summary,
    token,
  }
})
