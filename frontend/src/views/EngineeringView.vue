<script setup>
import { computed, onMounted, ref } from 'vue'
import { get, postJson, ApiError } from '../api.js'
import { formatDistance, formatConfidence, formatDateTime } from '../format.js'

const STATUS_FILTERS = [
  { value: 'pending', label: 'Pending' },
  { value: 'accepted', label: 'Accepted' },
  { value: 'rejected', label: 'Rejected' },
]

const overview = ref(null)
const reports = ref([])
const statusFilter = ref('pending')
const loading = ref(true)
const errorMessage = ref('')
const actionError = ref('')
const actingId = ref('')

const histogramMax = computed(() => {
  const counts = overview.value?.distance_histogram.map((b) => b.count) ?? []
  return Math.max(1, ...counts)
})

/* The threshold sits inside one bucket; marking it turns the chart into a decision boundary. */
function isThresholdBucket(bucket) {
  const threshold = overview.value?.model.threshold ?? 0
  return threshold >= bucket.lower && threshold < bucket.upper
}

/* An institution's own track record is the only anti-poisoning signal available here,
   since the engineer cannot inspect the disputed signature itself. */
function reporterRecord({ reports }) {
  if (reports.total <= 1) return 'first report'
  const settled = reports.accepted + reports.rejected
  if (settled === 0) return `${reports.total} reports, none reviewed yet`
  return `${reports.accepted} of ${settled} reports accepted`
}

function reporterClass({ reports }) {
  const settled = reports.accepted + reports.rejected
  if (settled < 3) return 'text-ink-subtle'
  return reports.accepted / settled < 0.34 ? 'text-fraud font-medium' : 'text-ink-subtle'
}

function verdictStat(verdict) {
  return overview.value?.verifications.by_verdict.find((row) => row.verdict === verdict)
}

/* The panel answers only on the internal entrypoint, so a 404 here means the browser
   reached the public one - a wrong address, not a broken server. Say which. */
const OUTSIDE_MESSAGE =
  'This panel is internal only. Open it from the machine running SecureSign, at http://localhost:8081/engineering.'

async function loadOverview() {
  try {
    overview.value = await get('/engineering/overview')
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) {
      errorMessage.value = OUTSIDE_MESSAGE
    } else {
      errorMessage.value = err instanceof ApiError ? err.message : 'Failed to load model metrics.'
    }
  }
}

async function loadReports() {
  try {
    const data = await get(`/engineering/feedback?status=${statusFilter.value}`)
    reports.value = data.feedback
  } catch (err) {
    errorMessage.value = err instanceof ApiError ? err.message : 'Failed to load reports.'
  }
}

async function applyStatus(value) {
  statusFilter.value = value
  actionError.value = ''
  await loadReports()
}

async function review(report, status) {
  if (actingId.value) return
  actingId.value = report.feedback_id
  actionError.value = ''
  try {
    await postJson(`/engineering/feedback/${report.feedback_id}`, { status })
    reports.value = reports.value.filter((r) => r.feedback_id !== report.feedback_id)
    await loadOverview()
  } catch (err) {
    actionError.value = err.message || 'Failed to record the review.'
  } finally {
    actingId.value = ''
  }
}

onMounted(async () => {
  await Promise.all([loadOverview(), loadReports()])
  loading.value = false
})
</script>

