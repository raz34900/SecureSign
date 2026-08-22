<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { get, del, ApiError } from '../api.js'
import { formatDateTime, isNationalId, pngSrc } from '../format.js'
import NoticeBanner from '../components/NoticeBanner.vue'

const lookupId = ref('')
const loading = ref(false)

/* A miss and a failure are different screens: one is an answer, the other is a fault. */
const notFoundId = ref('')
const errorMessage = ref('')

const customer = ref(null)
const loadedNationalId = ref('')
const references = ref([])

const confirmingId = ref(null)
const deleteNotice = ref(null) // { level: 'warning' | 'error', message }

const referenceFloor = computed(() => customer.value?.reference_floor)

/* The floor counts every organisation's references, because verification compares
   against all of them. An org with few of its own may still be free to delete. */
const atReferenceFloor = computed(
  () => !!customer.value && customer.value.total_reference_count <= referenceFloor.value,
)

const trimmedId = computed(() => lookupId.value.trim())
const canSearch = computed(() => isNationalId(trimmedId.value) && !loading.value)
const showsFormatHint = computed(
  () => lookupId.value.length > 0 && !isNationalId(trimmedId.value),
)

// Before the first search there is nothing to report, not an empty result.
const searched = computed(
  () => !!customer.value || !!notFoundId.value || !!errorMessage.value,
)

function handleEscape(event) {
  if (event.key === 'Escape' && confirmingId.value !== null) {
    cancelDelete()
  }
}

onMounted(() => window.addEventListener('keydown', handleEscape))
onUnmounted(() => window.removeEventListener('keydown', handleEscape))

