<script setup>
import { computed, nextTick, ref } from 'vue'
import { postForm, ApiError } from '../api.js'
import { isClerk } from '../auth.js'
import {
  formatConfidence,
  formatDateTime,
  formatDistance,
  classifyDecision,
  decisionLabel,
} from '../format.js'

const NATIONAL_ID_PATTERN = /^\d{9}$/

const SCALE_MAX_DISTANCE = 1.0

/* How many anchors are shown before the "show all" toggle is offered. */
const PREVIEW_GROUP_SIZE = 3

const nationalId = ref('')
const file = ref(null)
const previewUrl = ref('')
const pending = ref(false)
const result = ref(null)
const errorNotice = ref(null) // { level: 'warning' | 'error', title: string, message: string }

const fileInput = ref(null)
const cameraInput = ref(null)
const chooseFileButton = ref(null)
const verdictHeading = ref(null)

const nationalIdTouched = ref(false)
const nationalIdValid = computed(() => NATIONAL_ID_PATTERN.test(nationalId.value))
const canSubmit = computed(() => nationalIdValid.value && !!file.value && !pending.value)

const showAllAnchors = ref(false)
const expandedAnchorKey = ref(null)

/* ---------- verdict ---------- */

const decision = computed(() =>
  result.value ? classifyDecision(result.value.distance, result.value.threshold) : null,
)

const verdictWord = computed(() =>
  result.value ? decisionLabel(decision.value, result.value.verdict) : '',
)

const verdictExplanation = computed(() => {
  if (decision.value === 'valid') {
    return 'This signature is close enough to the signatures held for this customer to be treated as genuine.'
  }
  if (decision.value === 'fraud') {
    return 'This signature is too different from the signatures held for this customer to be treated as genuine.'
  }
  return 'This result sits very close to the decision line, so the system cannot separate genuine from forged here. Treat it as unresolved: compare the signatures yourself below, or ask the customer to sign again.'
})

const verdictTheme = computed(() => {
  if (decision.value === 'valid') {
    return {
      panel: 'border-valid-border bg-valid-surface',
      word: 'text-valid',
      badge: 'border-valid text-valid',
      dot: 'bg-valid',
      glyph: '✓',
    }
  }
  if (decision.value === 'fraud') {
    return {
      panel: 'border-fraud-border bg-fraud-surface',
      word: 'text-fraud',
      badge: 'border-fraud text-fraud',
      dot: 'bg-fraud',
      glyph: '✕',
    }
  }
  return {
    panel: 'border-borderline-border bg-borderline-surface border-dashed',
    word: 'text-borderline',
    badge: 'border-borderline text-borderline',
    dot: 'bg-borderline',
    glyph: '?',
  }
})

/* A fraud call interrupts what the clerk is doing, so it is announced at once. */
const liveTone = computed(() => (result.value?.verdict === 'FRAUD' ? 'assertive' : 'polite'))

function scalePercent(value) {
  const ratio = Number(value) / SCALE_MAX_DISTANCE
  const clamped = Math.min(Math.max(Number.isFinite(ratio) ? ratio : 0, 0), 1)
  return `${(clamped * 100).toFixed(2)}%`
}

/* ---------- evidence ---------- */

const rawReferences = computed(() => result.value?.references ?? [])

const matchedCount = computed(() => rawReferences.value.filter((r) => r.passed).length)

const anchors = computed(() => {
  const groups = new Map()
  rawReferences.value.forEach((reference, index) => {
    const existing = groups.get(reference.image_png_base64)
    if (existing) {
      groups.set(reference.image_png_base64, { ...existing, count: existing.count + 1 })
      return
    }
    groups.set(reference.image_png_base64, {
      key: reference.reference_id,
      image: reference.image_png_base64,
      distance: Number(reference.distance),
      confidence: reference.confidence,
      passed: reference.passed,
      position: index + 1,
      count: 1,
    })
  })
  return [...groups.values()]
})

const duplicateCount = computed(() => rawReferences.value.length - anchors.value.length)

const anchorsByCloseness = computed(() =>
  [...anchors.value].sort((a, b) => a.distance - b.distance),
)

const hasHiddenAnchors = computed(
  () => anchorsByCloseness.value.length > PREVIEW_GROUP_SIZE * 2,
)

const closestAnchors = computed(() => anchorsByCloseness.value.slice(0, PREVIEW_GROUP_SIZE))

