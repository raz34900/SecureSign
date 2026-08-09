<script setup>
import { ref, onMounted } from 'vue'
import { get, ApiError } from '../api.js'

const RECENT_KEY = 'ss_recent_customers'

const lookupId = ref('')
const loading = ref(false)
const notice = ref(null) // { level: 'warning' | 'error', message }

const customer = ref(null)
const references = ref([])

const recent = ref([])

function loadRecent() {
  try {
    const list = JSON.parse(localStorage.getItem(RECENT_KEY) || '[]')
    recent.value = Array.isArray(list) ? list : []
  } catch {
    recent.value = []
  }
}

onMounted(loadRecent)

async function loadCustomer(id) {
  const targetId = (id ?? lookupId.value).trim()
  if (!targetId) return

  lookupId.value = targetId
  loading.value = true
  notice.value = null
  customer.value = null
  references.value = []

  try {
    const customerRes = await get(`/customers/${targetId}`)
    customer.value = customerRes

    const referencesRes = await get(`/customers/${targetId}/references`)
    references.value = referencesRes.references
  } catch (err) {
    if (err instanceof ApiError && (err.code === 'CUSTOMER_NOT_FOUND' || err.status === 404)) {
      notice.value = { level: 'warning', message: 'Not found or belongs to another organisation.' }
    } else {
      notice.value = { level: 'error', message: err.message || 'Failed to load customer.' }
    }
  } finally {
    loading.value = false
  }
}

function selectRecent(entry) {
  loadCustomer(entry.customer_id)
}

function shortId(id) {
  return id ? id.slice(0, 8) : ''
}
</script>

<template>
  <div class="max-w-3xl mx-auto space-y-8">
    <h1 class="text-2xl font-bold text-navy">Customers</h1>

    <div class="bg-white rounded-lg shadow p-6 space-y-3">
      <label class="block text-sm font-medium text-gray-700">Customer ID</label>
      <div class="flex gap-2">
        <input
          v-model="lookupId"
          type="text"
          placeholder="Customer UUID"
          class="flex-1 rounded-lg border border-gray-300 px-3 py-2 focus:outline-none focus:ring-2 focus:ring-navy"
          @keyup.enter="loadCustomer()"
        />
        <button
          type="button"
          :disabled="!lookupId.trim() || loading"
          class="bg-brand-green text-navy font-semibold rounded-lg px-4 py-2 disabled:opacity-50 disabled:cursor-not-allowed"
          @click="loadCustomer()"
        >
          {{ loading ? 'Loading…' : 'Load' }}
        </button>
      </div>

      <div
        v-if="notice"
        :class="notice.level === 'warning'
          ? 'border-amber-400 bg-amber-50 text-amber-800'
          : 'border-red-400 bg-red-50 text-red-800'"
        class="rounded-lg border px-4 py-3 text-sm"
      >
        {{ notice.message }}
      </div>
    </div>

    <div v-if="recent.length > 0" class="bg-white rounded-lg shadow p-6 space-y-3">
      <h2 class="text-lg font-semibold text-navy">Recent enrolments</h2>
      <ul class="divide-y divide-gray-100">
        <li v-for="entry in recent" :key="entry.customer_id + entry.at">
          <button
            type="button"
            class="w-full flex items-center justify-between py-2 text-left hover:bg-gray-50 rounded px-2"
            @click="selectRecent(entry)"
          >
            <span class="text-gray-800">{{ entry.full_name }}</span>
            <code class="text-xs text-gray-500">{{ shortId(entry.customer_id) }}</code>
          </button>
        </li>
      </ul>
    </div>

    <div v-if="loading" class="text-center text-gray-500 py-6">Loading customer…</div>

    <div v-else-if="customer" class="bg-white rounded-lg shadow p-6 space-y-4">
      <div class="flex items-center justify-between">
        <h2 class="text-lg font-semibold text-navy">{{ customer.full_name }}</h2>
        <span class="inline-block rounded-full bg-brand-green/20 text-navy text-xs font-semibold px-3 py-1 capitalize">
          {{ customer.status }}
        </span>
      </div>
      <p class="text-sm text-gray-500">Customer ID: <code>{{ customer.customer_id }}</code></p>
      <p class="text-sm text-gray-500">Created: {{ customer.created_at }}</p>

      <div>
        <h3 class="text-sm font-medium text-gray-700 mb-2">
          Reference signatures ({{ references.length }})
        </h3>
        <div class="grid grid-cols-3 sm:grid-cols-4 lg:grid-cols-5 gap-3">
          <div
            v-for="ref in references"
            :key="ref.reference_id"
            class="bg-white border border-gray-200 rounded-lg p-2"
          >
            <img :src="'data:image/png;base64,' + ref.image_png_base64" class="w-full h-auto rounded" />
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