async function loadCustomer() {
  const targetId = trimmedId.value
  if (!isNationalId(targetId)) return

  loading.value = true
  notFoundId.value = ''
  errorMessage.value = ''
  deleteNotice.value = null
  confirmingId.value = null
  customer.value = null
  loadedNationalId.value = ''
  references.value = []

  try {
    const customerRes = await get(`/customers/lookup/${targetId}`)
    customer.value = customerRes
    loadedNationalId.value = targetId

    const referencesRes = await get(`/customers/${customerRes.customer_id}/references`)
    references.value = referencesRes.references
  } catch (err) {
    // A record held by another organisation answers 404 as well, and reads the same here.
    if (err instanceof ApiError && (err.code === 'CUSTOMER_NOT_FOUND' || err.status === 404)) {
      notFoundId.value = targetId
    } else {
      errorMessage.value = err.message || 'Failed to load customer.'
    }
  } finally {
    loading.value = false
  }
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
    customer.value = {
      ...customer.value,
      own_reference_count: customer.value.own_reference_count - 1,
      total_reference_count: customer.value.total_reference_count - 1,
    }
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
  <div class="space-y-6">
    <header>
      <h1 class="text-xl font-semibold text-ink">Customers</h1>
      <p class="mt-1 max-w-prose text-sm text-ink-muted">
        Look a customer up by national ID to see and manage the reference signatures your
        organisation holds for them.
      </p>
    </header>

    <form class="max-w-4xl border-t border-border pt-4" @submit.prevent="loadCustomer">
      <div class="flex flex-wrap items-end gap-3">
        <div>
          <label class="block text-xs font-semibold uppercase tracking-wide text-ink-muted" for="lookup-national-id">
            National ID
          </label>
          <input
            id="lookup-national-id"
            v-model="lookupId"
            type="text"
            inputmode="numeric"
            maxlength="9"
            autocomplete="off"
            placeholder="9 digits"
            class="tabular mt-1.5 min-h-11 w-44 rounded-md border border-border-strong bg-surface px-3 py-2 text-sm text-ink placeholder:text-ink-subtle"
          />
        </div>
        <button
          type="submit"
          :disabled="!canSearch"
          class="min-h-11 rounded-md bg-navy px-5 text-sm font-semibold text-ink-inverse disabled:bg-sunken disabled:text-ink-subtle disabled:cursor-not-allowed"
        >
          {{ loading ? 'Searching…' : 'Search' }}
        </button>
      </div>
      <p v-if="showsFormatHint" class="mt-2 text-xs text-danger">
        A national ID is exactly <span class="tabular">9</span> digits.
      </p>
    </form>

    <NoticeBanner v-if="errorMessage" level="error">
      {{ errorMessage }}
    </NoticeBanner>

    <p v-if="loading" class="border-t border-border pt-6 text-sm text-ink-subtle">
      Searching the registry…
    </p>

    <!-- Nothing has been asked yet: say what this screen will hold, not that it is empty. -->
    <section
      v-else-if="!searched"
      class="rounded-md border border-border px-4 py-12 text-center"
    >
      <p class="text-sm font-medium text-ink">No customer loaded</p>
      <p class="mx-auto mt-1.5 max-w-prose text-sm text-ink-muted">
        Enter a national ID above. Reference signatures your organisation holds for that
        customer appear here, at full size.
      </p>
    </section>

    <section
      v-else-if="notFoundId"
      class="rounded-md border border-border px-4 py-12 text-center"
    >
      <p class="text-sm font-medium text-ink">
        No customer found for <span class="tabular">{{ notFoundId }}</span>
      </p>
      <p class="mx-auto mt-1.5 max-w-prose text-sm text-ink-muted">
        Check the number for a typo, or enrol this customer if they are new to the registry.
      </p>
      <RouterLink
        :to="{ name: 'enrol', query: { national_id: notFoundId } }"
        class="mt-4 inline-flex min-h-11 items-center rounded-md border border-border-strong px-4 text-sm font-semibold text-navy"
      >
        Enrol a new customer
      </RouterLink>
    </section>

    <template v-else-if="customer">
      <section class="border-t border-border pt-4">
        <h2 class="text-lg font-semibold text-ink">{{ customer.full_name }}</h2>
        <dl class="mt-3 flex flex-wrap gap-x-10 gap-y-3">
          <div>
            <dt class="text-xs font-semibold uppercase tracking-wide text-ink-muted">National ID</dt>
            <dd class="tabular mt-0.5 text-sm text-ink">{{ loadedNationalId }}</dd>
          </div>
          <div>
            <dt class="text-xs font-semibold uppercase tracking-wide text-ink-muted">Status</dt>
            <dd class="mt-0.5 flex items-center gap-2 text-sm capitalize text-ink">
              <span
                aria-hidden="true"
                class="h-1.5 w-1.5 shrink-0 rounded-full"
                :class="customer.status === 'active' ? 'bg-brand-green-deep' : 'bg-ink-subtle'"
              ></span>
              {{ customer.status }}
            </dd>
          </div>
          <div>
            <dt class="text-xs font-semibold uppercase tracking-wide text-ink-muted">Enrolled</dt>
            <dd class="tabular mt-0.5 text-sm text-ink">{{ formatDateTime(customer.created_at) }}</dd>
          </div>
          <div>
            <dt class="text-xs font-semibold uppercase tracking-wide text-ink-muted">References on file</dt>
            <dd class="mt-0.5 text-sm text-ink">
              <span class="tabular">{{ customer.own_reference_count }}</span> yours,
              <span class="tabular">{{ customer.total_reference_count }}</span> across all organisations
            </dd>
          </div>
        </dl>
      </section>

      <section class="border-t border-border pt-4">
        <div class="flex flex-wrap items-center justify-between gap-3">
          <h3 class="text-sm font-semibold text-ink">
            Your reference signatures
            <span class="tabular font-normal text-ink-muted">({{ references.length }})</span>
          </h3>
          <RouterLink
            :to="{ name: 'enrol', query: { national_id: loadedNationalId, full_name: customer.full_name } }"
            class="inline-flex min-h-11 items-center rounded-md border border-border-strong px-4 text-sm font-semibold text-navy"
          >
            Add signatures
          </RouterLink>
        </div>

        <NoticeBanner v-if="deleteNotice" :level="deleteNotice.level" class="mt-3">
          {{ deleteNotice.message }}
        </NoticeBanner>

        <p v-if="references.length === 0" class="mt-4 max-w-prose text-sm text-ink-muted">
          Your organisation holds no reference signatures for this customer. Verifications
          still compare against the
          <span class="tabular">{{ customer.total_reference_count }}</span> held elsewhere in
          the registry.
        </p>

        <ul
          v-else
          class="mt-4 grid gap-4 grid-cols-[repeat(auto-fill,minmax(15rem,1fr))]"
        >
          <li
            v-for="(reference, index) in references"
            :key="reference.reference_id"
            class="rounded-md border border-border bg-surface"
          >
            <img
              :src="pngSrc(reference.image_png_base64)"
              :alt="`Reference signature ${index + 1} of ${references.length} for ${customer.full_name}`"
              class="h-44 w-full rounded-t-md object-contain p-3"
            />

            <div
              v-if="confirmingId === reference.reference_id"
              class="flex items-center gap-2 border-t border-border p-2"
            >
              <p class="flex-1 pl-1 text-xs text-ink-muted">Delete permanently?</p>
              <button
                type="button"
                class="min-h-11 rounded-md bg-danger px-3 text-xs font-semibold text-ink-inverse"
                @click="confirmDelete(reference.reference_id)"
              >
                Delete
              </button>
              <button
                type="button"
                class="min-h-11 rounded-md border border-border px-3 text-xs font-semibold text-ink"
                @click="cancelDelete"
              >
                Keep
              </button>
            </div>

            <div v-else class="flex min-h-11 items-center justify-between gap-2 border-t border-border pl-3 pr-2">
              <span class="tabular text-xs text-ink-muted">Reference {{ index + 1 }}</span>
              <button
                v-if="!atReferenceFloor"
                type="button"
                :aria-label="`Delete reference signature ${index + 1} for ${customer.full_name}`"
                class="min-h-11 rounded-md px-3 text-xs font-medium text-ink-muted hover:text-danger"
                @click="startDelete(reference.reference_id)"
              >
                Delete
              </button>
            </div>
          </li>
        </ul>
      </section>
    </template>
  </div>
</template>