const furthestAnchors = computed(() =>
  [...anchorsByCloseness.value.slice(-PREVIEW_GROUP_SIZE)].reverse(),
)

const anchorGroups = computed(() => {
  if (showAllAnchors.value || !hasHiddenAnchors.value) {
    return [
      {
        id: 'all',
        title: `All ${anchorsByCloseness.value.length} reference signatures, closest first`,
        items: anchorsByCloseness.value,
      },
    ]
  }
  return [
    {
      id: 'closest',
      title: `The ${closestAnchors.value.length} closest references`,
      items: closestAnchors.value,
    },
    {
      id: 'furthest',
      title: `The ${furthestAnchors.value.length} furthest references`,
      items: furthestAnchors.value,
    },
  ]
})

function anchorKind(anchor) {
  return classifyDecision(anchor.distance, result.value.threshold)
}

function anchorLabel(anchor) {
  const kind = anchorKind(anchor)
  if (kind === 'valid') return 'Match'
  if (kind === 'fraud') return 'No match'
  return 'Too close to call'
}

function anchorTileClass(anchor) {
  const kind = anchorKind(anchor)
  if (kind === 'valid') return 'border-valid-border bg-valid-surface'
  if (kind === 'fraud') return 'border-fraud-border bg-fraud-surface'
  return 'border-borderline-border bg-borderline-surface border-dashed'
}

function anchorDotClass(anchor) {
  const kind = anchorKind(anchor)
  if (kind === 'valid') return 'bg-valid'
  if (kind === 'fraud') return 'bg-fraud'
  return 'bg-borderline'
}

function anchorAlt(anchor) {
  const shared =
    anchor.count > 1 ? `, stored ${anchor.count} times as identical copies` : ''
  return `Reference signature ${anchor.position} on file for this customer${shared}. ${anchorLabel(anchor)}, distance ${formatDistance(anchor.distance)}.`
}

function toggleAnchor(anchor) {
  expandedAnchorKey.value = expandedAnchorKey.value === anchor.key ? null : anchor.key
}

/* ---------- file handling ---------- */

function handleFileChange(event) {
  const chosen = event.target.files && event.target.files[0]
  if (!chosen) return
  setFile(chosen)
}

function setFile(chosen) {
  file.value = chosen
  if (previewUrl.value) URL.revokeObjectURL(previewUrl.value)
  previewUrl.value = URL.createObjectURL(chosen)
}

function openFilePicker() {
  fileInput.value?.click()
}

function openCamera() {
  cameraInput.value?.click()
}

/* ---------- submit ---------- */

function noticeFor(err) {
  if (!(err instanceof ApiError)) {
    return {
      level: 'error',
      title: 'The check could not be completed',
      message: 'Something went wrong on our side. Please try again.',
    }
  }
  if (err.code === 'CUSTOMER_NOT_FOUND' || err.status === 404) {
    return {
      level: 'warning',
      title: 'No customer with that national ID',
      message: err.message || 'Check the number, or enrol this customer first.',
    }
  }
  if (err.code === 'PAYLOAD_TOO_LARGE' || err.status === 413) {
    return {
      level: 'warning',
      title: 'That image is too large',
      message: err.message || 'Take the photo again at a smaller size, then try once more.',
    }
  }
  if (err.code === 'INVALID_IMAGE' || err.status === 422) {
    return {
      level: 'error',
      title: 'That image could not be read',
      message: err.message || 'Use a clear photo or scan of the signature on a plain background.',
    }
  }
  return {
    level: 'error',
    title: 'The check could not be completed',
    message: err.message || 'Please try again.',
  }
}

async function handleSubmit() {
  if (!canSubmit.value) return
  errorNotice.value = null
  result.value = null
  showAllAnchors.value = false
  expandedAnchorKey.value = null
  pending.value = true
  try {
    const formData = new FormData()
    formData.append('national_id', nationalId.value)
    formData.append('file', file.value)
    result.value = await postForm('/verify', formData)
    await nextTick()
    verdictHeading.value?.focus()
  } catch (err) {
    errorNotice.value = noticeFor(err)
  } finally {
    pending.value = false
  }
}