<template>
  <div class="space-y-8">
    <div>
      <h1 class="text-2xl font-bold text-navy">Model engineering</h1>
      <p class="text-sm text-ink-muted mt-1">
        Aggregate model behaviour and the results institutions have disputed. This panel
        holds no customer names, identifiers or signature images.
      </p>
    </div>

    <div v-if="errorMessage" class="bg-danger-surface border border-danger-border text-danger text-sm rounded-lg px-4 py-3">
      {{ errorMessage }}
    </div>

    <div v-else-if="loading" class="text-center text-ink-subtle py-12">Loading…</div>

    <template v-else-if="overview">
      <div class="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <div class="bg-surface rounded-lg shadow p-4">
          <p class="text-xs font-medium uppercase tracking-wide text-ink-subtle">Verifications</p>
          <p class="text-2xl font-bold text-navy">{{ overview.verifications.total }}</p>
          <p class="text-xs text-ink-muted mt-1">{{ overview.verifications.borderline }} near the threshold</p>
        </div>
        <div class="bg-surface rounded-lg shadow p-4">
          <p class="text-xs font-medium uppercase tracking-wide text-ink-subtle">Customers enrolled</p>
          <p class="text-2xl font-bold text-navy">{{ overview.registry.customers }}</p>
          <p class="text-xs text-ink-muted mt-1">{{ overview.registry.reference_signatures }} reference signatures</p>
        </div>
        <div class="bg-surface rounded-lg shadow p-4">
          <p class="text-xs font-medium uppercase tracking-wide text-ink-subtle">Organisations</p>
          <p class="text-2xl font-bold text-navy">{{ overview.registry.organisations }}</p>
          <p class="text-xs text-ink-muted mt-1">subscribing to the registry</p>
        </div>
        <div class="bg-surface rounded-lg shadow p-4">
          <p class="text-xs font-medium uppercase tracking-wide text-ink-subtle">Model</p>
          <p class="text-lg font-bold text-navy">{{ overview.model.version }}</p>
          <p class="text-xs text-ink-muted mt-1 font-mono">threshold {{ formatDistance(overview.model.threshold) }}</p>
        </div>
      </div>

      <div class="grid gap-4 sm:grid-cols-2">
        <div
          v-for="verdict in ['VALID', 'FRAUD']"
          :key="verdict"
          class="bg-surface rounded-lg shadow p-4"
          :class="verdict === 'VALID' ? 'border-l-4 border-valid' : 'border-l-4 border-fraud'"
        >
          <p class="text-sm font-semibold" :class="verdict === 'VALID' ? 'text-valid' : 'text-fraud'">
            {{ verdict }}
          </p>
          <template v-if="verdictStat(verdict)">
            <p class="text-2xl font-bold text-navy">{{ verdictStat(verdict).count }}</p>
            <p class="text-xs text-ink-muted mt-1 font-mono">
              mean distance {{ formatDistance(verdictStat(verdict).mean_distance) }} ·
              mean confidence {{ formatConfidence(verdictStat(verdict).mean_confidence) }}
            </p>
          </template>
          <p v-else class="text-sm text-ink-subtle mt-1">No verifications yet.</p>
        </div>
      </div>

      <div class="bg-surface rounded-lg shadow p-6 space-y-3">
        <h2 class="text-lg font-semibold text-navy">Distance distribution</h2>
        <p class="text-sm text-ink-muted">
          Where scores actually land. A pile-up against the threshold line means the model is
          deciding on coin flips.
        </p>

        <div class="flex items-end gap-1 h-40" role="img" aria-label="Histogram of verification distances">
          <div v-for="bucket in overview.distance_histogram" :key="bucket.lower" class="flex-1 flex flex-col justify-end h-full">
            <div
              class="w-full rounded-t"
              :class="isThresholdBucket(bucket) ? 'bg-borderline' : 'bg-navy/70'"
              :style="{ height: `${(bucket.count / histogramMax) * 100}%` }"
              :title="`${bucket.lower}–${bucket.upper}: ${bucket.count}`"
            ></div>
          </div>
        </div>
        <div class="flex justify-between text-2xs text-ink-subtle font-mono">
          <span>0.00</span>
          <span>threshold {{ formatDistance(overview.model.threshold) }}</span>
          <span>1.00</span>
        </div>
      </div>

      <div class="bg-surface rounded-lg shadow p-6 space-y-4">
        <div class="flex flex-wrap items-center justify-between gap-3">
          <h2 class="text-lg font-semibold text-navy">Disputed results</h2>
          <div class="flex gap-1" role="group" aria-label="Filter reports by status">
            <button
              v-for="option in STATUS_FILTERS"
              :key="option.value"
              type="button"
              :aria-pressed="statusFilter === option.value"
              class="min-h-11 rounded-lg border px-4 text-sm font-medium"
              :class="statusFilter === option.value
                ? 'border-navy bg-navy text-ink-inverse'
                : 'border-border-strong bg-surface text-ink'"
              @click="applyStatus(option.value)"
            >
              {{ option.label }}
            </button>
          </div>
        </div>

        <p v-if="actionError" class="text-sm text-danger">{{ actionError }}</p>

        <p class="text-sm text-ink-muted">
          You cannot see the signature, and you are not being asked to re-judge it. Decide
          whether the report is a usable training signal: a near-threshold score from an
          institution with a good record usually is; a confident score disputed by an
          institution whose reports keep getting rejected usually is not.
        </p>

        <p v-if="reports.length === 0" class="text-sm text-ink-subtle py-6 text-center">
          No {{ statusFilter }} reports.
        </p>

        <ul v-else class="divide-y divide-border">
          <li v-for="report in reports" :key="report.feedback_id" class="py-4 space-y-2">
            <div class="flex flex-wrap items-baseline gap-x-3 gap-y-1">
              <span class="text-sm font-semibold text-ink">
                System said {{ report.verification?.verdict ?? 'unknown' }}, reported as {{ report.claimed_label }}
              </span>
              <span
                v-if="report.verification?.borderline"
                class="rounded-full bg-borderline-surface text-borderline border border-borderline-border px-2 py-0.5 text-2xs font-bold"
              >
                NEAR THRESHOLD
              </span>
            </div>

            <p v-if="report.verification" class="text-xs font-mono text-ink-muted">
              distance {{ formatDistance(report.verification.distance) }} ·
              threshold {{ formatDistance(report.verification.threshold_used) }} ·
              {{ report.verification.margin > 0 ? '+' : '' }}{{ formatDistance(report.verification.margin) }} from the line ·
              {{ formatConfidence(report.verification.confidence) }}
            </p>

            <p v-if="report.comment" class="text-sm text-ink">“{{ report.comment }}”</p>

            <p class="text-xs text-ink-subtle">
              Reported by <span class="font-medium text-ink">{{ report.reporter.organisation }}</span>
              ({{ report.reporter.type }}) ·
              <span :class="reporterClass(report.reporter)">
                {{ reporterRecord(report.reporter) }}
              </span>
              · {{ report.model_version }} · {{ formatDateTime(report.created_at) }}
            </p>

            <div v-if="report.status === 'pending'" class="flex flex-wrap gap-2 pt-1">
              <button
                type="button"
                :disabled="actingId === report.feedback_id"
                class="min-h-11 rounded-lg bg-navy px-4 text-sm font-semibold text-ink-inverse disabled:opacity-50"
                @click="review(report, 'accepted')"
              >
                Accept for retraining
              </button>
              <button
                type="button"
                :disabled="actingId === report.feedback_id"
                class="min-h-11 rounded-lg border border-border-strong bg-surface px-4 text-sm font-medium text-ink disabled:opacity-50"
                @click="review(report, 'rejected')"
              >
                Reject
              </button>
            </div>
          </li>
        </ul>
      </div>
    </template>
  </div>
</template>
