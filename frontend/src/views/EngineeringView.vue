<script setup>
import { computed, onMounted, ref } from 'vue'
import { get, postJson, ApiError } from '../api.js'
import { formatDistance, formatConfidence, formatDateTime } from '../format.js'
import NoticeBanner from '../components/NoticeBanner.vue'

const STATUS_FILTERS = [
  { value: 'pending', label: 'Pending' },
  { value: 'accepted', label: 'Accepted' },
  { value: 'rejected', label: 'Rejected' },
]

// Quarter marks only: twenty labelled buckets is a ruler, not an axis.
const X_TICKS = [0, 0.25, 0.5, 0.75, 1]

const overview = ref(null)
const reports = ref([])
const statusFilter = ref('pending')
const loading = ref(true)
const errorMessage = ref('')
const actionError = ref('')
const actingId = ref('')

const buckets = computed(() => overview.value?.distance_histogram ?? [])
const histogramMax = computed(() => Math.max(0, ...buckets.value.map((b) => b.count)))

/* A count axis has to read at one verification and at ten thousand, so the top of the
   scale is rounded up to a 1/2/5 step rather than pinned to the tallest bar. */
function niceStep(raw) {
  if (raw <= 1) return 1
  const magnitude = 10 ** Math.floor(Math.log10(raw))
  for (const multiple of [1, 2, 5]) {
    if (multiple * magnitude >= raw) return multiple * magnitude
  }
  return 10 * magnitude
}

const axis = computed(() => {
  const step = niceStep(Math.max(1, histogramMax.value) / 4)
  const top = Math.max(step, Math.ceil(histogramMax.value / step) * step)
  const ticks = []
  for (let value = 0; value <= top; value += step) ticks.push(value)
  return { top, ticks }
})

// A sliver, so a bucket holding one verification is still visibly not empty.
function barHeight(bucket) {
  if (!bucket.count) return '0px'
  return `max(3px, ${((bucket.count / axis.value.top) * 100).toFixed(2)}%)`
}

/* The threshold sits inside one bucket; marking it turns the chart into a decision boundary. */
function isThresholdBucket(bucket) {
  const threshold = overview.value?.model.threshold ?? 0
  return threshold >= bucket.lower && threshold < bucket.upper
}

const thresholdBucket = computed(() => buckets.value.find((b) => isThresholdBucket(b)))

// Near the edges the caption would be cut off, so it hangs from the side with room.
const thresholdShift = computed(() => {
  const threshold = overview.value?.model.threshold ?? 0
  if (threshold < 0.14) return 'translate-x-0'
  if (threshold > 0.86) return '-translate-x-full'
  return '-translate-x-1/2'
})

// Twenty permanent labels collide; a handful do not, and the early case is a handful.
const labelEveryBar = computed(() => buckets.value.filter((b) => b.count).length <= 12)

function showsCount(bucket) {
  return bucket.count > 0 && (labelEveryBar.value || bucket.count === histogramMax.value)
}

const chartSummary = computed(() => {
  const data = overview.value
  if (!data) return ''
  const total = data.verifications.total
  if (!total) return 'Distance histogram: no verifications recorded yet.'
  const peak = data.distance_histogram.reduce((a, b) => (b.count > a.count ? b : a))
  return `Histogram of ${total} verification distances in twenty buckets from 0 to 1. `
    + `Busiest bucket ${peak.lower} to ${peak.upper}, holding ${peak.count}. `
    + `Threshold ${formatDistance(data.model.threshold)}.`
})

/* An institution's own track record is the only anti-poisoning signal available here,
   since the engineer cannot inspect the disputed signature itself. */
function reporterRecord({ reports }) {
  if (reports.total <= 1) return 'first report'
  const settled = reports.accepted + reports.rejected
  if (settled === 0) return `${reports.total} reports, none reviewed yet`
  return `${reports.accepted} of ${settled} accepted`
}

