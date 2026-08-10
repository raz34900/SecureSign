<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { get, del, ApiError } from '../api.js'
import { formatDateTime } from '../format.js'

const RECENT_KEY = 'ss_recent_customers'
const REFERENCE_FLOOR = 5

const lookupId = ref('')
const loading = ref(false)
const notice = ref(null) // { level: 'warning' | 'error', message }

const customer = ref(null)
const references = ref([])

const recent = ref([])

const confirmingId = ref(null)
const deleteNotice = ref(null) // { level: 'warning' | 'error', message }

const atReferenceFloor = computed(
  () => !!customer.value && customer.value.own_reference_count <= REFERENCE_FLOOR,
)

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

function handleEscape(event) {
  if (event.key === 'Escape' && confirmingId.value !== null) {
    cancelDelete()
  }
}

onMounted(() => {
  loadRecent()
  window.addEventListener('keydown', handleEscape)
})

onUnmounted(() => {
  window.removeEventListener('keydown', handleEscape)
})

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
  if (atReferenceFloor.value) return
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

    <div class="bg-surface rounded-lg shadow p-6 space-y-3">
      <label class="block text-sm font-medium text-ink" for="lookup-national-id">National ID</label>
      <div class="flex gap-2">
        <input
          id="lookup-national-id"
          v-model="lookupId"
          type="text"
          inputmode="numeric"
          maxlength="9"
          placeholder="9-digit national ID"
          class="flex-1 min-h-11 rounded-lg border border-border-strong px-3 py-2 bg-surface text-ink"
          @keyup.enter="loadCustomer()"
        />
        <button
          type="button"
          :disabled="!isValidNationalId(lookupId.trim()) || loading"
          class="min-h-11 bg-brand-green text-navy font-semibold rounded-lg px-4 py-2 disabled:opacity-50 disabled:cursor-not-allowed"
          @click="loadCustomer()"
        >
          {{ loading ? 'Loading…' : 'Load' }}
        </button>
      </div>
      <p v-if="lookupId.length > 0 && !isValidNationalId(lookupId.trim())" class="text-sm text-danger">
        National ID must be exactly 9 digits.
      </p>

      <div
        v-if="notice"
        :class="notice.level === 'warning'
          ? 'border-warning-border bg-warning-surface text-warning'
          : 'border-danger-border bg-danger-surface text-danger'"
        class="rounded-lg border px-4 py-3 text-sm space-y-1"
      >
        <p>{{ notice.message }}</p>
        <p v-if="notice.level === 'warning'" class="text-ink-muted">
          Check the national ID, or
          <RouterLink :to="{ name: 'enrol' }" class="underline font-medium">enrol this customer</RouterLink>
          if they are new.
        </p>
      </div>
    </div>

    <div v-if="recent.length > 0" class="bg-surface rounded-lg shadow p-6 space-y-3">
      <h2 class="text-lg font-semibold text-navy">Recent enrolments</h2>
      <ul class="divide-y divide-border">
        <li v-for="entry in recent" :key="entry.customer_id + entry.at">
          <button
            type="button"
            class="w-full min-h-11 flex items-center justify-between py-2 text-left hover:bg-sunken rounded px-2"
            @click="selectRecent(entry)"
          >
            <span class="text-ink">{{ entry.full_name }}</span>
            <code class="text-xs text-ink-subtle">{{ entry.national_id }}</code>
          </button>
        </li>
      </ul>
    </div>

    <div v-if="loading" class="text-center text-ink-subtle py-6">Loading customer…</div>

    <div v-else-if="customer" class="bg-surface rounded-lg shadow p-6 space-y-4">
      <div class="flex items-center justify-between">
        <h2 class="text-lg font-semibold text-navy">{{ customer.full_name }}</h2>
        <span class="inline-block rounded-full bg-brand-green/20 text-navy text-xs font-semibold px-3 py-1 capitalize">
          {{ customer.status }}
        </span>
      </div>
      <p class="text-sm text-ink-subtle">Created: {{ formatDateTime(customer.created_at) }}</p>

      <div
        v-if="deleteNotice"
        :class="deleteNotice.level === 'warning'
          ? 'border-warning-border bg-warning-surface text-warning'
          : 'border-danger-border bg-danger-surface text-danger'"
        class="rounded-lg border px-4 py-3 text-sm"
      >
        {{ deleteNotice.message }}
      </div>

      <div>
        <h3 class="text-sm font-medium text-ink mb-1">
          Your organisation's reference signatures ({{ references.length }})
        </h3>
        <p v-if="atReferenceFloor" class="text-xs text-ink-muted mb-2">
          Your organisation must keep at least {{ REFERENCE_FLOOR }} reference signatures on file, so deletion is disabled.
        </p>
        <div class="grid grid-cols-3 sm:grid-cols-4 lg:grid-cols-5 gap-3">
          <div
            v-for="ref in references"
            :key="ref.reference_id"
            class="bg-surface border border-border rounded-lg p-2 flex flex-col gap-2"
          >
            <div class="relative">
              <img :src="'data:image/png;base64,' + ref.image_png_base64" class="w-full h-auto rounded" />

              <button
                v-if="confirmingId !== ref.reference_id"
                type="button"
                :disabled="atReferenceFloor"
                :aria-label="`Delete reference signature for ${customer.full_name}`"
                class="absolute -top-1 -right-1 min-w-11 min-h-11 flex items-center justify-center rounded-full bg-surface/95 border border-border text-ink-subtle hover:text-danger hover:border-danger-border disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:text-ink-subtle disabled:hover:border-border text-sm leading-none"
                @click="startDelete(ref.reference_id)"
              >
                ✕
              </button>
            </div>

            <div v-if="confirmingId === ref.reference_id" class="flex flex-col gap-2 text-center">
              <p class="text-2xs text-ink-muted">Delete this signature? This cannot be undone.</p>
              <div class="flex gap-2 justify-center">
                <button
                  type="button"
                  class="min-h-11 flex-1 text-xs font-semibold bg-danger text-ink-inverse rounded px-2"
                  @click="confirmDelete(ref.reference_id)"
                >
                  Delete
                </button>
                <button
                  type="button"
                  class="min-h-11 flex-1 text-xs font-semibold bg-sunken text-ink rounded px-2 border border-border"
                  @click="cancelDelete"
                >
                  Keep
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

