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

export interface DroppedEmailEntry {
  filename: string
  recipient: string
  sender: string
  received_at: string
}

interface RedirectApiResponse {
  redirects: RedirectEntry[]
}

interface DroppedEmailApiResponse {
  emails: DroppedEmailEntry[]
}

interface DeleteDroppedEmailApiResponse {
  deleted: string[]
  skipped: string[]
}

const TOKEN_STORAGE_KEY = 'redirect-manager-token'
const API_BASE_URL = __API_BASE_URL__

function apiUrl(path: string): string {
  return `${API_BASE_URL}${path}`
}

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

function cloneDroppedEmailEntry(email: DroppedEmailEntry): DroppedEmailEntry {
  return {
    filename: email.filename ?? '',
    recipient: email.recipient ?? '',
    sender: email.sender ?? '',
    received_at: email.received_at ?? '',
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
  const droppedEmails = ref<DroppedEmailEntry[]>([])
  const hasLoaded = ref(false)
  const loading = ref(false)
  const saving = ref(false)
  const deletingDroppedEmails = ref(false)
  const error = ref('')
  const success = ref('')

  const summary = computed(() => {
    const catchallCount = redirects.value.length
    const ruleCount = redirects.value.reduce((count, redirect) => count + redirect.rules.length, 0)
    return `${catchallCount} destinations, ${ruleCount} rules, ${droppedEmails.value.length} dropped`
  })

  const isAuthenticated = computed(() => hasLoaded.value && Boolean(token.value))

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

  async function loadRedirects(): Promise<boolean> {
    try {
      const response = await fetch(apiUrl('/api/redirects'), {
        headers: authHeaders(),
      })
      if (!response.ok) {
        throw new Error(await readError(response))
      }

      const payload = (await response.json()) as RedirectApiResponse
      redirects.value = payload.redirects.map(cloneRedirectEntry)
      return true
    } catch (err) {
      error.value = err instanceof Error ? err.message : 'Failed to load redirects.'
      return false
    }
  }

  async function loadDroppedEmails(): Promise<boolean> {
    try {
      const response = await fetch(apiUrl('/api/dropped-emails'), {
        headers: authHeaders(),
      })
      if (!response.ok) {
        throw new Error(await readError(response))
      }

      const payload = (await response.json()) as DroppedEmailApiResponse
      droppedEmails.value = payload.emails.map(cloneDroppedEmailEntry)
      return true
    } catch (err) {
      error.value = err instanceof Error ? err.message : 'Failed to load dropped emails.'
      return false
    }
  }

  async function loadAdminData(): Promise<boolean> {
    clearMessages()
    loading.value = true
    try {
      const [redirectsLoaded, droppedLoaded] = await Promise.all([
        loadRedirects(),
        loadDroppedEmails(),
      ])
      hasLoaded.value = redirectsLoaded && droppedLoaded
      if (hasLoaded.value) {
        localStorage.setItem(TOKEN_STORAGE_KEY, token.value)
      }
      return hasLoaded.value
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
      const response = await fetch(apiUrl('/api/redirects'), {
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

  async function deleteDroppedEmailSelection(filenames: string[]): Promise<void> {
    clearMessages()
    if (!filenames.length) {
      return
    }

    deletingDroppedEmails.value = true
    try {
      const response = await fetch(apiUrl('/api/dropped-emails/delete'), {
        method: 'POST',
        headers: authHeaders(),
        body: JSON.stringify({ filenames }),
      })
      if (!response.ok) {
        throw new Error(await readError(response))
      }

      const payload = (await response.json()) as DeleteDroppedEmailApiResponse
      const deletedSet = new Set(payload.deleted)
      droppedEmails.value = droppedEmails.value.filter((email) => !deletedSet.has(email.filename))
      success.value =
        payload.deleted.length > 0
          ? `Deleted ${payload.deleted.length} dropped email${payload.deleted.length === 1 ? '' : 's'}.`
          : 'No dropped emails were deleted.'
      if (payload.skipped.length > 0) {
        error.value = `Skipped ${payload.skipped.length} file${payload.skipped.length === 1 ? '' : 's'} that could not be deleted.`
      }
    } catch (err) {
      error.value = err instanceof Error ? err.message : 'Failed to delete dropped emails.'
    } finally {
      deletingDroppedEmails.value = false
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

  function signOut(): void {
    token.value = ''
    redirects.value = []
    droppedEmails.value = []
    hasLoaded.value = false
    clearMessages()
    localStorage.removeItem(TOKEN_STORAGE_KEY)
  }

  return {
    addRedirect,
    addRule,
    deleteDroppedEmailSelection,
    deletingDroppedEmails,
    droppedEmails,
    error,
    hasLoaded,
    isAuthenticated,
    loadAdminData,
    loadDroppedEmails,
    loadRedirects,
    loading,
    redirects,
    removeRedirect,
    removeRule,
    saveRedirects,
    saving,
    signOut,
    success,
    summary,
    token,
  }
})