function reporterClass({ reports }) {
  const settled = reports.accepted + reports.rejected
  if (settled < 3) return 'text-ink-subtle'
  return reports.accepted / settled < 0.34 ? 'text-fraud font-medium' : 'text-ink-subtle'
}

function verdictStat(verdict) {
  return overview.value?.verifications.by_verdict.find((row) => row.verdict === verdict)
}

function feedbackCount(status) {
  return overview.value?.feedback?.[status] ?? 0
}

const reviewedTotal = computed(() => feedbackCount('accepted') + feedbackCount('rejected'))

// The server decides the band; this only picks the ink for the name it already chose.
const BAND_TONE = {
  valid: { text: 'text-valid', dot: 'bg-valid' },
  fraud: { text: 'text-fraud', dot: 'bg-fraud' },
  borderline: { text: 'text-borderline', dot: 'bg-borderline' },
}

function bandTone(band) {
  return BAND_TONE[band] ?? { text: 'text-ink', dot: 'bg-ink-subtle' }
}

const filedRange = computed(() => {
  const times = reports.value
    .map((report) => new Date(report.created_at).getTime())
    .filter((time) => !Number.isNaN(time))
  if (!times.length) return ''
  const oldest = formatDateTime(new Date(Math.min(...times)).toISOString())
  const newest = formatDateTime(new Date(Math.max(...times)).toISOString())
  return oldest === newest ? oldest : `${oldest} – ${newest}`
})

/* The panel answers only on the internal entrypoint, so a 404 here means the browser
   reached the public one. Say nothing about where it does answer: whoever is looking
   at this screen from the public entrypoint is the one person who must not be told. */
const OUTSIDE_MESSAGE = 'Not available.'

async function loadOverview() {
  try {
    overview.value = await get('/engineering/overview')
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) {
      errorMessage.value = OUTSIDE_MESSAGE
    } else {
      errorMessage.value = err.message || 'Failed to load model metrics.'
    }
  }
}

