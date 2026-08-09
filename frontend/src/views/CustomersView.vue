<script setup>
import { ref, onMounted } from 'vue'
import { get, del, ApiError } from '../api.js'

const RECENT_KEY = 'ss_recent_customers'

const lookupId = ref('')
const loading = ref(false)
const notice = ref(null) // { level: 'warning' | 'error', message }

const customer = ref(null)
const references = ref([])

const recent = ref([])

const confirmingId = ref(null)
const deleteNotice = ref(null) // { level: 'warning' | 'error', message }

function isValidNationalId(value) {
  return /^\d{9}$/.test(value)
}

function loadRecent() {
  try {
    const list = JSON.parse(localStorage.getItem(RECENT_KEY) || '[]')
    // Migrate silently: entries lacking national_id are ignored.
    recent.value = Array.isArray(list) ? list.filter((entry) => entry && entry.national_id) : []
  } catch {
    recent.value = []
  }
}

onMounted(loadRecent)

async function loadCustomer(id) {
  const targetId = (id ?? lookupId.value).trim()
  if (!isValidNationalId(targetId)) return

  lookupId.value = targetId
  loading.value = true
  notice.value = null
  deleteNotice.value = null
  confirmingId.value = null
  customer.value = null
  references.value = []

  try {
    const customerRes = await get(`/customers/lookup/${targetId}`)
    customer.value = customerRes

    const referencesRes = await get(`/customers/${customerRes.customer_id}/references`)
    references.value = referencesRes.references
  } catch (err) {
    if (err instanceof ApiError && (err.code === 'CUSTOMER_NOT_FOUND' || err.status === 404)) {
      notice.value = { level: 'warning', message: 'Customer not found.' }
    } else {
      notice.value = { level: 'error', message: err.message || 'Failed to load customer.' }
    }
  } finally {
    loading.value = false
  }
}

function selectRecent(entry) {
  loadCustomer(entry.national_id)
}

function startDelete(referenceId) {
  deleteNotice.value = null
  confirmingId.value = referenceId
}

function cancelDelete() {
  confirmingId.value = null
}

async function confirmDelete(referenceId) {
  try {
    await del(`/customers/${customer.value.customer_id}/references/${referenceId}`)
    references.value = references.value.filter((r) => r.reference_id !== referenceId)
    customer.value = { ...customer.value, own_reference_count: customer.value.own_reference_count - 1 }
    deleteNotice.value = null
  } catch (err) {
    if (err instanceof ApiError && err.code === 'REFERENCE_FLOOR') {
      deleteNotice.value = { level: 'warning', message: err.message || 'Cannot delete: minimum reference signatures required.' }
    } else {
      deleteNotice.value = { level: 'error', message: err.message || 'Failed to delete reference.' }
    }
  } finally {
    confirmingId.value = null
  }
}
</script>

<template>
  <div class="max-w-3xl mx-auto space-y-8">
    <h1 class="text-2xl font-bold text-navy">Customers</h1>

    <div class="bg-white rounded-lg shadow p-6 space-y-3">
      <label class="block text-sm font-medium text-gray-700">National ID</label>
      <div class="flex gap-2">
        <input
          v-model="lookupId"
          type="text"
          inputmode="numeric"
          maxlength="9"
          placeholder="9-digit national ID"
          class="flex-1 rounded-lg border border-gray-300 px-3 py-2 focus:outline-none focus:ring-2 focus:ring-navy"
          @keyup.enter="loadCustomer()"
        />
        <button
          type="button"
          :disabled="!isValidNationalId(lookupId.trim()) || loading"
          class="bg-brand-green text-navy font-semibold rounded-lg px-4 py-2 disabled:opacity-50 disabled:cursor-not-allowed"
          @click="loadCustomer()"
        >
          {{ loading ? 'Loading…' : 'Load' }}
        </button>
      </div>
      <p v-if="lookupId.length > 0 && !isValidNationalId(lookupId.trim())" class="text-sm text-red-600">
        National ID must be exactly 9 digits.
      </p>

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
            <code class="text-xs text-gray-500">{{ entry.national_id }}</code>
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
      <p class="text-sm text-gray-500">Created: {{ customer.created_at }}</p>
      <p class="text-sm text-gray-500">Your organisation's reference signatures on file: {{ customer.own_reference_count }}</p>

      <div
        v-if="deleteNotice"
        :class="deleteNotice.level === 'warning'
          ? 'border-amber-400 bg-amber-50 text-amber-800'
          : 'border-red-400 bg-red-50 text-red-800'"
        class="rounded-lg border px-4 py-3 text-sm"
      >
        {{ deleteNotice.message }}
      </div>

      <div>
        <h3 class="text-sm font-medium text-gray-700 mb-2">
          Your organisation's reference signatures ({{ references.length }})
        </h3>
        <div class="grid grid-cols-3 sm:grid-cols-4 lg:grid-cols-5 gap-3">
          <div
            v-for="ref in references"
            :key="ref.reference_id"
            class="relative bg-white border border-gray-200 rounded-lg p-2"
          >
            <img :src="'data:image/png;base64,' + ref.image_png_base64" class="w-full h-auto rounded" />

            <div
              v-if="confirmingId === ref.reference_id"
              class="absolute inset-0 bg-white/95 rounded-lg flex flex-col items-center justify-center gap-2 p-2 text-center"
            >
              <p class="text-xs font-medium text-gray-700">Confirm delete?</p>
              <div class="flex gap-2">
                <button
                  type="button"
                  class="text-xs bg-red-600 text-white rounded px-2 py-1"
                  @click="confirmDelete(ref.reference_id)"
                >
                  Yes
                </button>
                <button
                  type="button"
                  class="text-xs bg-gray-200 text-gray-700 rounded px-2 py-1"
                  @click="cancelDelete"
                >
                  No
                </button>
              </div>
            </div>
            <button
              v-else
              type="button"
              title="Delete reference"
              class="absolute top-1 right-1 w-5 h-5 flex items-center justify-center rounded-full bg-white/90 border border-gray-300 text-gray-500 hover:text-red-600 hover:border-red-400 text-xs leading-none"
              @click="startDelete(ref.reference_id)"
            >
              ✕
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
