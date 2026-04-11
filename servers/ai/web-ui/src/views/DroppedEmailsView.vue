<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'

import { useRedirectStore } from '@/stores/redirects'

const redirectStore = useRedirectStore()

const {
  continuingDroppedEmails,
  deletingDroppedEmails,
  droppedEmails,
  error,
  hasLoaded,
  success,
  token,
} =
  storeToRefs(redirectStore)

const { continueDroppedEmailSelection, deleteDroppedEmailSelection, loadDroppedEmails } =
  redirectStore

const selectedDroppedFilenames = ref<string[]>([])
let droppedEmailRefreshTimer: number | null = null

const allDroppedSelected = computed({
  get: () =>
    droppedEmails.value.length > 0 &&
    selectedDroppedFilenames.value.length === droppedEmails.value.length,
  set: (checked: boolean) => {
    selectedDroppedFilenames.value = checked ? droppedEmails.value.map((email) => email.filename) : []
  },
})

const hasDroppedSelection = computed(() => selectedDroppedFilenames.value.length > 0)

watch(droppedEmails, (emails) => {
  const available = new Set(emails.map((email) => email.filename))
  selectedDroppedFilenames.value = selectedDroppedFilenames.value.filter((filename) =>
    available.has(filename),
  )
})

function toggleDroppedSelection(filename: string, checked: boolean): void {
  if (checked) {
    if (!selectedDroppedFilenames.value.includes(filename)) {
      selectedDroppedFilenames.value = [...selectedDroppedFilenames.value, filename]
    }
    return
  }

  selectedDroppedFilenames.value = selectedDroppedFilenames.value.filter(
    (selected) => selected !== filename,
  )
}

function handleDroppedSelectionChange(filename: string, event: Event): void {
  toggleDroppedSelection(filename, (event.target as HTMLInputElement).checked)
}

async function deleteSelectedDroppedEmails(): Promise<void> {
  const filenames = [...selectedDroppedFilenames.value]
  await deleteDroppedEmailSelection(filenames)
  selectedDroppedFilenames.value = selectedDroppedFilenames.value.filter(
    (filename) => !filenames.includes(filename),
  )
}

async function continueSelectedDroppedEmails(): Promise<void> {
  const filenames = [...selectedDroppedFilenames.value]
  await continueDroppedEmailSelection(filenames)
  selectedDroppedFilenames.value = selectedDroppedFilenames.value.filter(
    (filename) => !filenames.includes(filename),
  )
}

function formatReceivedAt(value: string): string {
  if (!value) {
    return 'Unknown'
  }

  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) {
    return value
  }

  return new Intl.DateTimeFormat(undefined, {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(parsed)
}

function stopDroppedEmailRefresh(): void {
  if (droppedEmailRefreshTimer !== null) {
    window.clearInterval(droppedEmailRefreshTimer)
    droppedEmailRefreshTimer = null
  }
}

function startDroppedEmailRefresh(): void {
  stopDroppedEmailRefresh()
  droppedEmailRefreshTimer = window.setInterval(() => {
    if (
      !hasLoaded.value ||
      !token.value ||
      deletingDroppedEmails.value ||
      continuingDroppedEmails.value
    ) {
      return
    }
    void loadDroppedEmails()
  }, 2000)
}

onMounted(() => {
  void loadDroppedEmails()
  startDroppedEmailRefresh()
})

onBeforeUnmount(() => {
  stopDroppedEmailRefresh()
})
</script>

<template>
  <section class="panel">
    <div class="section-header">
      <div>
        <h2>Dropped emails</h2>
        <p>Newest first. Select rows to continue through processing or remove them permanently.</p>
      </div>
      <div class="auth-actions">
        <button
          class="secondary"
          @click="continueSelectedDroppedEmails"
          :disabled="continuingDroppedEmails || deletingDroppedEmails || !hasDroppedSelection"
        >
          Continue processing
        </button>
        <button
          class="danger"
          @click="deleteSelectedDroppedEmails"
          :disabled="continuingDroppedEmails || deletingDroppedEmails || !hasDroppedSelection"
        >
          Delete selected
        </button>
      </div>
    </div>

    <p v-if="error" class="message error section-message">{{ error }}</p>
    <p v-if="success" class="message success section-message">{{ success }}</p>

    <div v-if="!droppedEmails.length" class="empty-state">
      No dropped emails found.
    </div>

    <div v-else class="table-wrap">
      <table class="dropped-table">
        <thead>
          <tr>
            <th class="checkbox-col">
              <input v-model="allDroppedSelected" type="checkbox" aria-label="Select all dropped emails">
            </th>
            <th>Recipient</th>
            <th>Sender</th>
            <th>Received</th>
            <th>File name</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="email in droppedEmails" :key="email.filename">
            <td class="checkbox-col">
              <input
                :checked="selectedDroppedFilenames.includes(email.filename)"
                type="checkbox"
                :aria-label="`Select ${email.filename}`"
                @change="handleDroppedSelectionChange(email.filename, $event)"
              >
            </td>
            <td>{{ email.recipient || 'Unknown' }}</td>
            <td>{{ email.sender || 'Unknown' }}</td>
            <td>{{ formatReceivedAt(email.received_at) }}</td>
            <td><code>{{ email.filename }}</code></td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>