async function loadReports() {
  try {
    const data = await get(`/engineering/feedback?status=${statusFilter.value}`)
    reports.value = data.feedback
  } catch (err) {
    errorMessage.value = err.message || 'Failed to load reports.'
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
  <div class="space-y-6">
    <div>
      <h1 class="text-xl font-semibold text-navy">Model engineering</h1>
      <p class="mt-1 max-w-prose text-sm text-ink-muted">
        Aggregate model behaviour and the results institutions have disputed. This panel
        holds no customer names, identifiers or signature images.
      </p>
    </div>

    <NoticeBanner v-if="errorMessage">
      {{ errorMessage }}
    </NoticeBanner>

    <p v-else-if="loading" class="py-12 text-sm text-ink-subtle">Loading…</p>

    <template v-else-if="overview">
      <!-- One rail, divided, rather than four cards of the same size and shape. These are
           readings off one system, and reading them across is the point. -->
      <dl class="grid divide-y divide-border rounded-md border border-border bg-surface sm:grid-cols-2 sm:divide-y-0 lg:grid-cols-4">
        <div class="p-4 sm:border-r sm:border-border sm:last:border-r-0 lg:border-r">
          <dt class="text-xs font-medium uppercase tracking-wide text-ink-subtle">Verifications</dt>
          <dd class="tabular mt-1 text-2xl font-semibold text-navy">{{ overview.verifications.total }}</dd>
          <dd class="tabular mt-0.5 text-xs text-ink-muted">
            {{ overview.verifications.borderline }} near the threshold
          </dd>
        </div>
        <div class="p-4 lg:border-r lg:border-border">
          <dt class="text-xs font-medium uppercase tracking-wide text-ink-subtle">Customers enrolled</dt>
          <dd class="tabular mt-1 text-2xl font-semibold text-navy">{{ overview.registry.customers }}</dd>
          <dd class="tabular mt-0.5 text-xs text-ink-muted">
            {{ overview.registry.reference_signatures }} reference signatures
          </dd>
        </div>
        <div class="p-4 sm:border-r sm:border-border lg:border-r">
          <dt class="text-xs font-medium uppercase tracking-wide text-ink-subtle">Organisations</dt>
          <dd class="tabular mt-1 text-2xl font-semibold text-navy">{{ overview.registry.organisations }}</dd>
          <dd class="mt-0.5 text-xs text-ink-muted">subscribing to the registry</dd>
        </div>
        <div class="p-4">
          <dt class="text-xs font-medium uppercase tracking-wide text-ink-subtle">Model</dt>
          <dd class="mt-1 text-lg font-semibold text-navy">{{ overview.model.version }}</dd>
          <dd class="tabular mt-0.5 text-xs text-ink-muted">
            threshold {{ formatDistance(overview.model.threshold) }}
          </dd>
        </div>
      </dl>

      <div class="grid gap-6 border-t border-border pt-6 xl:grid-cols-[minmax(0,2.4fr)_minmax(0,1fr)]">
        <section class="min-w-0">
          <div class="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
            <h2 class="text-sm font-semibold text-navy">Distance distribution</h2>
            <p class="tabular text-xs text-ink-subtle">
              {{ overview.verifications.total }} verifications · buckets of 0.05
            </p>
          </div>
          <p class="mt-1 max-w-prose text-xs text-ink-muted">
            Where scores actually land. A pile-up against the threshold line means the model
            is deciding on coin flips.
          </p>

          <!-- The threshold is the only line on this chart that means anything, so it is
               drawn across the plot rather than named in a caption underneath. -->
          <div class="relative mt-4 ml-11 h-4">
            <span
              class="tabular absolute whitespace-nowrap text-2xs font-medium text-fraud"
              :class="thresholdShift"
              :style="{ left: `${overview.model.threshold * 100}%` }"
            >threshold {{ formatDistance(overview.model.threshold) }}</span>
          </div>

          <div class="flex">
            <div class="relative h-56 w-11 shrink-0 sm:h-64 xl:h-72 2xl:h-96">
              <span
                v-for="tick in axis.ticks"
                :key="tick"
                class="tabular absolute right-2 -translate-y-1/2 text-2xs text-ink-subtle"
                :style="{ bottom: `${(tick / axis.top) * 100}%` }"
              >{{ tick }}</span>
            </div>

            <div class="min-w-0 flex-1">
              <div
                class="relative h-56 border-b border-l border-border-strong sm:h-64 xl:h-72 2xl:h-96"
                role="img"
                :aria-label="chartSummary"
              >
                <!-- Which side of the line a bucket falls on is the whole reading, so the
                     ground states it and the captions below name it. -->
                <div
                  class="absolute inset-y-0 left-0 bg-valid-surface/60"
                  :style="{ width: `${overview.model.threshold * 100}%` }"
                ></div>
                <div
                  class="absolute inset-y-0 right-0 bg-fraud-surface/45"
                  :style="{ width: `${(1 - overview.model.threshold) * 100}%` }"
                ></div>

                <div
                  v-for="tick in axis.ticks.slice(1)"
                  :key="`grid-${tick}`"
                  class="absolute inset-x-0 h-px bg-border"
                  :style="{ bottom: `${(tick / axis.top) * 100}%` }"
                ></div>
                <div
                  v-for="tick in [0.25, 0.5, 0.75]"
                  :key="`vgrid-${tick}`"
                  class="absolute inset-y-0 w-px bg-border/70"
                  :style="{ left: `${tick * 100}%` }"
                ></div>

                <div class="absolute inset-0 flex items-end">
                  <div
                    v-for="bucket in buckets"
                    :key="bucket.lower"
                    class="group relative h-full flex-1"
                  >
                    <div
                      class="absolute inset-x-[1.5px] bottom-0 rounded-t-[2px]"
                      :class="isThresholdBucket(bucket) ? 'bg-borderline' : 'bg-navy/70'"
                      :style="{ height: barHeight(bucket) }"
                    ></div>
                    <span
                      v-if="bucket.count"
                      class="tabular pointer-events-none absolute inset-x-0 text-center text-2xs text-ink-muted"
                      :class="showsCount(bucket) ? '' : 'opacity-0 group-hover:opacity-100'"
                      :style="{ bottom: `calc(${barHeight(bucket)} + 4px)` }"
                    >{{ bucket.count }}</span>
                  </div>
                </div>

                <div
                  class="absolute inset-y-0 z-10 w-px bg-fraud/70"
                  :style="{ left: `${overview.model.threshold * 100}%` }"
                ></div>

                <p
                  v-if="!overview.verifications.total"
                  class="absolute inset-0 flex items-center justify-center text-xs text-ink-subtle"
                >
                  No verifications recorded yet.
                </p>
              </div>

              <div class="relative h-4">
                <span
                  v-for="(tick, index) in X_TICKS"
                  :key="`x-${tick}`"
                  class="tabular absolute pt-1 text-2xs text-ink-subtle"
                  :class="index === 0 ? '' : index === X_TICKS.length - 1 ? '-translate-x-full' : '-translate-x-1/2'"
                  :style="{ left: `${tick * 100}%` }"
                >{{ tick.toFixed(2) }}</span>
              </div>
            </div>
          </div>

          <div class="ml-11 mt-3 flex flex-wrap items-center gap-x-5 gap-y-1.5 text-2xs text-ink-muted">
            <span class="flex items-center gap-1.5">
              <span class="h-2.5 w-2.5 rounded-[2px] bg-navy/70"></span>
              verifications per bucket
            </span>
            <span v-if="thresholdBucket" class="tabular flex items-center gap-1.5">
              <span class="h-2.5 w-2.5 rounded-[2px] bg-borderline"></span>
              bucket holding the threshold, {{ thresholdBucket.lower.toFixed(2) }}–{{ thresholdBucket.upper.toFixed(2) }}
            </span>
            <span class="flex items-center gap-1.5">
              <span class="h-3 w-px bg-fraud/70"></span>
              below the line VALID, above it FRAUD
            </span>
          </div>
        </section>

        <!-- The verdict split. A tinted ground and a leading marker carry the state; a thick
             coloured edge on one side is decoration pretending to be structure. -->
        <section class="min-w-0">
          <h2 class="text-sm font-semibold text-navy">Verdicts and bands</h2>
          <p class="mt-1 text-xs text-ink-muted">Counted over the same verifications.</p>

          <div class="mt-4 grid gap-3 sm:grid-cols-3 xl:grid-cols-1">
            <div
              v-for="verdict in ['VALID', 'FRAUD']"
              :key="verdict"
              class="rounded-md border p-4"
              :class="verdict === 'VALID'
                ? 'border-valid-border bg-valid-surface'
                : 'border-fraud-border bg-fraud-surface'"
            >
              <p
                class="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide"
                :class="verdict === 'VALID' ? 'text-valid' : 'text-fraud'"
              >
                <span
                  class="h-2 w-2 rounded-full"
                  :class="verdict === 'VALID' ? 'bg-valid' : 'bg-fraud'"
                ></span>
                {{ verdict }}
              </p>
              <template v-if="verdictStat(verdict)">
                <p class="tabular mt-1 text-2xl font-semibold text-navy">{{ verdictStat(verdict).count }}</p>
                <p class="tabular mt-0.5 text-2xs text-ink-muted">
                  mean distance {{ formatDistance(verdictStat(verdict).mean_distance) }} ·
                  mean similarity {{ formatConfidence(verdictStat(verdict).mean_confidence) }}
                </p>
              </template>
              <p v-else class="mt-1 text-sm text-ink-subtle">No verifications yet.</p>
            </div>

            <div class="rounded-md border border-borderline-border bg-borderline-surface p-4">
              <p class="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-borderline">
                <span class="h-2 w-2 rounded-full bg-borderline"></span>
                Borderline
              </p>
              <p class="tabular mt-1 text-2xl font-semibold text-navy">{{ overview.verifications.borderline }}</p>
              <p class="tabular mt-0.5 text-2xs text-ink-muted">
                within ±{{ formatDistance(overview.model.borderline_margin) }} of the threshold,
                counted again in the verdicts above
              </p>
            </div>
          </div>
        </section>
      </div>

      <section class="border-t border-border pt-6">
        <div class="flex flex-wrap items-start justify-between gap-x-6 gap-y-3">
          <div class="min-w-0">
            <h2 class="text-sm font-semibold text-navy">Disputed results</h2>
            <p class="mt-1 max-w-prose text-xs text-ink-muted">
              You cannot see the signature, and you are not being asked to re-judge it. Decide
              whether the report is a usable training signal: a near-threshold score from an
              institution with a good record usually is; a confident score disputed by an
              institution whose reports keep getting rejected usually is not.
            </p>
          </div>
          <div
            class="flex shrink-0 gap-1 rounded-md border border-border bg-surface p-1"
            role="group"
            aria-label="Filter reports by status"
          >
            <button
              v-for="option in STATUS_FILTERS"
              :key="option.value"
              type="button"
              :aria-pressed="statusFilter === option.value"
              class="flex min-h-11 items-center gap-2 rounded px-3 text-sm font-medium"
              :class="statusFilter === option.value
                ? 'bg-navy text-ink-inverse'
                : 'text-ink hover:bg-sunken'"
              @click="applyStatus(option.value)"
            >
              {{ option.label }}
              <span
                class="tabular text-xs"
                :class="statusFilter === option.value ? 'text-white/70' : 'text-ink-subtle'"
              >{{ feedbackCount(option.value) }}</span>
            </button>
          </div>
        </div>

        <p v-if="actionError" class="mt-3 text-sm text-danger">{{ actionError }}</p>

        <p v-if="reports.length" class="tabular mt-4 text-xs text-ink-subtle">
          Showing all {{ reports.length }} {{ statusFilter }}
          {{ reports.length === 1 ? 'report' : 'reports' }} · filed {{ filedRange }}
        </p>

        <div v-if="reports.length" class="mt-2 overflow-x-auto rounded-md border border-border">
          <table class="w-full min-w-[62rem] text-sm">
            <thead class="bg-sunken text-xs font-semibold uppercase tracking-wide text-ink-muted">
              <tr class="border-b border-border text-left">
                <th scope="col" class="px-4 py-2.5 font-semibold">Report</th>
                <th scope="col" class="px-4 py-2.5 text-right font-semibold">Distance</th>
                <th scope="col" class="px-4 py-2.5 text-right font-semibold">From line</th>
                <th scope="col" class="px-4 py-2.5 text-right font-semibold">Similarity</th>
                <th scope="col" class="px-4 py-2.5 font-semibold">Reported by</th>
                <th scope="col" class="px-4 py-2.5 font-semibold">Filed</th>
                <th scope="col" class="px-4 py-2.5 font-semibold">Review</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-border">
              <tr
                v-for="report in reports"
                :key="report.feedback_id"
                class="align-top hover:bg-sunken"
              >
                <td class="px-4 py-2.5">
                  <p class="flex flex-wrap items-center gap-x-2 gap-y-1">
                    <span
                      class="flex items-center gap-1.5 font-semibold"
                      :class="bandTone(report.verification?.band).text"
                    >
                      <span
                        class="h-1.5 w-1.5 rounded-full"
                        :class="bandTone(report.verification?.band).dot"
                      ></span>
                      {{ report.verification?.verdict ?? 'unknown' }}
                    </span>
                    <span class="text-xs text-ink-subtle">reported as</span>
                    <span class="font-semibold text-ink">{{ report.claimed_label }}</span>
                    <span
                      v-if="report.verification?.band === 'borderline'"
                      class="rounded-sm border border-borderline-border bg-borderline-surface px-1.5 py-0.5 text-2xs font-semibold uppercase tracking-wide text-borderline"
                    >near threshold</span>
                  </p>
                  <p v-if="report.comment" class="mt-1 max-w-prose text-xs text-ink-muted">
                    “{{ report.comment }}”
                  </p>
                </td>
                <td class="tabular px-4 py-2.5 text-right">
                  {{ report.verification ? formatDistance(report.verification.distance) : '—' }}
                </td>
                <td class="tabular px-4 py-2.5 text-right">
                  <template v-if="report.verification">
                    {{ report.verification.margin > 0 ? '+' : '' }}{{ formatDistance(report.verification.margin) }}
                  </template>
                  <template v-else>—</template>
                </td>
                <td class="tabular px-4 py-2.5 text-right">
                  {{ report.verification ? formatConfidence(report.verification.confidence) : '—' }}
                </td>
                <td class="px-4 py-2.5">
                  <p class="text-ink">{{ report.reporter.organisation }}</p>
                  <p class="text-xs text-ink-subtle">{{ report.reporter.type }}</p>
                  <p class="tabular text-xs" :class="reporterClass(report.reporter)">
                    {{ reporterRecord(report.reporter) }}
                  </p>
                </td>
                <td class="px-4 py-2.5">
                  <p class="tabular text-xs text-ink-muted">{{ formatDateTime(report.created_at) }}</p>
                  <p class="tabular text-xs text-ink-subtle">{{ report.model_version }}</p>
                </td>
                <td class="px-4 py-2.5">
                  <div v-if="report.status === 'pending'" class="flex flex-wrap gap-2">
                    <button
                      type="button"
                      :disabled="actingId === report.feedback_id"
                      class="min-h-11 whitespace-nowrap rounded-md bg-navy px-3 text-sm font-semibold text-ink-inverse disabled:opacity-50"
                      @click="review(report, 'accepted')"
                    >
                      Accept
                    </button>
                    <button
                      type="button"
                      :disabled="actingId === report.feedback_id"
                      class="min-h-11 rounded-md border border-border-strong bg-surface px-3 text-sm font-medium text-ink disabled:opacity-50"
                      @click="review(report, 'rejected')"
                    >
                      Reject
                    </button>
                  </div>
                  <p v-else class="text-sm capitalize text-ink-muted">{{ report.status }}</p>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <!-- An empty queue is the state this panel exists to reach, so it is reported as a
             result rather than as a blank table. -->
        <div v-else class="mt-4 rounded-md border border-border px-4 py-10 text-center">
          <template v-if="statusFilter === 'pending'">
            <span class="mx-auto flex h-9 w-9 items-center justify-center rounded-full border border-valid-border bg-valid-surface">
              <svg
                class="h-4 w-4 text-valid"
                viewBox="0 0 20 20"
                fill="none"
                stroke="currentColor"
                stroke-width="2.2"
                stroke-linecap="round"
                stroke-linejoin="round"
                aria-hidden="true"
              >
                <path d="M4 10.5l4 4 8-8" />
              </svg>
            </span>
            <p class="mt-3 text-sm font-semibold text-ink">Queue clear</p>
            <p v-if="reviewedTotal" class="tabular mx-auto mt-1 max-w-prose text-xs text-ink-muted">
              No institution is waiting on a decision.
              {{ feedbackCount('accepted') }} accepted for retraining,
              {{ feedbackCount('rejected') }} rejected.
            </p>
            <p v-else class="mx-auto mt-1 max-w-prose text-xs text-ink-muted">
              No institution has disputed a result.
            </p>
          </template>
          <template v-else>
            <p class="text-sm font-semibold text-ink">No {{ statusFilter }} reports</p>
            <p class="tabular mx-auto mt-1 max-w-prose text-xs text-ink-muted">
              Nothing has been {{ statusFilter }} yet.
              {{ feedbackCount('pending') }} reports are waiting on a decision.
            </p>
          </template>
        </div>
      </section>
    </template>
  </div>
</template>
