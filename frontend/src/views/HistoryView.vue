<script setup>
import { computed, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { get, postJson } from '../api.js'
import { isClerk } from '../auth.js'
import { formatDistance, formatConfidence, formatDateTime, decisionLabel, isNationalId, pngSrc } from '../format.js'
import NoticeBanner from '../components/NoticeBanner.vue'

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
const benchIndex = ref(0)
const reportLabel = ref('')
const reportComment = ref('')
const reportError = ref('')
const reportSubmitting = ref(false)

const nationalIdValid = computed(
  () => nationalIdFilter.value === '' || isNationalId(nationalIdFilter.value),
)

// Never colour alone: each band carries a glyph and its own word as well as a hue.
const BAND_THEMES = {
  valid: { chip: 'border-valid-border bg-valid-surface text-valid', glyph: '✓' },
  fraud: { chip: 'border-fraud-border bg-fraud-surface text-fraud', glyph: '✕' },
  borderline: {
    chip: 'border-borderline-border border-dashed bg-borderline-surface text-borderline',
    glyph: '?',
  },
}

function bandTheme(band) {
  return BAND_THEMES[band] ?? BAND_THEMES.borderline
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
    errorMessage.value = err.message || 'Failed to load history.'
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

// The references the enrolling side is allowed to see; a subscriber gets none at all.
const references = computed(() => detail.value?.references ?? [])

// Whichever reference is on the bench, with a fallback if the set came back shorter.
const benchReference = computed(
  () => references.value[benchIndex.value] ?? references.value[0] ?? null,
)

const benchPosition = computed(() =>
  references.value.length ? Math.min(benchIndex.value, references.value.length - 1) + 1 : 0,
)

async function toggleRow(row) {
  if (expandedId.value === row.request_id) {
    expandedId.value = ''
    detail.value = null
    return
  }
  expandedId.value = row.request_id
  benchIndex.value = 0
  reportLabel.value = row.verdict === 'VALID' ? 'forged' : 'genuine'
  reportComment.value = ''
  reportError.value = ''

  // Fetched only when a row is opened, one row at a time. The list carries a has_image
  // flag rather than the pictures: a page shipping every signature the organisation had
  // ever queried would be both enormous and a standing disclosure.
  detail.value = null
  detailError.value = ''
  detailLoading.value = true
  try {
    const opened = row.request_id
    const body = await get(`/verifications/${opened}`)
    if (expandedId.value === opened) detail.value = body
  } catch (err) {
    detailError.value = err.message || 'Could not load this result.'
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
      <h1 class="text-xl font-semibold text-navy">Verification history</h1>
      <p class="mt-1 max-w-prose text-sm text-ink-muted">
        Every check your organisation has run. Flag a result you believe was wrong and it
        goes to the engineering team; the recorded verdict never changes.
      </p>
    </div>

    <!-- Filters sit on the canvas, divided from the table by a rule rather than boxed. -->
    <div class="flex flex-wrap items-end gap-x-4 gap-y-3 border-b border-border pb-4">
      <div>
        <span
          id="history-verdict-label"
          class="mb-1 block text-xs font-semibold uppercase tracking-wide text-ink-muted"
        >
          Verdict
        </span>
        <div
          class="flex divide-x divide-border-strong overflow-hidden rounded-md border border-border-strong"
          role="group"
          aria-labelledby="history-verdict-label"
        >
          <button
            v-for="option in VERDICT_FILTERS"
            :key="option.value"
            type="button"
            :aria-pressed="verdictFilter === option.value"
            class="min-h-11 px-4 text-sm font-medium transition-colors"
            :class="verdictFilter === option.value
              ? 'bg-navy text-ink-inverse'
              : 'bg-surface text-ink hover:bg-sunken'"
            @click="applyVerdict(option.value)"
          >
            {{ option.label }}
          </button>
        </div>
      </div>

      <div class="min-w-64 flex-1 sm:max-w-sm">
        <label
          class="mb-1 block text-xs font-semibold uppercase tracking-wide text-ink-muted"
          for="history-national-id"
        >
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
            :aria-invalid="!nationalIdValid"
            aria-describedby="history-national-id-error"
            class="tabular min-h-11 flex-1 rounded-md border border-border-strong bg-surface px-3 text-sm text-ink"
            @keyup.enter="loadHistory"
          />
          <button
            type="button"
            :disabled="!nationalIdValid || loading"
            class="min-h-11 rounded-md bg-navy px-4 text-sm font-semibold text-ink-inverse disabled:cursor-not-allowed disabled:opacity-50"
            @click="loadHistory"
          >
            Search
          </button>
        </div>
      </div>

      <button
        v-if="filtersActive"
        type="button"
        class="min-h-11 px-2 text-sm font-medium text-ink-muted underline underline-offset-2"
        @click="clearFilters"
      >
        Clear
      </button>

      <p v-if="!nationalIdValid" id="history-national-id-error" class="w-full text-sm text-danger">
        National ID must be exactly 9 digits.
      </p>
    </div>

    <NoticeBanner v-if="errorMessage">
      {{ errorMessage }}
    </NoticeBanner>

    <div
      v-else-if="loading"
      role="status"
      class="rounded-md border border-border bg-surface px-6 py-16 text-center text-sm text-ink-muted"
    >
      Loading history…
    </div>

    <!-- Nothing to show is a state of its own, not a blank page. -->
    <div
      v-else-if="verifications.length === 0"
      class="rounded-md border border-border bg-surface px-6 py-16 text-center"
    >
      <svg
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        stroke-width="1.25"
        aria-hidden="true"
        class="mx-auto h-10 w-10 text-ink-subtle"
      >
        <path
          stroke-linecap="round"
          stroke-linejoin="round"
          d="M9 5H7a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V7a2 2 0 0 0-2-2h-2M9 5a2 2 0 0 0 2 2h2a2 2 0 0 0 2-2M9 5a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2m-6 9 2 2 4-4"
        />
      </svg>
      <p class="mt-4 text-sm font-semibold text-ink">
        {{ filtersActive ? 'No verifications match these filters' : 'No verifications yet' }}
      </p>
      <p class="mx-auto mt-1 max-w-prose text-sm text-ink-muted">
        <template v-if="filtersActive">
          Your organisation has run checks, but none of them match what you asked for.
        </template>
        <template v-else>
          Every signature your organisation checks is recorded here, with the image the
          model compared kept for 90 days.
        </template>
      </p>
      <div class="mt-4 flex justify-center">
        <button
          v-if="filtersActive"
          type="button"
          class="min-h-11 rounded-md border border-border-strong bg-surface px-4 text-sm font-medium text-navy transition-colors hover:bg-sunken"
          @click="clearFilters"
        >
          Clear the filters
        </button>
        <RouterLink
          v-else
          :to="{ name: 'verify' }"
          class="flex min-h-11 items-center rounded-md bg-navy px-4 text-sm font-semibold text-ink-inverse"
        >
          Run a verification
        </RouterLink>
      </div>
    </div>

    <div v-else class="space-y-2">
      <!-- A total, not just a page. Without it the newest rows look like all the rows. -->
      <p class="text-xs text-ink-muted">
        <span class="tabular font-semibold text-ink">{{ total }}</span>
        verification{{ total === 1 ? '' : 's' }}{{ filtersActive ? ' match these filters' : ' recorded' }},
        newest first.
      </p>

      <!-- A table is a distinct object, so it keeps a hairline border and no shadow. -->
      <div class="rounded-md border border-border bg-surface">
        <div class="overflow-x-auto">
          <table class="w-full text-sm">
            <caption class="sr-only">Verification history, most recent first</caption>
            <thead>
              <tr
                class="border-b border-border bg-sunken text-xs font-semibold uppercase tracking-wide text-ink-muted"
              >
                <th scope="col" class="px-4 py-2 text-left font-semibold">Customer</th>
                <th scope="col" class="px-4 py-2 text-left font-semibold">Verdict</th>
                <th scope="col" class="px-4 py-2 text-right font-semibold">Distance</th>
                <th scope="col" class="px-4 py-2 text-right font-semibold">Similarity</th>
                <th scope="col" class="px-4 py-2 text-left font-semibold">Checked by</th>
                <th scope="col" class="px-4 py-2 text-left font-semibold">When</th>
                <th scope="col" class="px-4 py-2 text-left font-semibold">Report</th>
                <th scope="col" class="px-4 py-2 text-right font-semibold">
                  <span class="sr-only">Details</span>
                </th>
              </tr>
            </thead>
            <tbody class="divide-y divide-border">
              <template v-for="v in verifications" :key="v.request_id">
                <!-- The whole row opens the result; the button in the last cell is the
                     same control for anyone not using a pointer. -->
                <tr
                  class="cursor-pointer hover:bg-sunken"
                  :class="expandedId === v.request_id ? 'bg-sunken' : ''"
                  @click="toggleRow(v)"
                >
                  <td class="px-4 py-2.5">
                    <span class="block font-medium text-ink">{{ v.customer_name }}</span>
                    <code class="tabular block text-xs text-ink-subtle">{{ v.national_id_masked }}</code>
                  </td>
                  <td class="px-4 py-2.5">
                    <span
                      class="inline-flex items-center gap-1.5 rounded-md border px-2 py-0.5 text-xs font-semibold"
                      :class="bandTheme(v.band).chip"
                    >
                      <span aria-hidden="true">{{ bandTheme(v.band).glyph }}</span>
                      {{ decisionLabel(v.band, v.verdict) }}
                    </span>
                  </td>
                  <td class="tabular px-4 py-2.5 text-right text-ink">{{ formatDistance(v.distance) }}</td>
                  <td class="tabular px-4 py-2.5 text-right text-ink">{{ formatConfidence(v.confidence) }}</td>
                  <td class="px-4 py-2.5 text-ink-muted">{{ v.performed_by }}</td>
                  <td class="tabular whitespace-nowrap px-4 py-2.5 text-ink-muted">
                    {{ formatDateTime(v.created_at) }}
                  </td>
                  <td class="px-4 py-2.5 text-xs">
                    <span v-if="v.feedback" class="text-ink-muted">
                      {{ v.feedback.claimed_label }} · {{ v.feedback.status }}
                    </span>
                    <span v-else class="text-ink-subtle" aria-hidden="true">-</span>
                  </td>
                  <td class="px-4 py-2.5 text-right">
                    <button
                      type="button"
                      class="ml-auto flex min-h-11 items-center gap-1.5 px-1 text-sm font-medium text-navy"
                      :aria-expanded="expandedId === v.request_id"
                      :aria-label="`${expandedId === v.request_id ? 'Hide' : 'Show'} the compared signature for ${v.customer_name}`"
                      @click.stop="toggleRow(v)"
                    >
                      {{ expandedId === v.request_id ? 'Hide' : 'Details' }}
                      <svg
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="currentColor"
                        stroke-width="2"
                        aria-hidden="true"
                        class="h-3.5 w-3.5"
                        :class="expandedId === v.request_id ? 'rotate-180' : ''"
                      >
                        <path stroke-linecap="round" stroke-linejoin="round" d="m6 9 6 6 6-6" />
                      </svg>
                    </button>
                  </td>
                </tr>

                <tr v-if="expandedId === v.request_id">
                  <td colspan="8" class="bg-sunken px-4 py-4">
                    <div class="sticky left-0 w-[calc(100vw-2rem)] max-w-full sm:w-[calc(100vw-3rem)] lg:w-auto">
                    <div class="space-y-4">
                      <p v-if="detailLoading" role="status" class="text-sm text-ink-muted">
                        Loading this result…
                      </p>
                      <p v-else-if="detailError" class="text-sm text-danger">{{ detailError }}</p>

                      <template v-else-if="detail && detail.request_id === v.request_id">
                        <!-- The comparison bench, as on the verify screen: questioned beside
                             known, cropped and at one scale, so a difference on screen is a
                             difference the model saw. -->
                        <div class="overflow-hidden rounded-md border border-border bg-surface">
                          <div
                            class="grid gap-px bg-border"
                            :class="benchReference ? 'sm:grid-cols-2' : ''"
                          >
                            <figure class="bg-surface p-4">
                              <figcaption class="mb-3 flex items-baseline justify-between gap-2">
                                <span class="text-sm font-semibold text-ink">Checked in this verification</span>
                                <span class="text-2xs uppercase tracking-wide text-ink-subtle">Questioned</span>
                              </figcaption>
                              <img
                                v-if="detail.compared_png_base64"
                                :src="pngSrc(detail.compared_png_base64)"
                                alt="The signature that was checked, as the model read it"
                                class="h-40 w-full rounded-md border border-border bg-surface object-contain lg:h-48"
                              />
                              <p
                                v-else
                                class="tabular flex h-40 items-center justify-center rounded-md border border-dashed border-border bg-sunken px-4 text-center text-xs text-ink-muted lg:h-48"
                              >
                                The checked image is no longer kept. Images are held for
                                {{ detail.retention_days }} days; the result itself is permanent.
                              </p>
                            </figure>

                            <figure v-if="benchReference" class="bg-surface p-4">
                              <figcaption class="mb-3 flex items-baseline justify-between gap-2">
                                <span class="text-sm font-semibold text-ink">
                                  Reference <span class="tabular">{{ benchPosition }}</span> of
                                  <span class="tabular">{{ references.length }}</span> on file
                                </span>
                                <span class="text-2xs uppercase tracking-wide text-ink-subtle">Known</span>
                              </figcaption>
                              <img
                                :src="pngSrc(benchReference.image_png_base64)"
                                :alt="`Reference signature ${benchPosition} held for this customer`"
                                class="h-40 w-full rounded-md border border-border bg-surface object-contain lg:h-48"
                              />
                            </figure>
                          </div>

                          <div
                            class="flex flex-wrap items-center gap-x-4 gap-y-2 border-t border-border px-4 py-3"
                          >
                            <span class="flex items-center gap-2">
                              <span
                                aria-hidden="true"
                                class="flex h-5 w-5 items-center justify-center rounded-full border text-2xs font-bold"
                                :class="bandTheme(detail.band).chip"
                              >
                                {{ bandTheme(detail.band).glyph }}
                              </span>
                              <span class="text-sm font-semibold text-ink">
                                {{ decisionLabel(detail.band, detail.verdict) }}
                              </span>
                            </span>
                            <span class="tabular text-sm text-ink-muted">
                              Distance {{ formatDistance(detail.distance) }} against
                              {{ formatDistance(detail.threshold_used) }}
                            </span>
                            <span class="tabular text-sm text-ink-muted">
                              Similarity {{ formatConfidence(detail.confidence) }}
                            </span>
                          </div>
                        </div>

                        <!-- The stored references carry no distance of their own: those were
                             computed at the time and the set can have changed since. -->
                        <div v-if="references.length > 1">
                          <h3 class="text-sm font-semibold text-ink">
                            All <span class="tabular">{{ references.length }}</span> signatures on
                            file for this customer now
                          </h3>
                          <p class="mt-0.5 text-xs text-ink-subtle">
                            Shown as they stand today, so they carry no distance of their own.
                            Pick one to put it on the bench.
                          </p>
                          <div class="mt-3 flex snap-x gap-3 overflow-x-auto pb-1">
                            <button
                              v-for="(reference, index) in references"
                              :key="reference.reference_id"
                              type="button"
                              :aria-pressed="index === benchIndex"
                              class="w-28 shrink-0 snap-start rounded-md border bg-surface p-2 text-left"
                              :class="index === benchIndex
                                ? 'border-navy ring-1 ring-navy'
                                : 'border-border hover:border-border-strong'"
                              @click="benchIndex = index"
                            >
                              <img
                                :src="pngSrc(reference.image_png_base64)"
                                :alt="`Reference signature ${index + 1} on file for this customer`"
                                class="h-14 w-full rounded bg-surface object-contain"
                              />
                              <span
                                class="mt-1.5 block text-2xs font-medium"
                                :class="index === benchIndex ? 'text-navy' : 'text-ink-subtle'"
                              >
                                {{ index === benchIndex ? 'On the bench' : `Reference ${index + 1}` }}
                              </span>
                            </button>
                          </div>
                        </div>

                        <!-- What the counter did about it. Only shown when there is one. -->
                        <div v-if="detail.outcome" class="border-t border-border pt-3 text-sm">
                          <p class="text-ink">
                            <span class="font-medium">{{ OUTCOME_LABELS[detail.outcome.outcome] }}</span>
                            by {{ detail.outcome.recorded_by }},
                            <span class="tabular">{{ formatDateTime(detail.outcome.recorded_at) }}</span>
                          </p>
                          <p v-if="detail.outcome.reason" class="mt-1 text-ink-muted">
                            {{ detail.outcome.reason }}
                          </p>
                        </div>
                      </template>

                      <!-- Reporting belongs to the enrolling side: a merchant is paid either way,
                           so the cheapest correction they could file is always "that fraud was
                           fine", and these reports are engineering's ground truth. Nothing is
                           shown in place of the form. -->

                      <!-- A result can only be reported once, so the form goes once it is used
                           while the row itself stays open for reading. -->
                      <div
                        v-if="isClerk && v.feedback"
                        class="border-t border-border pt-3 text-sm text-ink-muted"
                      >
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
                            class="flex min-h-11 cursor-pointer items-center gap-2 rounded-md border px-3 text-sm"
                            :class="reportLabel === option.value
                              ? 'border-navy bg-surface font-medium text-navy'
                              : 'border-border-strong bg-surface text-ink'"
                          >
                            <input v-model="reportLabel" type="radio" :value="option.value" class="shrink-0" />
                            {{ option.label }}
                          </label>
                        </div>

                        <label class="block">
                          <span class="mb-1 block text-sm font-medium text-ink">Notes (optional)</span>
                          <textarea
                            v-model="reportComment"
                            rows="2"
                            maxlength="500"
                            placeholder="What did you observe that the system missed?"
                            class="w-full rounded-md border border-border-strong bg-surface px-3 py-2 text-sm text-ink"
                          ></textarea>
                        </label>

                        <p v-if="reportError" class="text-sm text-danger">{{ reportError }}</p>

                        <div class="flex flex-wrap gap-2">
                          <button
                            type="button"
                            :disabled="reportSubmitting"
                            class="min-h-11 rounded-md bg-navy px-4 text-sm font-semibold text-ink-inverse disabled:opacity-50"
                            @click="submitReport(v)"
                          >
                            {{ reportSubmitting ? 'Sending…' : 'Send report' }}
                          </button>
                          <button
                            type="button"
                            class="min-h-11 rounded-md border border-border-strong bg-surface px-4 text-sm font-medium text-ink transition-colors hover:bg-sunken"
                            @click="expandedId = ''"
                          >
                            Cancel
                          </button>
                        </div>
                      </div>
                    </div>
                  </div>
                  </td>
                </tr>
              </template>
            </tbody>
          </table>
        </div>

        <div
          class="flex flex-wrap items-center justify-between gap-3 border-t border-border px-4 py-3 text-sm"
        >
          <p class="tabular text-ink-muted">
            Showing {{ firstShown }}–{{ lastShown }} of {{ total }}
          </p>
          <div class="flex gap-2">
            <button
              type="button"
              :disabled="!hasPrevious || loading"
              class="min-h-11 rounded-md border border-border-strong bg-surface px-3 text-sm font-medium text-navy transition-colors hover:bg-sunken disabled:text-ink-subtle disabled:hover:bg-surface"
              @click="goToPage(-1)"
            >
              Newer
            </button>
            <button
              type="button"
              :disabled="!hasNext || loading"
              class="min-h-11 rounded-md border border-border-strong bg-surface px-3 text-sm font-medium text-navy transition-colors hover:bg-sunken disabled:text-ink-subtle disabled:hover:bg-surface"
              @click="goToPage(1)"
            >
              Older
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
