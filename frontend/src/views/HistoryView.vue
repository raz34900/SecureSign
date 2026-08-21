<script setup>
import { computed, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { get, postJson, ApiError } from '../api.js'
import { isClerk } from '../auth.js'
import { formatDistance, formatConfidence, formatDateTime, decisionLabel, isNationalId, pngSrc } from '../format.js'

const VERDICT_FILTERS = [
  { value: '', label: 'All' },
  { value: 'VALID', label: 'Valid' },
  { value: 'FRAUD', label: 'Fraud' },
]

const PAGE_SIZE = 25

const OUTCOME_LABELS = {
  accepted: 'Honoured at the counter',
  rejected: 'Refused at the counter',
  escalated: 'Sent to a manager',
}

const verifications = ref([])
const total = ref(0)
const offset = ref(0)
const detail = ref(null)
const detailLoading = ref(false)
const detailError = ref('')
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
  () => nationalIdFilter.value === '' || isNationalId(nationalIdFilter.value),
)



const verdictClasses = {
  valid: 'bg-valid-surface text-valid border border-valid-border',
  fraud: 'bg-fraud-surface text-fraud border border-fraud-border',
  borderline: 'bg-borderline-surface text-borderline border border-borderline-border',
}

async function loadHistory({ keepPage = false } = {}) {
  if (!nationalIdValid.value) return
  if (!keepPage) offset.value = 0
  loading.value = true
  errorMessage.value = ''
  expandedId.value = ''
  detail.value = null
  try {
    const params = new URLSearchParams()
    if (verdictFilter.value) params.set('verdict', verdictFilter.value)
    if (nationalIdFilter.value.trim()) params.set('national_id', nationalIdFilter.value.trim())
    params.set('limit', String(PAGE_SIZE))
    params.set('offset', String(offset.value))
    const data = await get(`/verifications?${params.toString()}`)
    verifications.value = data.verifications
    total.value = data.total ?? data.verifications.length
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

const firstShown = computed(() => (verifications.value.length ? offset.value + 1 : 0))
const lastShown = computed(() => offset.value + verifications.value.length)
const hasPrevious = computed(() => offset.value > 0)
const hasNext = computed(() => lastShown.value < total.value)

function goToPage(delta) {
  offset.value = Math.max(0, offset.value + delta * PAGE_SIZE)
  loadHistory({ keepPage: true })
}

async function toggleReport(row) {
  if (expandedId.value === row.request_id) {
    expandedId.value = ''
    detail.value = null
    return
  }
  expandedId.value = row.request_id
  reportLabel.value = row.verdict === 'VALID' ? 'forged' : 'genuine'
  reportComment.value = ''
  reportError.value = ''

  /* Fetched only when a row is opened, one row at a time. The list deliberately carries
     a has_image flag rather than the pictures: a page that shipped every signature the
     organisation had ever queried would be both enormous and a standing disclosure. */
  detail.value = null
  detailError.value = ''
  detailLoading.value = true
  try {
    const opened = row.request_id
    const body = await get(`/verifications/${opened}`)
    if (expandedId.value === opened) detail.value = body
  } catch (err) {
    detailError.value = err instanceof ApiError ? err.message : 'Could not load this result.'
  } finally {
    detailLoading.value = false
  }
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
                <span :class="['inline-block rounded-full px-3 py-1 text-xs font-bold', verdictClasses[v.band]]">
                  {{ decisionLabel(v.band, v.verdict) }}
                </span>
              </td>
              <td class="px-4 py-3">{{ formatConfidence(v.confidence) }}</td>
              <td class="px-4 py-3 font-mono">{{ formatDistance(v.distance) }}</td>
              <td class="px-4 py-3 text-ink-muted">{{ v.performed_by }}</td>
              <td class="px-4 py-3 text-ink-muted">{{ formatDateTime(v.created_at) }}</td>
              <td class="px-4 py-3">
                <span v-if="v.feedback" class="block text-xs text-ink-muted">
                  Reported as {{ v.feedback.claimed_label }} ({{ v.feedback.status }})
                </span>
                <button
                  type="button"
                  class="min-h-11 px-2 text-sm font-medium text-navy underline underline-offset-2"
                  :aria-expanded="expandedId === v.request_id"
                  @click="toggleReport(v)"
                >
                  {{ expandedId === v.request_id ? 'Close' : 'Open' }}
                </button>
              </td>
            </tr>

            <tr v-if="expandedId === v.request_id">
              <td colspan="7" class="px-4 py-4 bg-sunken">
                <div class="space-y-4">
                  <!-- What was actually compared, so a clerk can judge the decision
                       rather than only the number it produced. -->
                  <p v-if="detailLoading" class="text-sm text-ink-muted">Loading this result…</p>
                  <p v-else-if="detailError" class="text-sm text-danger">{{ detailError }}</p>
                  <div v-else-if="detail && detail.request_id === v.request_id" class="space-y-3">
                    <div v-if="detail.compared_png_base64" class="flex flex-wrap items-start gap-4">
                      <figure class="shrink-0">
                        <img
                          :src="pngSrc(detail.compared_png_base64)"
                          alt="The signature that was checked, as the model read it"
                          class="h-32 w-32 rounded border border-border bg-surface"
                        />
                        <figcaption class="mt-1 text-2xs text-ink-subtle text-center">Checked</figcaption>
                      </figure>

                      <div v-if="detail.references && detail.references.length" class="min-w-0">
                        <p class="text-xs font-medium text-ink">
                          Signatures on file for this customer now
                        </p>
                        <p class="text-2xs text-ink-subtle mb-1">
                          Shown as they stand today. The set may have changed since this check.
                        </p>
                        <div class="flex flex-wrap gap-2">
                          <img
                            v-for="reference in detail.references"
                            :key="reference.reference_id"
                            :src="pngSrc(reference.image_png_base64)"
                            alt="A reference signature on file"
                            class="h-20 w-20 rounded border border-border bg-surface"
                          />
                        </div>
                      </div>
                    </div>
                    <p v-else class="text-sm text-ink-muted">
                      The checked image is no longer kept. Images are held for
                      {{ detail.retention_days }} days; the result itself is permanent.
                    </p>

                    <!-- What the counter did about it. Only shown when there is one:
                         nothing is said in place of an outcome nobody recorded. -->
                    <div v-if="detail.outcome" class="border-t border-border pt-3 text-sm">
                      <p class="text-ink">
                        <span class="font-medium">{{ OUTCOME_LABELS[detail.outcome.outcome] }}</span>
                        by {{ detail.outcome.recorded_by }},
                        {{ formatDateTime(detail.outcome.recorded_at) }}
                      </p>
                      <p v-if="detail.outcome.reason" class="mt-1 text-ink-muted">
                        {{ detail.outcome.reason }}
                      </p>
                    </div>
                  </div>

                  <!-- Reporting belongs to the enrolling side: a merchant is paid either
                       way, so the cheapest correction they could file is always "that
                       fraud was fine", and these reports are engineering's ground truth.
                       Nothing is shown in place of the form - explaining the absence of a
                       control the reader never saw only raises a question. -->

                  <!-- A result can only be reported once, so the form disappears
                       afterwards while the row itself stays open for reading. -->
                  <div v-if="isClerk && v.feedback" class="border-t border-border pt-3 text-sm text-ink-muted">
                    Reported as {{ v.feedback.claimed_label }} - {{ v.feedback.status }}.
                    A result cannot be reported twice.
                  </div>
                  <div v-else-if="isClerk" class="max-w-xl space-y-3 border-t border-border pt-3">
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
                </div>
              </td>
            </tr>
          </template>
        </tbody>
      </table>

      <!-- A total, not just a page. Without it the newest rows look like all the rows. -->
      <div class="flex flex-wrap items-center justify-between gap-3 border-t border-border px-4 py-3 text-sm">
        <p class="text-ink-muted">
          Showing {{ firstShown }}–{{ lastShown }} of {{ total }}
        </p>
        <div class="flex gap-2">
          <button
            type="button"
            :disabled="!hasPrevious || loading"
            class="min-h-11 rounded-lg border border-border-strong bg-surface px-3 font-medium text-navy disabled:text-ink-subtle"
            @click="goToPage(-1)"
          >
            Newer
          </button>
          <button
            type="button"
            :disabled="!hasNext || loading"
            class="min-h-11 rounded-lg border border-border-strong bg-surface px-3 font-medium text-navy disabled:text-ink-subtle"
            @click="goToPage(1)"
          >
            Older
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
