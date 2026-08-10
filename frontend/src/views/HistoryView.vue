<script setup>
import { onMounted, ref } from 'vue'
import { get, ApiError } from '../api.js'
import { formatDistance, formatConfidence, formatDateTime, classifyDecision, decisionLabel } from '../format.js'

const FALLBACK_THRESHOLD = 0.3999

const verifications = ref([])
const loading = ref(true)
const errorMessage = ref('')
const copiedId = ref('')

function verdictKind(row) {
  return classifyDecision(row.distance, row.threshold_used ?? FALLBACK_THRESHOLD)
}

const verdictClasses = {
  valid: 'bg-valid-surface text-valid border border-valid-border',
  fraud: 'bg-fraud-surface text-fraud border border-fraud-border',
  borderline: 'bg-borderline-surface text-borderline border border-borderline-border',
}

async function copyRequestId(id) {
  try {
    await navigator.clipboard.writeText(id)
    copiedId.value = id
    setTimeout(() => {
      if (copiedId.value === id) copiedId.value = ''
    }, 1500)
  } catch {
    // Clipboard access can be denied by the browser; nothing further to do.
  }
}

onMounted(async () => {
  try {
    const data = await get('/verifications')
    verifications.value = data.verifications
  } catch (err) {
    errorMessage.value = err instanceof ApiError ? err.message : 'Failed to load history.'
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div>
    <h1 class="text-2xl font-bold text-navy mb-6">Verification History</h1>

    <div v-if="errorMessage" class="bg-danger-surface border border-danger-border text-danger text-sm rounded-lg px-4 py-3 mb-4">
      {{ errorMessage }}
    </div>

    <div v-else-if="loading" class="text-center text-ink-subtle py-12">Loading…</div>

    <div v-else-if="verifications.length === 0" class="text-center text-ink-subtle py-12 space-y-1">
      <p class="text-ink font-medium">No verifications yet</p>
      <p class="text-sm">Verified signatures will appear here after you run a verification.</p>
    </div>

    <div v-else class="bg-surface rounded-lg shadow overflow-x-auto">
      <table class="min-w-full text-sm">
        <caption class="sr-only">Verification history, most recent first</caption>
        <thead class="bg-navy text-ink-inverse">
          <tr>
            <th scope="col" class="px-4 py-3 text-left font-semibold">Verdict</th>
            <th scope="col" class="px-4 py-3 text-left font-semibold">Confidence</th>
            <th scope="col" class="px-4 py-3 text-left font-semibold">Distance</th>
            <th scope="col" class="px-4 py-3 text-left font-semibold">Model</th>
            <th scope="col" class="px-4 py-3 text-left font-semibold">Created</th>
            <!-- TODO: add a customer column once the API returns a customer identifier for each verification -->
            <th scope="col" class="px-4 py-3 text-left font-semibold">Request ID</th>
          </tr>
        </thead>
        <tbody class="divide-y divide-border">
          <tr v-for="v in verifications" :key="v.request_id">
            <td class="px-4 py-3">
              <span
                :class="['inline-block rounded-full px-3 py-1 text-xs font-bold', verdictClasses[verdictKind(v)]]"
              >
                {{ decisionLabel(verdictKind(v), v.verdict) }}
              </span>
            </td>
            <td class="px-4 py-3">{{ formatConfidence(v.confidence) }}</td>
            <td class="px-4 py-3 font-mono">{{ formatDistance(v.distance) }}</td>
            <td class="px-4 py-3">{{ v.model_version }}</td>
            <td class="px-4 py-3">{{ formatDateTime(v.created_at) }}</td>
            <td class="px-4 py-3">
              <button
                type="button"
                class="min-h-11 inline-flex items-center gap-2 font-mono text-xs text-ink-muted hover:text-navy px-2 rounded"
                :aria-label="`Copy request ID ${v.request_id}`"
                @click="copyRequestId(v.request_id)"
              >
                {{ v.request_id.slice(0, 8) }}
                <span class="text-2xs font-sans">{{ copiedId === v.request_id ? 'Copied' : 'Copy' }}</span>
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
