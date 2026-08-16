<script setup>
import { computed, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { get, postJson, ApiError } from '../api.js'
import { formatDistance, formatConfidence, formatDateTime, classifyDecision, decisionLabel } from '../format.js'

const FALLBACK_THRESHOLD = 0.3999

const VERDICT_FILTERS = [
  { value: '', label: 'All' },
  { value: 'VALID', label: 'Valid' },
  { value: 'FRAUD', label: 'Fraud' },
]

const verifications = ref([])
const loading = ref(true)
const errorMessage = ref('')

const verdictFilter = ref('')
const nationalIdFilter = ref('')

const expandedId = ref('')
const reportLabel = ref('')
const reportComment = ref('')
const reportError = ref('')
const reportSubmitting = ref(false)

const nationalIdValid = computed(
  () => nationalIdFilter.value === '' || /^\d{9}$/.test(nationalIdFilter.value.trim()),
)

function verdictKind(row) {
  return classifyDecision(row.distance, row.threshold_used ?? FALLBACK_THRESHOLD)
}

const verdictClasses = {
  valid: 'bg-valid-surface text-valid border border-valid-border',
  fraud: 'bg-fraud-surface text-fraud border border-fraud-border',
  borderline: 'bg-borderline-surface text-borderline border border-borderline-border',
}

async function loadHistory() {
  if (!nationalIdValid.value) return
  loading.value = true
  errorMessage.value = ''
  expandedId.value = ''
  try {
    const params = new URLSearchParams()
    if (verdictFilter.value) params.set('verdict', verdictFilter.value)
    if (nationalIdFilter.value.trim()) params.set('national_id', nationalIdFilter.value.trim())
    const query = params.toString()
    const data = await get(query ? `/verifications?${query}` : '/verifications')
    verifications.value = data.verifications
  } catch (err) {
    errorMessage.value = err instanceof ApiError ? err.message : 'Failed to load history.'
  } finally {
    loading.value = false
  }
}

function applyVerdict(value) {
  verdictFilter.value = value
  loadHistory()
}

function clearFilters() {
  verdictFilter.value = ''
  nationalIdFilter.value = ''
  loadHistory()
}

const filtersActive = computed(() => !!verdictFilter.value || !!nationalIdFilter.value.trim())

function toggleReport(row) {
  if (expandedId.value === row.request_id) {
    expandedId.value = ''
    return
  }
  expandedId.value = row.request_id
  reportLabel.value = row.verdict === 'VALID' ? 'forged' : 'genuine'
  reportComment.value = ''
  reportError.value = ''
}

async function submitReport(row) {
  if (reportSubmitting.value) return
  reportSubmitting.value = true
  reportError.value = ''
  try {
    await postJson(`/verifications/${row.request_id}/feedback`, {
      claimed_label: reportLabel.value,
      comment: reportComment.value.trim() || null,
    })
    verifications.value = verifications.value.map((entry) =>
      entry.request_id === row.request_id
        ? { ...entry, feedback: { claimed_label: reportLabel.value, status: 'pending' } }
        : entry,
    )
    expandedId.value = ''
  } catch (err) {
    reportError.value = err.message || 'Failed to send the report.'
  } finally {
    reportSubmitting.value = false
  }
}

onMounted(loadHistory)
</script>

<template>
  <div class="space-y-6">
    <div>
      <h1 class="text-2xl font-bold text-navy">Verification history</h1>
      <p class="text-sm text-ink-muted mt-1">
        Every check your organisation has run. Flag a result you believe was wrong and it
        goes to the engineering team; the recorded verdict never changes.
      </p>
    </div>

    <div class="bg-surface rounded-lg shadow p-4 space-y-3">
      <div class="flex flex-wrap items-end gap-4">
        <div class="flex items-center gap-1" role="group" aria-label="Filter by verdict">
          <button
            v-for="option in VERDICT_FILTERS"
            :key="option.value"
            type="button"
            :aria-pressed="verdictFilter === option.value"
            class="min-h-11 rounded-lg border px-4 text-sm font-medium"
            :class="verdictFilter === option.value
              ? 'border-navy bg-navy text-ink-inverse'
              : 'border-border-strong bg-surface text-ink'"
            @click="applyVerdict(option.value)"
          >
            {{ option.label }}
          </button>
        </div>

        <div class="flex-1 min-w-[14rem]">
          <label class="block text-sm font-medium text-ink mb-1" for="history-national-id">
            National ID
          </label>
          <div class="flex gap-2">
            <input
              id="history-national-id"
              v-model="nationalIdFilter"
              type="text"
              inputmode="numeric"
              maxlength="9"
              placeholder="9-digit national ID"
              class="flex-1 min-h-11 rounded-lg border border-border-strong px-3 py-2 bg-surface text-ink"
              @keyup.enter="loadHistory"
            />
            <button
              type="button"
              :disabled="!nationalIdValid || loading"
              class="min-h-11 bg-brand-green text-navy font-semibold rounded-lg px-4 disabled:opacity-50 disabled:cursor-not-allowed"
              @click="loadHistory"
            >
              Search
            </button>
          </div>
        </div>

        <button
          v-if="filtersActive"
          type="button"
          class="min-h-11 px-3 text-sm font-medium text-ink-muted underline underline-offset-2"
          @click="clearFilters"
        >
          Clear
        </button>
      </div>

      <p v-if="!nationalIdValid" class="text-sm text-danger">
        National ID must be exactly 9 digits.
      </p>
    </div>

    <div v-if="errorMessage" class="bg-danger-surface border border-danger-border text-danger text-sm rounded-lg px-4 py-3">
      {{ errorMessage }}
    </div>

    <div v-else-if="loading" class="text-center text-ink-subtle py-12">Loading…</div>

    <div v-else-if="verifications.length === 0" class="text-center text-ink-subtle py-12 space-y-1">
      <p class="text-ink font-medium">
        {{ filtersActive ? 'No verifications match these filters' : 'No verifications yet' }}
      </p>
      <p class="text-sm">
        <template v-if="filtersActive">
          <button type="button" class="underline font-medium" @click="clearFilters">Clear the filters</button>
          to see every result.
        </template>
        <template v-else>
          Verified signatures will appear here after you
          <RouterLink :to="{ name: 'verify' }" class="underline font-medium">run a verification</RouterLink>.
        </template>
      </p>
    </div>

    <div v-else class="bg-surface rounded-lg shadow overflow-x-auto">
      <table class="min-w-full text-sm">
        <caption class="sr-only">Verification history, most recent first</caption>
        <thead class="bg-navy text-ink-inverse">
          <tr>
            <th scope="col" class="px-4 py-3 text-left font-semibold">Customer</th>
            <th scope="col" class="px-4 py-3 text-left font-semibold">Verdict</th>
            <th scope="col" class="px-4 py-3 text-left font-semibold">Confidence</th>
            <th scope="col" class="px-4 py-3 text-left font-semibold">Distance</th>
            <th scope="col" class="px-4 py-3 text-left font-semibold">Checked by</th>
            <th scope="col" class="px-4 py-3 text-left font-semibold">When</th>
            <th scope="col" class="px-4 py-3 text-left font-semibold">Result</th>
          </tr>
        </thead>
        <tbody class="divide-y divide-border">
          <template v-for="v in verifications" :key="v.request_id">
            <tr>
              <td class="px-4 py-3">
                <span class="block text-ink font-medium">{{ v.customer_name }}</span>
                <code class="block text-xs text-ink-subtle">{{ v.national_id_masked }}</code>
              </td>
              <td class="px-4 py-3">
                <span :class="['inline-block rounded-full px-3 py-1 text-xs font-bold', verdictClasses[verdictKind(v)]]">
                  {{ decisionLabel(verdictKind(v), v.verdict) }}
                </span>
              </td>
              <td class="px-4 py-3">{{ formatConfidence(v.confidence) }}</td>
              <td class="px-4 py-3 font-mono">{{ formatDistance(v.distance) }}</td>
              <td class="px-4 py-3 text-ink-muted">{{ v.performed_by }}</td>
              <td class="px-4 py-3 text-ink-muted">{{ formatDateTime(v.created_at) }}</td>
              <td class="px-4 py-3">
                <span v-if="v.feedback" class="text-xs text-ink-muted">
                  Reported as {{ v.feedback.claimed_label }} ({{ v.feedback.status }})
                </span>
                <button
                  v-else
                  type="button"
                  class="min-h-11 px-2 text-sm font-medium text-navy underline underline-offset-2"
                  :aria-expanded="expandedId === v.request_id"
                  @click="toggleReport(v)"
                >
                  {{ expandedId === v.request_id ? 'Cancel' : 'Report as wrong' }}
                </button>
              </td>
            </tr>

            <tr v-if="expandedId === v.request_id">
              <td colspan="7" class="px-4 py-4 bg-sunken">
                <div class="max-w-xl space-y-3">
                  <p class="text-sm text-ink">
                    The system decided <strong>{{ v.verdict }}</strong>. What was the truth?
                  </p>

                  <div class="flex flex-wrap gap-2">
                    <label
                      v-for="option in [
                        { value: 'genuine', label: 'It was the real customer' },
                        { value: 'forged', label: 'It was a forgery' },
                      ]"
                      :key="option.value"
                      class="flex items-center gap-2 min-h-11 rounded-lg border px-3 text-sm cursor-pointer"
                      :class="reportLabel === option.value
                        ? 'border-navy bg-surface text-navy font-medium'
                        : 'border-border-strong bg-surface text-ink'"
                    >
                      <input v-model="reportLabel" type="radio" :value="option.value" class="shrink-0" />
                      {{ option.label }}
                    </label>
                  </div>

                  <label class="block">
                    <span class="block text-sm font-medium text-ink mb-1">Notes (optional)</span>
                    <textarea
                      v-model="reportComment"
                      rows="2"
                      maxlength="500"
                      placeholder="What did you observe that the system missed?"
                      class="w-full rounded-lg border border-border-strong bg-surface text-ink px-3 py-2 text-sm"
                    ></textarea>
                  </label>

                  <p v-if="reportError" class="text-sm text-danger">{{ reportError }}</p>

                  <div class="flex flex-wrap gap-2">
                    <button
                      type="button"
                      :disabled="reportSubmitting"
                      class="min-h-11 bg-navy text-ink-inverse font-semibold rounded-lg px-4 disabled:opacity-50"
                      @click="submitReport(v)"
                    >
                      {{ reportSubmitting ? 'Sending…' : 'Send report' }}
                    </button>
                    <button
                      type="button"
                      class="min-h-11 px-4 rounded-lg border border-border-strong bg-surface text-ink font-medium"
                      @click="expandedId = ''"
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              </td>
            </tr>
          </template>
        </tbody>
      </table>
    </div>
  </div>
</template>
