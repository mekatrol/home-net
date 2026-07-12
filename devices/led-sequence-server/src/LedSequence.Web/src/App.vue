<script setup lang="ts">
import { onMounted, ref } from 'vue'

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

const controllers = ref<Record<string, ControllerDefinition>>({})
const error = ref('')

const outputEntries = (controller: ControllerDefinition) =>
  Object.entries(controller).filter((entry): entry is [string, OutputDefinition] => entry[1] != null)

onMounted(async () => {
  try {
    const response = await fetch('/api/controllers')
    if (!response.ok) throw new Error(`HTTP ${response.status}`)
    controllers.value = await response.json()
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : 'Could not load controllers'
  }
})
</script>

<template>
  <main>
    <header>
      <p class="eyebrow">Home network</p>
      <h1>LED sequence server</h1>
      <p>Readable color definitions are encoded for each controller when requested.</p>
    </header>

    <p v-if="error" class="error">{{ error }}</p>
    <section v-for="(controller, address) in controllers" :key="address" class="controller">
      <div>
        <p class="eyebrow">Controller</p>
        <h2>{{ address }}</h2>
        <code>GET /{{ address }}</code>
      </div>
      <div class="outputs">
        <article v-for="[name, output] in outputEntries(controller)" :key="name">
          <strong>{{ name }}</strong>
          <span>{{ output.ledCount }} LED{{ output.ledCount === 1 ? '' : 's' }}</span>
          <span>{{ output.format.toUpperCase() }}</span>
          <span>{{ output.frames.length }} frames · {{ output.sequenceIntervalMs }} ms</span>
        </article>
      </div>
    </section>
  </main>
</template>