async function reset() {
  file.value = null
  if (previewUrl.value) URL.revokeObjectURL(previewUrl.value)
  previewUrl.value = ''
  errorNotice.value = null
  result.value = null
  showAllAnchors.value = false
  expandedAnchorKey.value = null
  await nextTick()
  chooseFileButton.value?.focus()
}
</script>

<template>
  <div class="mx-auto max-w-3xl">
    <h1 class="text-2xl font-bold text-navy">Verify a signature</h1>
    <p class="mt-1 text-sm text-ink-muted">
      Check a handwritten signature against the signatures held for a customer.
    </p>

    <!-- ---------------------------------------------------------------- form -->
    <form
      v-if="!result"
      class="mt-6 space-y-6 rounded-xl border border-border bg-surface p-6 shadow-sm"
      @submit.prevent="handleSubmit"
    >
      <div
        v-if="errorNotice"
        :class="errorNotice.level === 'warning'
          ? 'border-warning-border bg-warning-surface'
          : 'border-danger-border bg-danger-surface'"
        class="rounded-lg border px-4 py-3"
      >
        <p
          :class="errorNotice.level === 'warning' ? 'text-warning' : 'text-danger'"
          class="text-sm font-semibold"
        >
          {{ errorNotice.title }}
        </p>
        <p class="mt-1 text-sm text-ink">{{ errorNotice.message }}</p>
      </div>

      <div>
        <label for="national-id" class="mb-1 block text-sm font-medium text-ink">
          Customer national ID
        </label>
        <input
          id="national-id"
          v-model="nationalId"
          type="text"
          inputmode="numeric"
          autocomplete="off"
          maxlength="9"
          placeholder="9 digits"
          :aria-invalid="nationalIdTouched && !nationalIdValid"
          aria-describedby="national-id-error"
          class="min-h-11 w-full rounded-lg border border-border-strong bg-surface px-3 py-2 text-base text-ink placeholder:text-ink-subtle"
          @blur="nationalIdTouched = true"
        />
        <p
          v-if="nationalIdTouched && !nationalIdValid"
          id="national-id-error"
          class="mt-1 text-sm text-danger"
        >
          The national ID must be exactly 9 digits.
        </p>
      </div>

      <div>
        <span class="mb-1 block text-sm font-medium text-ink">Signature to check</span>
        <input ref="fileInput" type="file" accept="image/*" class="hidden" @change="handleFileChange" />
        <input
          ref="cameraInput"
          type="file"
          accept="image/*"
          capture="environment"
          class="hidden"
          @change="handleFileChange"
        />

        <div class="flex flex-col gap-3 sm:flex-row">
          <button
            ref="chooseFileButton"
            type="button"
            class="min-h-11 flex-1 rounded-lg border-2 border-dashed border-border-strong px-4 py-5 text-base text-ink-muted transition-colors hover:border-brand-green hover:text-navy"
            @click="openFilePicker"
          >
            Choose a file
          </button>
          <button
            type="button"
            class="min-h-11 flex-1 rounded-lg border-2 border-dashed border-border-strong px-4 py-5 text-base text-ink-muted transition-colors hover:border-brand-green hover:text-navy"
            @click="openCamera"
          >
            Use the camera
          </button>
        </div>

        <div v-if="previewUrl" class="mt-4 rounded-lg border border-border bg-sunken p-3">
          <img
            :src="previewUrl"
            alt="The signature image you selected, ready to be checked"
            class="mx-auto max-h-56 w-auto rounded"
          />
          <p class="mt-2 text-center text-xs text-ink-muted">Ready to check.</p>
        </div>
      </div>

      <button
        type="submit"
        :disabled="!canSubmit"
        class="min-h-11 w-full rounded-lg bg-brand-green px-4 py-3 text-base font-semibold text-navy transition enabled:hover:brightness-95 disabled:cursor-not-allowed disabled:bg-sunken disabled:text-ink-subtle"
      >
        {{ pending ? 'Checking the signature…' : 'Check this signature' }}
      </button>
    </form>

    <!-- -------------------------------------------------------------- result -->
    <section v-else class="mt-6 space-y-6">
      <div
        :class="verdictTheme.panel"
        role="status"
        :aria-live="liveTone"
        class="rounded-xl border-2 p-6 text-center sm:p-8"
      >
        <span
          :class="verdictTheme.badge"
          class="mx-auto mb-4 flex h-10 w-10 items-center justify-center rounded-full border-2 text-lg font-bold"
          aria-hidden="true"
        >
          {{ verdictTheme.glyph }}
        </span>

        <h2
          ref="verdictHeading"
          tabindex="-1"
          :class="verdictTheme.word"
          class="text-4xl font-bold tracking-tight"
        >
          {{ verdictWord }}
        </h2>

        <p class="mx-auto mt-3 max-w-xl text-base text-ink">{{ verdictExplanation }}</p>

        <p class="mt-4 text-sm text-ink-muted">
          Confidence in this verdict: {{ formatConfidence(result.confidence) }}
        </p>

        <!-- positional scale -->
        <div class="mx-auto mt-6 max-w-xl">
          <div class="relative h-3 rounded-full bg-sunken" aria-hidden="true">
            <div
              class="absolute inset-y-0 left-0 rounded-l-full bg-valid-surface"
              :style="{ width: scalePercent(result.threshold) }"
            ></div>
            <div
              class="absolute inset-y-0 right-0 rounded-r-full bg-fraud-surface"
              :style="{ left: scalePercent(result.threshold) }"
            ></div>
            <div
              class="absolute -top-1.5 -bottom-1.5 w-0.5 -translate-x-1/2 bg-ink-muted"
              :style="{ left: scalePercent(result.threshold) }"
            ></div>
            <div
              :class="verdictTheme.dot"
              class="absolute top-1/2 h-5 w-5 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-surface"
              :style="{ left: scalePercent(result.distance) }"
            ></div>
          </div>
          <div class="mt-2 flex justify-between text-2xs text-ink-muted">
            <span>Identical, 0.0000</span>
            <span>Nothing alike, 1.0000</span>
          </div>
          <p class="mt-3 text-sm text-ink">
            This signature scored {{ formatDistance(result.distance) }}. The upright line marks
            the decision threshold, {{ formatDistance(result.threshold) }}. Anything left of that
            line counts as a match, anything right of it does not.
          </p>
        </div>
      </div>

      <!-- evidence -->
      <div v-if="isClerk && rawReferences.length" class="space-y-4">
        <div>
          <h2 class="text-xl font-semibold text-navy">
            {{ matchedCount }} of {{ rawReferences.length }} reference signatures matched
          </h2>
          <p v-if="duplicateCount > 0" class="mt-1 text-sm text-ink-muted">
            {{ duplicateCount }} of them are repeat copies of an image already shown, so they are
            grouped together rather than counted as separate evidence.
          </p>
        </div>

        <div class="grid gap-6 md:grid-cols-[minmax(0,15rem)_minmax(0,1fr)]">
          <!-- submitted signature, stays in view while the anchors scroll -->
          <div class="sticky top-4 z-10 self-start rounded-xl border-2 border-navy bg-surface p-3">
            <h3 class="mb-2 text-sm font-semibold text-navy">The signature you submitted</h3>
            <img
              :src="previewUrl"
              alt="The signature submitted for this check, shown for comparison against the references on file"
              class="mx-auto max-h-28 w-auto rounded md:max-h-56"
            />
          </div>

          <!-- anchors -->
          <div class="space-y-6">
            <div v-for="group in anchorGroups" :key="group.id">
              <h3 class="mb-2 text-sm font-semibold text-ink">{{ group.title }}</h3>
              <div class="grid grid-cols-2 gap-3 sm:grid-cols-3">
                <template v-for="anchor in group.items" :key="group.id + anchor.key">
                  <button
                    type="button"
                    :aria-expanded="expandedAnchorKey === anchor.key"
                    :class="anchorTileClass(anchor)"
                    class="min-h-11 rounded-lg border-2 p-2 text-left transition-colors hover:brightness-95"
                    @click="toggleAnchor(anchor)"
                  >
                    <img
                      :src="'data:image/png;base64,' + anchor.image"
                      :alt="anchorAlt(anchor)"
                      class="h-20 w-full rounded bg-surface object-contain"
                    />
                    <span class="mt-2 flex items-center gap-1.5">
                      <span :class="anchorDotClass(anchor)" class="h-2 w-2 shrink-0 rounded-full"></span>
                      <span class="text-xs font-semibold text-ink">{{ anchorLabel(anchor) }}</span>
                      <span v-if="anchor.count > 1" class="text-2xs text-ink-muted">
                        &times;{{ anchor.count }}
                      </span>
                    </span>
                    <span class="mt-0.5 block text-2xs text-ink-muted">
                      Score {{ formatDistance(anchor.distance) }}
                    </span>
                  </button>

                  <div
                    v-if="expandedAnchorKey === anchor.key"
                    class="col-span-full rounded-lg border border-border bg-sunken p-4"
                  >
                    <h4 class="mb-3 text-sm font-semibold text-ink">
                      Reference {{ anchor.position }} compared with the submitted signature
                    </h4>
                    <div class="grid gap-4 sm:grid-cols-2">
                      <figure>
                        <img
                          :src="previewUrl"
                          :alt="`The submitted signature, shown beside reference ${anchor.position}`"
                          class="h-40 w-full rounded border border-border bg-surface object-contain"
                        />
                        <figcaption class="mt-1 text-xs text-ink-muted">Submitted now</figcaption>
                      </figure>
                      <figure>
                        <img
                          :src="'data:image/png;base64,' + anchor.image"
                          :alt="anchorAlt(anchor)"
                          class="h-40 w-full rounded border border-border bg-surface object-contain"
                        />
                        <figcaption class="mt-1 text-xs text-ink-muted">
                          Reference {{ anchor.position }} on file
                        </figcaption>
                      </figure>
                    </div>
                    <div class="relative mt-4 h-3 rounded-full bg-surface" aria-hidden="true">
                      <div
                        class="absolute -top-1.5 -bottom-1.5 w-0.5 -translate-x-1/2 bg-ink-muted"
                        :style="{ left: scalePercent(result.threshold) }"
                      ></div>
                      <div
                        :class="anchorDotClass(anchor)"
                        class="absolute top-1/2 h-4 w-4 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-surface"
                        :style="{ left: scalePercent(anchor.distance) }"
                      ></div>
                    </div>
                    <p class="mt-3 text-sm text-ink">
                      {{ anchorLabel(anchor) }}. Score {{ formatDistance(anchor.distance) }} against a
                      threshold of {{ formatDistance(result.threshold) }}, confidence
                      {{ formatConfidence(anchor.confidence) }}.
                    </p>
                    <p v-if="anchor.count > 1" class="mt-1 text-sm text-ink-muted">
                      This exact image is stored {{ anchor.count }} times, so treat it as one
                      signature, not {{ anchor.count }}.
                    </p>
                  </div>
                </template>
              </div>
            </div>

            <button
              v-if="hasHiddenAnchors"
              type="button"
              class="min-h-11 w-full rounded-lg border border-border-strong bg-surface px-4 py-2 text-sm font-medium text-navy transition-colors hover:bg-sunken"
              @click="showAllAnchors = !showAllAnchors"
            >
              {{ showAllAnchors
                ? 'Show only the closest and furthest references'
                : `Show all ${anchorsByCloseness.length} references` }}
            </button>
          </div>
        </div>
      </div>

      <!-- technical details, below the evidence -->
      <details class="rounded-lg border border-border bg-surface">
        <summary class="min-h-11 cursor-pointer px-4 py-3 text-sm font-medium text-ink marker:text-ink-subtle">
          Technical details
        </summary>
        <dl class="space-y-2 border-t border-border px-4 py-3 text-sm">
          <div class="flex flex-wrap gap-x-2">
            <dt class="text-ink-muted">Model version:</dt>
            <dd class="text-ink">{{ result.model_version }}</dd>
          </div>
          <div class="flex flex-wrap gap-x-2">
            <dt class="text-ink-muted">Request reference:</dt>
            <dd class="break-all text-ink">{{ result.request_id }}</dd>
          </div>
          <div class="flex flex-wrap gap-x-2">
            <dt class="text-ink-muted">Checked at:</dt>
            <dd class="text-ink">{{ formatDateTime(result.verified_at) }}</dd>
          </div>
          <div class="flex flex-wrap gap-x-2">
            <dt class="text-ink-muted">Distance and threshold:</dt>
            <dd class="text-ink">
              {{ formatDistance(result.distance) }} against {{ formatDistance(result.threshold) }}
            </dd>
          </div>
        </dl>
      </details>

      <button
        type="button"
        class="min-h-11 w-full rounded-lg bg-navy px-6 py-3 text-base font-semibold text-ink-inverse transition hover:brightness-110 sm:w-auto"
        @click="reset"
      >
        Check another signature
      </button>
    </section>
  </div>
</template>
