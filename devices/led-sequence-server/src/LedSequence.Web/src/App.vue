<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'

type FrameDefinition = { fill?: string; pixels?: string[] }
type OutputDefinition = {
  sequenceIntervalMs: number
  format: string
  ledCount: number
  frames: FrameDefinition[]
}
type ControllerDefinition = {
  onboard?: OutputDefinition | null
  string1?: OutputDefinition | null
  string2?: OutputDefinition | null
  string3?: OutputDefinition | null
  string4?: OutputDefinition | null
}
type ControllerForm = {
  address: string
  ledCount: number
  color: string
}

const controllers = ref<Record<string, ControllerDefinition>>({})
const form = reactive<ControllerForm>({ address: '', ledCount: 30, color: '#00b4ff' })
const editingAddress = ref<string | null>(null)
const error = ref('')
const success = ref('')
const isLoading = ref(true)
const isSaving = ref(false)

const outputEntries = (controller: ControllerDefinition) =>
  Object.entries(controller).filter((entry): entry is [string, OutputDefinition] => entry[1] != null)

const request = async (url: string, options?: RequestInit) => {
  const response = await fetch(url, options)
  if (response.ok) return response

  const body = await response.json().catch(() => null) as { error?: string } | null
  throw new Error(body?.error ?? `Request failed with HTTP ${response.status}`)
}

const loadControllers = async () => {
  isLoading.value = true
  error.value = ''
  try {
    const response = await request('/api/controllers')
    controllers.value = await response.json()
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : 'Could not load controllers'
  } finally {
    isLoading.value = false
  }
}

const resetForm = () => {
  editingAddress.value = null
  form.address = ''
  form.ledCount = 30
  form.color = '#00b4ff'
}

const editController = (address: string, controller: ControllerDefinition) => {
  const output = controller.string1
  editingAddress.value = address
  form.address = address
  form.ledCount = output?.ledCount ?? 30
  form.color = output?.frames[0]?.fill ?? '#00b4ff'
  error.value = ''
  success.value = ''
  window.scrollTo({ top: 0, behavior: 'smooth' })
}

const saveController = async () => {
  isSaving.value = true
  error.value = ''
  success.value = ''

  const definition: ControllerDefinition = {
    ...(editingAddress.value ? controllers.value[editingAddress.value] : {}),
    string1: {
      sequenceIntervalMs: 1000,
      format: 'grb',
      ledCount: form.ledCount,
      frames: [{ fill: form.color }],
    },
  }

  try {
    if (editingAddress.value) {
      await request(`/api/controllers/${encodeURIComponent(editingAddress.value)}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(definition),
      })
      success.value = `Updated ${editingAddress.value}.`
    } else {
      await request('/api/controllers', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ address: form.address, definition }),
      })
      success.value = `Added ${form.address}.`
    }

    resetForm()
    await loadControllers()
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : 'Could not save the controller'
  } finally {
    isSaving.value = false
  }
}

const deleteController = async (address: string) => {
  if (!window.confirm(`Delete the configuration for ${address}?`)) return

  error.value = ''
  success.value = ''
  try {
    await request(`/api/controllers/${encodeURIComponent(address)}`, { method: 'DELETE' })
    success.value = `Deleted ${address}.`
    if (editingAddress.value === address) resetForm()
    await loadControllers()
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : 'Could not delete the controller'
  }
}

onMounted(loadControllers)
</script>

<template>
  <main>
    <header>
      <p class="eyebrow">Home network</p>
      <h1>LED controllers</h1>
      <p>Add a controller and choose the solid color shown on its LED string.</p>
    </header>

    <section class="editor" aria-labelledby="editor-title">
      <div>
        <p class="eyebrow">{{ editingAddress ? 'Edit controller' : 'New controller' }}</p>
        <h2 id="editor-title">{{ editingAddress ?? 'Configure a controller' }}</h2>
        <p>String 1 uses GRB color order and refreshes every second.</p>
      </div>

      <form @submit.prevent="saveController">
        <label>
          Controller IP address
          <input
            v-model.trim="form.address"
            type="text"
            inputmode="decimal"
            placeholder="10.2.2.80"
            required
            :disabled="editingAddress !== null"
            pattern="(?:[0-9]{1,3}\.){3}[0-9]{1,3}"
          >
        </label>
        <label>
          LED string length
          <input v-model.number="form.ledCount" type="number" min="1" max="2048" required>
        </label>
        <label>
          Solid color
          <span class="color-control">
            <input v-model="form.color" type="color" aria-label="Solid color picker">
            <input v-model.trim="form.color" type="text" pattern="#[0-9a-fA-F]{6}" required aria-label="Solid color hex value">
          </span>
        </label>
        <div class="form-actions">
          <button type="submit" :disabled="isSaving">
            {{ isSaving ? 'Saving…' : editingAddress ? 'Save changes' : 'Add controller' }}
          </button>
          <button v-if="editingAddress" type="button" class="button-secondary" @click="resetForm">Cancel</button>
        </div>
      </form>
    </section>

    <p v-if="error" class="notice error" role="alert">{{ error }}</p>
    <p v-if="success" class="notice success" role="status">{{ success }}</p>

    <div class="section-heading">
      <div>
        <p class="eyebrow">Saved configurations</p>
        <h2>Controllers</h2>
      </div>
      <span>{{ Object.keys(controllers).length }} total</span>
    </div>

    <p v-if="isLoading" class="empty-state">Loading controllers…</p>
    <p v-else-if="Object.keys(controllers).length === 0" class="empty-state">No controllers configured yet.</p>
    <section v-for="(controller, address) in controllers" v-else :key="address" class="controller">
      <div class="controller-summary">
        <p class="eyebrow">Controller</p>
        <h2>{{ address }}</h2>
        <code>GET /{{ address }}</code>
        <div class="controller-actions">
          <button type="button" class="button-secondary" @click="editController(address, controller)">Edit</button>
          <button type="button" class="button-danger" @click="deleteController(address)">Delete</button>
        </div>
      </div>
      <div class="outputs">
        <article v-for="[name, output] in outputEntries(controller)" :key="name">
          <span class="color-swatch" :style="{ backgroundColor: output.frames[0]?.fill ?? '#000000' }" aria-hidden="true"></span>
          <strong>{{ name }}</strong>
          <span>{{ output.ledCount }} LED{{ output.ledCount === 1 ? '' : 's' }}</span>
          <span>{{ output.frames[0]?.fill ?? 'Pixel sequence' }}</span>
          <span>{{ output.format.toUpperCase() }} · {{ output.sequenceIntervalMs }} ms</span>
        </article>
      </div>
    </section>
  </main>
</template>
