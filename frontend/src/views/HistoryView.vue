<script setup>
import { onMounted, ref } from 'vue'
import { get, ApiError } from '../api.js'

const verifications = ref([])
const loading = ref(true)
const errorMessage = ref('')

function shortId(id) {
  return id ? id.slice(0, 8) : ''
}

function formatDistance(distance) {
  return Number(distance).toFixed(4)
}

function formatDate(isoString) {
  return new Date(isoString).toLocaleString()
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

    <div v-if="errorMessage" class="bg-red-50 border border-red-200 text-red-700 text-sm rounded-lg px-4 py-3 mb-4">
      {{ errorMessage }}
    </div>

    <div v-else-if="loading" class="text-center text-gray-500 py-12">Loading…</div>

    <div v-else-if="verifications.length === 0" class="text-center text-gray-500 py-12">
      No verifications yet
    </div>

    <div v-else class="bg-white rounded-lg shadow overflow-x-auto">
      <table class="min-w-full text-sm">
        <thead class="bg-navy text-white">
          <tr>
            <th class="px-4 py-3 text-left font-semibold">Verdict</th>
            <th class="px-4 py-3 text-left font-semibold">Confidence</th>
            <th class="px-4 py-3 text-left font-semibold">Distance</th>
            <th class="px-4 py-3 text-left font-semibold">Model</th>
            <th class="px-4 py-3 text-left font-semibold">Created</th>
            <th class="px-4 py-3 text-left font-semibold">Request ID</th>
          </tr>
        </thead>
        <tbody class="divide-y divide-gray-200">
          <tr v-for="v in verifications" :key="v.request_id">
            <td class="px-4 py-3">
              <span
                :class="[
                  'inline-block rounded-full px-3 py-1 text-xs font-bold',
                  v.verdict === 'VALID' ? 'bg-brand-green/20 text-green-700' : 'bg-red-100 text-red-700',
                ]"
              >
                {{ v.verdict }}
              </span>
            </td>
            <td class="px-4 py-3">{{ v.confidence.toFixed(1) }}%</td>
            <td class="px-4 py-3 font-mono">{{ formatDistance(v.distance) }}</td>
            <td class="px-4 py-3">{{ v.model_version }}</td>
            <td class="px-4 py-3">{{ formatDate(v.created_at) }}</td>
            <td class="px-4 py-3 font-mono" :title="v.request_id">{{ shortId(v.request_id) }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
