<script setup>
import { computed, nextTick, ref } from 'vue'
import { postForm, postJson, ApiError } from '../api.js'
import { isClerk } from '../auth.js'
import { assessCapture } from '../capture.js'
import CaptureGuide from '../components/CaptureGuide.vue'
import {
  formatConfidence,
  formatDateTime,
  formatDistance,
  decisionLabel,
  noticeClass,
  isNationalId,
  pngSrc,
} from '../format.js'

const SCALE_MAX_DISTANCE = 1.0


const nationalId = ref('')
const originalFile = ref(null)
const originalPreviewUrl = ref('')
const pending = ref(false)
const result = ref(null)
const errorNotice = ref(null) // { level: 'warning' | 'error', title: string, message: string }

const captureNotice = ref(null) // { level: 'good' | 'warning' | 'error', title, message }

const regions = ref([])
const regionPending = ref(false)
const chosenRegion = ref(null)

const fileInput = ref(null)
const cameraInput = ref(null)
const chooseFileButton = ref(null)
const verdictHeading = ref(null)

const nationalIdTouched = ref(false)
const nationalIdValid = computed(() => isNationalId(nationalId.value))

/* ---------- which image gets checked ---------- */

const activeRegion = computed(() =>
  typeof chosenRegion.value === 'number'
    ? regions.value.find((region) => region.position === chosenRegion.value) ?? null
    : null,
)

const submissionFile = computed(() => activeRegion.value?.file ?? originalFile.value)

/* What the whole picture looks like once the model has normalised it. Choosing the whole
   image sends the original photograph, which /verify neither extracts nor cleans, so
   this is the only chance to see what is really being compared before committing. */
const wholePreview = ref('')

const previewUrl = computed(() =>
  activeRegion.value
    ? pngSrc(activeRegion.value.image)
    : originalPreviewUrl.value,
)

const awaitingChoice = computed(() => !!originalFile.value && chosenRegion.value === null)

const canSubmit = computed(
  () =>
    nationalIdValid.value &&
    !!submissionFile.value &&
    !awaitingChoice.value &&
    !regionPending.value &&
    !pending.value,
)

const submitLabel = computed(() => {
  if (pending.value) return 'Checking the signature…'
  if (regionPending.value) return 'Looking for the signature…'
  if (awaitingChoice.value) return 'Choose which marking is the signature'
  return 'Check this signature'
})

const previewCaption = computed(() => {
  if (activeRegion.value) {
    return 'Cut out of your photo and evened for lighting. This is exactly what is compared.'
  }
  if (awaitingChoice.value) return 'Choose which marking is the signature to continue.'
  if (regions.value.length > 0) return 'The whole image will be checked.'
  return 'Ready to check.'
})

/* One steady live region. Announcing the picker itself would read out every card. */
const regionAnnouncement = computed(() => {
  if (regionPending.value) return 'Looking for the signature in this image.'
  if (regions.value.length > 1 && chosenRegion.value === null) {
    return 'More than one marking was found in this image. Choose which one is the signature, or use the whole image.'
  }
  if (regions.value.length === 1 && activeRegion.value) {
    return 'The signature was found and cut out of the picture.'
  }
  return ''
})

const comparedImageUrl = computed(() =>
  result.value?.query_preview_png_base64
    ? pngSrc(result.value.query_preview_png_base64)
    : previewUrl.value,
)

const benchKey = ref(null)

/* ---------- verdict ---------- */

const decision = computed(() =>
  result.value ? result.value.band : null,
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
      rule: 'border-valid-border divide-valid-border',
      word: 'text-valid',
      badge: 'border-valid text-valid',
      dot: 'bg-valid',
      glyph: '✓',
    }
  }
  if (decision.value === 'fraud') {
    return {
      panel: 'border-fraud-border bg-fraud-surface',
      rule: 'border-fraud-border divide-fraud-border',
      word: 'text-fraud',
      badge: 'border-fraud text-fraud',
      dot: 'bg-fraud',
      glyph: '✕',
    }
  }
  return {
    panel: 'border-borderline-border bg-borderline-surface border-dashed',
    rule: 'border-borderline-border divide-borderline-border',
    word: 'text-borderline',
    badge: 'border-borderline text-borderline',
    dot: 'bg-borderline',
    glyph: '?',
  }
})

/* A fraud call interrupts what the clerk is doing, so it is announced at once. */
const liveTone = computed(() => (result.value?.verdict === 'FRAUD' ? 'assertive' : 'polite'))

function scaleRatio(value) {
  const ratio = Number(value) / SCALE_MAX_DISTANCE
  return Math.min(Math.max(Number.isFinite(ratio) ? ratio : 0, 0), 1)
}

/* The span either side of the line where the model cannot separate genuine from forged.
   Width comes from the response, so the rule is not duplicated here. */
const uncertainSpan = computed(() => {
  const margin = result.value?.borderline_margin
  if (!margin) return null
  return {
    left: scalePercent(result.value.threshold - margin),
    right: `${100 - parseFloat(scalePercent(result.value.threshold + margin))}%`,
  }
})

function scalePercent(value) {
  return `${(scaleRatio(value) * 100).toFixed(2)}%`
}

/* A label centred on the marker would hang off the track at the extremes of the scale. */
function labelPercent(value) {
  const pct = scaleRatio(value) * 100
  return `${Math.min(Math.max(pct, 7), 93).toFixed(2)}%`
}

/* How far the score landed from the line. Arithmetic on two numbers the server sent,
   not a second opinion about the band: that arrives decided and is never re-derived. */
const gapFromLine = computed(() =>
  result.value ? Math.abs(Number(result.value.distance) - Number(result.value.threshold)) : 0,
)

const onMatchSide = computed(
  () => !!result.value && Number(result.value.distance) < Number(result.value.threshold),
)

const scaleSummary = computed(() => {
  if (!result.value) return ''
  const score = formatDistance(result.value.distance)
  const gap = formatDistance(gapFromLine.value)
  const line = formatDistance(result.value.threshold)
  if (decision.value === 'borderline') {
    return `It scored ${score}, only ${gap} from the decision line at ${line} - too close for the model to tell a genuine signature from a forged one.`
  }
  if (onMatchSide.value) {
    return `It scored ${score}, which is ${gap} inside the decision line at ${line}. Closer to the left is more alike.`
  }
  return `It scored ${score}, which is ${gap} beyond the decision line at ${line}. Closer to the right is less alike.`
})

/* ---------- evidence ---------- */

const rawReferences = computed(() => result.value?.references ?? [])

const matchedCount = computed(() => rawReferences.value.filter((r) => r.band === 'valid').length)

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
      band: reference.band,
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

/* Whichever reference is on the bench. Defaults to the closest, which is the one the
   verdict turned on, and falls back if the set changed under it. */
const benchAnchor = computed(
  () => anchorsByCloseness.value.find((a) => a.key === benchKey.value)
    ?? anchorsByCloseness.value[0]
    ?? null,
)



const ANCHOR_THEMES = {
  valid: { label: 'Match', tile: 'border-valid-border bg-valid-surface', dot: 'bg-valid' },
  fraud: { label: 'No match', tile: 'border-fraud-border bg-fraud-surface', dot: 'bg-fraud' },
  borderline: {
    label: 'Too close to call',
    tile: 'border-borderline-border bg-borderline-surface border-dashed',
    dot: 'bg-borderline',
  },
}

function anchorTheme(anchor) {
  return ANCHOR_THEMES[anchor.band] ?? ANCHOR_THEMES.borderline
}

function anchorAlt(anchor) {
  const shared =
    anchor.count > 1 ? `, stored ${anchor.count} times as identical copies` : ''
  return `Reference signature ${anchor.position} on file for this customer${shared}. ${anchorTheme(anchor).label}, distance ${formatDistance(anchor.distance)}.`
}

/* ---------- file handling ---------- */

const captureTheme = computed(() => noticeClass(captureNotice.value?.level ?? 'warning'))

function handleFileChange(event) {
  const chosen = event.target.files && event.target.files[0]
  if (!chosen) return
  setFile(chosen)
  findRegions(chosen)
  assessFile(chosen)
}

async function assessFile(chosen) {
  captureNotice.value = null
  const verdict = await assessCapture(chosen)
  if (originalFile.value !== chosen) return
  captureNotice.value = verdict
}

/* Judge what the model will actually compare, not the raw upload.
   The server evens out lighting before embedding, so warning about a shadow it has
   already removed tells the clerk to retake a photo that was fine. */
async function assessPrepared(scan, prepared) {
  const verdict = await assessCapture(prepared)
  if (originalFile.value !== scan) return
  captureNotice.value = verdict.level === 'good' ? null : verdict
}

function setFile(chosen) {
  originalFile.value = chosen
  if (originalPreviewUrl.value) URL.revokeObjectURL(originalPreviewUrl.value)
  originalPreviewUrl.value = URL.createObjectURL(chosen)
}

function clearFile() {
  originalFile.value = null
  if (originalPreviewUrl.value) URL.revokeObjectURL(originalPreviewUrl.value)
  originalPreviewUrl.value = ''
  captureNotice.value = null
  clearRegions()
}

function clearRegions() {
  regions.value = []
  wholePreview.value = ''
  chosenRegion.value = null
}

function base64ToFile(base64, name) {
  const binary = atob(base64)
  const bytes = new Uint8Array(binary.length)
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i)
  return new File([bytes], name, { type: 'image/png' })
}

async function findRegions(chosen) {
  errorNotice.value = null
  clearRegions()
  regionPending.value = true
  const scan = chosen
  try {
    const formData = new FormData()
    formData.append('file', chosen)
    const data = await postForm('/verify/regions', formData)
    if (originalFile.value !== scan) return
    const found = Array.isArray(data?.regions) ? data.regions : []
    regions.value = found.map((region, order) => ({
      position: order + 1,
      // Two images on purpose: `image` is a thumbnail to look at, because a phone
      // discards the page rather than hold several full bitmaps; `file` is the
      // full-resolution region that gets submitted, since downscaling moves the distance.
      image: region.preview_png_base64,
      clipped: !!region.clipped,
      file: base64ToFile(region.image_png_base64, `signature-${order + 1}.png`),
    }))
    wholePreview.value = data?.whole_preview_png_base64 ?? ''
    if (regions.value.length === 0) chosenRegion.value = 'whole'
    else if (regions.value.length === 1) chosenRegion.value = 1
    else chosenRegion.value = null

    // Now that the prepared image exists, judge that instead of the raw upload.
    if (regions.value.length === 1) assessPrepared(scan, regions.value[0].file)
  } catch (err) {
    if (originalFile.value !== scan) return
    const unreadable =
      err instanceof ApiError && (err.code === 'INVALID_IMAGE' || err.status === 422)
    if (unreadable) {
      errorNotice.value = noticeFor(err)
      clearFile()
      return
    }
    regions.value = []
    chosenRegion.value = 'whole'
  } finally {
    if (originalFile.value === scan || !originalFile.value) regionPending.value = false
  }
}

function chooseRegion(position) {
  chosenRegion.value = position
}

function chooseWholeImage() {
  chosenRegion.value = 'whole'
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
  clearOutcome()
  pending.value = true
  try {
    const formData = new FormData()
    formData.append('national_id', nationalId.value)
    formData.append('file', submissionFile.value)
    result.value = await postForm('/verify', formData)
    await nextTick()
    verdictHeading.value?.focus()
  } catch (err) {
    errorNotice.value = noticeFor(err)
  } finally {
    pending.value = false
  }
}

/* ---------- what the counter did next ---------- */

/* The evidence above exists so a person can disagree with the model. Without somewhere
   to say what they actually did, that decision leaves no trace at all. */
const OUTCOMES = [
  { value: 'accepted', label: 'Honoured it' },
  { value: 'rejected', label: 'Refused it' },
  { value: 'escalated', label: 'Sent it to a manager' },
]

const outcomeChoice = ref('')
const outcomeReason = ref('')
const outcomeError = ref('')
const outcomeSaving = ref(false)
const outcomeRecorded = ref(null)

/* Escalating is declining to decide, not overruling anyone, so it never needs a reason.
   Mirrors _contradicts() on the server. */
const outcomeContradicts = computed(() =>
  (result.value?.verdict === 'FRAUD' && outcomeChoice.value === 'accepted') ||
  (result.value?.verdict === 'VALID' && outcomeChoice.value === 'rejected'),
)

const outcomeReasonMissing = computed(
  () => outcomeContradicts.value && !outcomeReason.value.trim(),
)

async function recordOutcome() {
  if (outcomeSaving.value || !outcomeChoice.value || outcomeReasonMissing.value) return
  outcomeSaving.value = true
  outcomeError.value = ''
  try {
    outcomeRecorded.value = await postJson(`/verifications/${result.value.request_id}/outcome`, {
      outcome: outcomeChoice.value,
      reason: outcomeReason.value.trim() || null,
    })
  } catch (err) {
    outcomeError.value = err.message || 'Could not record what you did.'
  } finally {
    outcomeSaving.value = false
  }
}

function clearOutcome() {
  outcomeChoice.value = ''
  outcomeReason.value = ''
  outcomeError.value = ''
  outcomeRecorded.value = null
}

async function reset() {
  clearFile()
  clearOutcome()
  errorNotice.value = null
  result.value = null
  await nextTick()
  chooseFileButton.value?.focus()
}
</script>

<template>
  <div>
    <!-- ------------------------------------------------------------- header -->
    <header class="flex flex-wrap items-start justify-between gap-x-6 gap-y-3 border-b border-border pb-4">
      <div>
        <h1 class="text-xl font-semibold text-navy">Verify a signature</h1>
        <p class="mt-0.5 max-w-prose text-sm text-ink-muted">
          Check a handwritten signature against the signatures held for a customer.
        </p>
      </div>
      <button
        v-if="result"
        type="button"
        class="min-h-11 rounded-md bg-navy px-4 text-sm font-semibold text-ink-inverse transition-colors hover:bg-navy-deep"
        @click="reset"
      >
        Check another signature
      </button>
    </header>

    <!-- ---------------------------------------------------------------- form -->
    <form
      v-if="!result"
      class="mt-6 space-y-6"
      @submit.prevent="handleSubmit"
    >
      <div
        v-if="errorNotice"
        :class="errorNotice.level === 'warning'
          ? 'border-warning-border bg-warning-surface'
          : 'border-danger-border bg-danger-surface'"
        class="ss-rise rounded-md border px-4 py-3"
      >
        <p
          :class="errorNotice.level === 'warning' ? 'text-warning' : 'text-danger'"
          class="text-sm font-semibold"
        >
          {{ errorNotice.title }}
        </p>
        <p class="mt-1 max-w-prose text-sm text-ink">{{ errorNotice.message }}</p>
      </div>

      <!-- Who and what, side by side: two short answers, not two stacked screens. -->
      <div class="grid gap-x-10 gap-y-6 xl:grid-cols-[minmax(0,20rem)_minmax(0,1fr)]">
        <div>
          <label for="national-id" class="block text-sm font-semibold text-ink">
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
            class="tabular mt-1.5 min-h-11 w-full rounded-md border border-border-strong bg-surface px-3 py-2 text-base text-ink placeholder:text-ink-subtle sm:text-sm"
            @blur="nationalIdTouched = true"
          />
          <p
            v-if="nationalIdTouched && !nationalIdValid"
            id="national-id-error"
            class="mt-1.5 text-xs text-danger"
          >
            The national ID must be exactly 9 digits.
          </p>
        </div>

        <div>
          <span class="block text-sm font-semibold text-ink">Signature image</span>
          <input ref="fileInput" type="file" accept="image/*" class="hidden" @change="handleFileChange" />
          <input
            ref="cameraInput"
            type="file"
            accept="image/*"
            capture="environment"
            class="hidden"
            @change="handleFileChange"
          />

          <div class="mt-1.5 flex flex-col gap-2 sm:flex-row">
            <button
              ref="chooseFileButton"
              type="button"
              class="min-h-11 flex-1 rounded-md border border-dashed border-border-strong px-4 py-3 text-sm font-medium text-ink-muted transition-colors hover:border-navy hover:text-navy"
              @click="openFilePicker"
            >
              Choose a file
            </button>
            <button
              type="button"
              class="min-h-11 flex-1 rounded-md border border-dashed border-border-strong px-4 py-3 text-sm font-medium text-ink-muted transition-colors hover:border-navy hover:text-navy"
              @click="openCamera"
            >
              Use the camera
            </button>
          </div>

          <details class="mt-2 rounded-md border border-border">
            <summary class="min-h-11 cursor-pointer px-3 py-3 text-sm font-medium text-ink marker:text-ink-subtle">
              How to photograph a signature
            </summary>
            <div class="border-t border-border p-3">
              <CaptureGuide />
            </div>
          </details>

          <!-- Advice about the picture, never a block on sending it. -->
          <div
            v-if="captureNotice"
            :class="captureTheme"
            class="mt-2 rounded-md border px-4 py-3"
          >
            <p class="text-sm font-semibold">
              {{ captureNotice.title }}
            </p>
            <p class="mt-1 max-w-prose text-sm text-ink">{{ captureNotice.message }}</p>
            <button
              type="button"
              class="mt-2 min-h-11 rounded-md border border-border-strong bg-surface px-3 text-sm font-medium text-navy transition-colors hover:bg-sunken"
              @click="openFilePicker"
            >
              Choose a different picture
            </button>
          </div>
        </div>
      </div>

      <p class="sr-only" role="status" aria-live="polite">{{ regionAnnouncement }}</p>

      <!-- ------------------------------------------- what is actually checked -->
      <section v-if="regionPending || previewUrl" class="border-t border-border pt-4">
        <h2 class="text-sm font-semibold text-ink">What will be checked</h2>

        <p v-if="regionPending" class="mt-1.5 text-sm text-ink-muted">
          Looking for the signature in this image…
        </p>

        <div v-if="previewUrl" class="mt-3 flex flex-wrap items-start gap-4">
          <figure class="w-full rounded-md border border-border sm:w-72">
            <figcaption class="border-b border-border bg-sunken px-3 py-2 text-2xs font-semibold uppercase tracking-wide text-ink-muted">
              Being checked
            </figcaption>
            <div class="p-3">
              <img
                :src="previewUrl"
                alt="The signature image that will be checked"
                class="mx-auto max-h-44 w-auto"
              />
              <p class="mt-2 text-xs text-ink-muted">{{ previewCaption }}</p>
              <!-- Framing changes the size of the writing inside the fixed square the model
                   reads, and the model is sensitive to size. A stroke running off the picture
                   is the single biggest reason two photographs of one signature disagree. -->
              <p v-if="activeRegion?.clipped" class="mt-2 text-xs text-warning">
                Part of the signature runs off the edge of the picture. Photograph it again
                with the whole signature inside the frame, including any trailing stroke.
              </p>
            </div>
          </figure>

          <!-- The whole picture is submitted as photographed, so the only way to see what
               is really being compared is to show it normalised, before it is sent. -->
          <figure
            v-if="chosenRegion === 'whole' && wholePreview"
            class="w-full rounded-md border border-border sm:w-72"
          >
            <figcaption class="border-b border-border bg-sunken px-3 py-2 text-2xs font-semibold uppercase tracking-wide text-ink-muted">
              As the model reads it
            </figcaption>
            <div class="p-3">
              <img
                :src="pngSrc(wholePreview)"
                alt="The whole image as the model will read it"
                class="mx-auto max-h-44 w-auto"
              />
              <p class="mt-2 text-xs text-ink-muted">
                Anything else on the page is compared along with the signature, which can
                make a genuine one look wrong.
              </p>
            </div>
          </figure>

          <!-- One region: used on its own, with a way back to the full picture. -->
          <div
            v-if="regions.length === 1"
            class="flex min-w-64 flex-1 flex-wrap items-center gap-x-4 gap-y-3 rounded-md border border-border p-3"
          >
            <img
              :src="pngSrc(regions[0].image)"
              alt="The signature as it was cut out of the picture"
              class="h-12 w-20 shrink-0 rounded-sm border border-border bg-surface object-contain"
            />
            <p class="min-w-40 flex-1 max-w-prose text-xs text-ink-muted">
              <template v-if="chosenRegion === 1">
                The signature was found in the picture and cut out. Only this part is checked.
              </template>
              <template v-else>
                The whole picture is being checked, including anything printed around the
                signature. That can make a genuine signature look wrong.
              </template>
            </p>
            <button
              v-if="chosenRegion === 1"
              type="button"
              class="min-h-11 rounded-md border border-border-strong bg-surface px-3 text-sm font-medium text-navy transition-colors hover:bg-sunken"
              @click="chooseWholeImage"
            >
              Use the whole image instead
            </button>
            <button
              v-else
              type="button"
              class="min-h-11 rounded-md border border-border-strong bg-surface px-3 text-sm font-medium text-navy transition-colors hover:bg-sunken"
              @click="chooseRegion(1)"
            >
              Use the cut out signature
            </button>
          </div>

          <!-- Several regions: only the clerk knows which mark is the signature. -->
          <div v-else-if="regions.length > 1" class="min-w-64 flex-1">
            <h3 class="text-sm font-semibold text-ink">
              More than one marking was found
            </h3>
            <p class="mt-1 max-w-prose text-xs text-ink-muted">
              Which one is the signature? Only the part you pick is checked. Checking the whole
              page as well can make a genuine signature look wrong.
            </p>

            <div class="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-3 xl:grid-cols-4">
              <button
                v-for="region in regions"
                :key="region.position"
                type="button"
                :aria-pressed="chosenRegion === region.position"
                class="relative flex min-h-11 flex-col items-center gap-1.5 rounded-md border p-2 text-left transition-colors"
                :class="chosenRegion === region.position
                  ? 'border-valid bg-valid-surface'
                  : 'border-border bg-surface hover:border-border-strong'"
                @click="chooseRegion(region.position)"
              >
                <span
                  class="absolute top-1.5 right-1.5 flex h-5 w-5 items-center justify-center rounded-full border"
                  :class="chosenRegion === region.position
                    ? 'border-valid bg-valid text-ink-inverse'
                    : 'border-border-strong bg-surface'"
                  aria-hidden="true"
                >
                  <svg
                    v-if="chosenRegion === region.position"
                    xmlns="http://www.w3.org/2000/svg"
                    class="h-3 w-3"
                    fill="none"
                    viewBox="0 0 24 24"
                    stroke="currentColor"
                    stroke-width="3"
                  >
                    <path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7" />
                  </svg>
                </span>
                <img
                  :src="pngSrc(region.image)"
                  :alt="`Marking ${region.position} found in the image`"
                  class="h-16 w-full bg-surface object-contain"
                />
                <span
                  class="tabular text-2xs font-semibold uppercase tracking-wide"
                  :class="chosenRegion === region.position ? 'text-valid' : 'text-ink-subtle'"
                >
                  {{ chosenRegion === region.position ? 'Chosen' : `Marking ${region.position}` }}
                </span>
              </button>
            </div>

            <button
              type="button"
              :aria-pressed="chosenRegion === 'whole'"
              class="mt-2 min-h-11 w-full rounded-md border px-4 text-sm font-medium transition-colors"
              :class="chosenRegion === 'whole'
                ? 'border-valid bg-valid-surface text-valid'
                : 'border-border-strong bg-surface text-navy hover:bg-sunken'"
              @click="chooseWholeImage"
            >
              {{ chosenRegion === 'whole' ? 'Using the whole image' : 'Use the whole image instead' }}
            </button>
          </div>
        </div>
      </section>

      <div class="flex flex-wrap items-center gap-4 border-t border-border pt-4">
        <button
          type="submit"
          :disabled="!canSubmit"
          class="min-h-11 w-full rounded-md bg-navy px-6 text-sm font-semibold text-ink-inverse transition-colors enabled:hover:bg-navy-deep disabled:cursor-not-allowed disabled:bg-sunken disabled:text-ink-subtle sm:w-auto"
        >
          {{ submitLabel }}
        </button>
      </div>
    </form>

    <!-- -------------------------------------------------------------- result -->
    <section v-else class="mt-6 space-y-6">
      <div
        :class="[verdictTheme.panel, verdictTheme.rule]"
        role="status"
        :aria-live="liveTone"
        class="ss-settle rounded-md border"
      >
        <div class="grid gap-6 p-4 xl:grid-cols-[minmax(0,22rem)_minmax(0,1fr)] xl:gap-10 xl:p-6">
          <div>
            <div class="flex items-center gap-3">
              <span
                :class="verdictTheme.badge"
                class="flex h-9 w-9 shrink-0 items-center justify-center rounded-full border text-base font-bold"
                aria-hidden="true"
              >
                {{ verdictTheme.glyph }}
              </span>
              <h2
                ref="verdictHeading"
                tabindex="-1"
                :class="verdictTheme.word"
                class="text-3xl font-bold tracking-tight"
              >
                {{ verdictWord }}
              </h2>
            </div>
            <p class="mt-3 max-w-prose text-sm text-ink">{{ verdictExplanation }}</p>
          </div>

          <!-- Where the score landed. Two named zones, the line between them labelled with
               its own number, and the score marked on it: the position is the reading, and
               a result that sits on the line looks like it sits on the line. -->
          <div>
            <div class="relative pt-6">
              <div
                class="absolute top-0 -translate-x-1/2 whitespace-nowrap"
                :style="{ left: labelPercent(result.distance) }"
              >
                <span
                  :class="verdictTheme.badge"
                  class="tabular flex items-center gap-1 rounded-sm border bg-surface px-1.5 py-px text-2xs font-semibold"
                >
                  <span aria-hidden="true">{{ verdictTheme.glyph }}</span>
                  {{ formatDistance(result.distance) }}
                </span>
              </div>

              <div class="relative h-9 overflow-hidden rounded-sm border border-border" aria-hidden="true">
                <div
                  class="absolute inset-y-0 left-0 bg-valid-surface"
                  :style="{ width: scalePercent(result.threshold) }"
                ></div>
                <div
                  class="absolute inset-y-0 right-0 bg-fraud-surface"
                  :style="{ left: scalePercent(result.threshold) }"
                ></div>
                <span class="absolute top-1/2 left-2 -translate-y-1/2 text-2xs font-semibold uppercase tracking-wide text-valid">
                  Match
                </span>
                <span class="absolute top-1/2 right-2 -translate-y-1/2 text-2xs font-semibold uppercase tracking-wide text-fraud">
                  No match
                </span>
                <div
                  v-if="uncertainSpan"
                  class="absolute inset-y-0 bg-borderline-surface"
                  :style="uncertainSpan"
                ></div>
                <div
                  class="absolute inset-y-0 w-px -translate-x-1/2 bg-ink-muted"
                  :style="{ left: scalePercent(result.threshold) }"
                ></div>
                <div
                  :class="verdictTheme.dot"
                  class="absolute inset-y-0 w-1 -translate-x-1/2"
                  :style="{ left: scalePercent(result.distance) }"
                ></div>
              </div>

              <div class="relative mt-1.5 h-7" aria-hidden="true">
                <span
                  class="absolute -translate-x-1/2 text-center text-2xs leading-tight text-ink-muted"
                  :style="{ left: scalePercent(result.threshold) }"
                >
                  <span class="block">Decision line</span>
                  <span class="tabular block">{{ formatDistance(result.threshold) }}</span>
                </span>
                <span class="tabular absolute left-0 text-2xs leading-tight text-ink-subtle">
                  <span class="block">Identical</span>
                  <span class="block">0.0000</span>
                </span>
                <span class="tabular absolute right-0 text-right text-2xs leading-tight text-ink-subtle">
                  <span class="block">Nothing alike</span>
                  <span class="block">1.0000</span>
                </span>
              </div>
            </div>

            <p class="tabular mt-2 max-w-prose text-sm text-ink">{{ scaleSummary }}</p>
          </div>
        </div>

        <dl :class="verdictTheme.rule" class="flex flex-wrap divide-x border-t px-4 xl:px-6">
          <div class="py-3 pr-5 first:pl-0">
            <dt class="text-2xs font-semibold uppercase tracking-wide text-ink-muted">Score</dt>
            <dd class="tabular mt-0.5 text-sm font-semibold text-ink">
              {{ formatDistance(result.distance) }}
            </dd>
          </div>
          <div class="px-5 py-3">
            <dt class="text-2xs font-semibold uppercase tracking-wide text-ink-muted">Decision line</dt>
            <dd class="tabular mt-0.5 text-sm font-semibold text-ink">
              {{ formatDistance(result.threshold) }}
            </dd>
          </div>
          <div class="px-5 py-3">
            <dt class="text-2xs font-semibold uppercase tracking-wide text-ink-muted">
              {{ onMatchSide ? 'Inside the line by' : 'Beyond the line by' }}
            </dt>
            <dd class="tabular mt-0.5 text-sm font-semibold text-ink">
              {{ formatDistance(gapFromLine) }}
            </dd>
          </div>
          <div class="px-5 py-3">
            <dt class="text-2xs font-semibold uppercase tracking-wide text-ink-muted">Confidence</dt>
            <dd class="tabular mt-0.5 text-sm font-semibold text-ink">
              {{ formatConfidence(result.confidence) }}
            </dd>
          </div>
        </dl>
      </div>

      <!-- evidence -->
      <section v-if="isClerk && rawReferences.length" class="border-t border-border pt-4">
        <div class="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1">
          <h2 class="text-sm font-semibold text-ink">Compare the signatures</h2>
          <p class="tabular text-sm text-ink-muted">
            <span class="font-semibold text-ink">{{ matchedCount }}</span>
            of {{ rawReferences.length }} reference signatures matched
          </p>
        </div>
        <p v-if="duplicateCount > 0" class="mt-1 max-w-prose text-xs text-ink-muted">
          <span class="tabular">{{ duplicateCount }}</span> of them are repeat copies of an image
          already shown, so they are grouped together rather than counted as separate evidence.
        </p>

        <div class="mt-3 grid gap-4 xl:grid-cols-[minmax(0,1fr)_22rem]">
          <!-- The comparison bench. Forensic practice is questioned beside known, cropped and
               at one scale; both panes are the same size and run through the same transform,
               so a difference on screen is a difference the model saw. -->
          <div class="overflow-hidden rounded-md border border-border">
            <div class="grid gap-px bg-border sm:grid-cols-2">
              <figure class="bg-surface">
                <figcaption class="flex items-baseline justify-between gap-2 border-b border-border bg-sunken px-3 py-2">
                  <span class="text-2xs font-semibold uppercase tracking-wide text-ink-muted">Questioned</span>
                  <span class="text-2xs text-ink-subtle">Submitted now</span>
                </figcaption>
                <img
                  :src="comparedImageUrl"
                  alt="The submitted signature after cleaning, which is the image the check ran on"
                  class="h-48 w-full bg-surface object-contain p-3 xl:h-64"
                />
              </figure>

              <figure class="bg-surface">
                <figcaption class="flex items-baseline justify-between gap-2 border-b border-border bg-sunken px-3 py-2">
                  <span class="text-2xs font-semibold uppercase tracking-wide text-ink-muted">Known</span>
                  <span class="tabular text-2xs text-ink-subtle">Reference {{ benchAnchor?.position }} on file</span>
                </figcaption>
                <img
                  v-if="benchAnchor"
                  :src="pngSrc(benchAnchor.image)"
                  :alt="anchorAlt(benchAnchor)"
                  class="h-48 w-full bg-surface object-contain p-3 xl:h-64"
                />
              </figure>
            </div>

            <dl
              v-if="benchAnchor"
              class="flex flex-wrap divide-x divide-border border-t border-border px-3"
            >
              <div class="py-2.5 pr-5 first:pl-0">
                <dt class="text-2xs font-semibold uppercase tracking-wide text-ink-muted">This pair</dt>
                <dd class="mt-0.5 flex items-center gap-1.5 text-sm font-semibold text-ink">
                  <span :class="anchorTheme(benchAnchor).dot" class="h-2 w-2 shrink-0 rounded-full"></span>
                  {{ anchorTheme(benchAnchor).label }}
                </dd>
              </div>
              <div class="px-5 py-2.5">
                <dt class="text-2xs font-semibold uppercase tracking-wide text-ink-muted">Distance</dt>
                <dd class="tabular mt-0.5 text-sm font-semibold text-ink">
                  {{ formatDistance(benchAnchor.distance) }}
                </dd>
              </div>
              <div class="px-5 py-2.5">
                <dt class="text-2xs font-semibold uppercase tracking-wide text-ink-muted">Confidence</dt>
                <dd class="tabular mt-0.5 text-sm font-semibold text-ink">
                  {{ formatConfidence(benchAnchor.confidence) }}
                </dd>
              </div>
              <div v-if="benchAnchor.count > 1" class="px-5 py-2.5">
                <dt class="text-2xs font-semibold uppercase tracking-wide text-ink-muted">Stored</dt>
                <dd class="tabular mt-0.5 text-sm font-semibold text-ink">
                  {{ benchAnchor.count }} times, as one signature
                </dd>
              </div>
            </dl>
          </div>

          <!-- Every reference, because the spread across them is what shows the writer's own
               range of variation. Picking one puts it on the bench. -->
          <div class="overflow-hidden rounded-md border border-border">
            <div class="flex items-baseline justify-between gap-2 border-b border-border bg-sunken px-3 py-2">
              <h3 class="text-2xs font-semibold uppercase tracking-wide text-ink-muted">
                References on file, closest first
              </h3>
              <span class="tabular text-2xs text-ink-subtle">{{ anchorsByCloseness.length }}</span>
            </div>
            <ul class="max-h-96 divide-y divide-border overflow-y-auto">
              <li v-for="anchor in anchorsByCloseness" :key="anchor.key">
                <button
                  type="button"
                  :aria-pressed="benchAnchor?.key === anchor.key"
                  class="flex min-h-11 w-full items-center gap-3 px-3 py-2 text-left transition-colors hover:bg-sunken"
                  :class="benchAnchor?.key === anchor.key ? 'bg-sunken' : 'bg-surface'"
                  @click="benchKey = anchor.key"
                >
                  <img
                    :src="pngSrc(anchor.image)"
                    :alt="anchorAlt(anchor)"
                    class="h-10 w-16 shrink-0 rounded-sm border border-border bg-surface object-contain"
                  />
                  <span class="min-w-0 flex-1">
                    <span class="flex items-center gap-1.5">
                      <span :class="anchorTheme(anchor).dot" class="h-2 w-2 shrink-0 rounded-full"></span>
                      <span class="text-xs font-semibold text-ink">{{ anchorTheme(anchor).label }}</span>
                    </span>
                    <span class="tabular mt-0.5 block truncate text-2xs text-ink-subtle">
                      Reference {{ anchor.position }}<template v-if="anchor.count > 1"> &middot; stored {{ anchor.count }} times</template><template v-if="benchAnchor?.key === anchor.key"> &middot; on the bench</template>
                    </span>
                  </span>
                  <span class="tabular shrink-0 text-sm font-semibold text-ink">
                    {{ formatDistance(anchor.distance) }}
                  </span>
                </button>
              </li>
            </ul>
          </div>
        </div>
      </section>

      <!-- What was done about it. Below the evidence, because the evidence is what the
           decision is made from, and inline rather than in a dialog. -->
      <section v-if="outcomeRecorded" class="border-t border-border pt-4">
        <h2 class="text-sm font-semibold text-ink">
          Recorded: {{ OUTCOMES.find((o) => o.value === outcomeRecorded.outcome)?.label }}
        </h2>
        <p v-if="outcomeRecorded.reason" class="mt-1 max-w-prose text-sm text-ink-muted">
          {{ outcomeRecorded.reason }}
        </p>
        <p class="mt-1 text-xs text-ink-subtle">
          This is kept alongside the result. It does not change the verdict.
        </p>
      </section>

      <section v-else class="border-t border-border pt-4">
        <div class="grid gap-x-10 gap-y-4 xl:grid-cols-[minmax(0,22rem)_minmax(0,1fr)]">
          <div>
            <h2 class="text-sm font-semibold text-ink">What did you do?</h2>
            <p class="mt-1 max-w-prose text-sm text-ink-muted">
              The verdict is a measurement. Recording what happened at the counter is how the
              system learns where it disagreed with the person who was there.
            </p>
          </div>

          <div class="space-y-3">
            <div class="flex flex-wrap gap-2">
              <label
                v-for="option in OUTCOMES"
                :key="option.value"
                class="flex min-h-11 cursor-pointer items-center gap-2 rounded-md border px-3 text-sm"
                :class="outcomeChoice === option.value
                  ? 'border-navy bg-surface font-medium text-navy'
                  : 'border-border-strong bg-surface text-ink'"
              >
                <input v-model="outcomeChoice" type="radio" :value="option.value" class="shrink-0" />
                {{ option.label }}
              </label>
            </div>

            <label v-if="outcomeChoice" class="block max-w-xl">
              <span class="mb-1 block text-sm font-medium text-ink">
                {{ outcomeContradicts ? 'Why (required)' : 'Notes (optional)' }}
              </span>
              <textarea
                v-model="outcomeReason"
                rows="2"
                maxlength="500"
                :placeholder="outcomeContradicts
                  ? 'What did you know that the system did not?'
                  : 'Anything worth recording'"
                class="w-full rounded-md border border-border-strong bg-surface px-3 py-2 text-sm text-ink"
              ></textarea>
              <span v-if="outcomeContradicts" class="mt-1 block text-xs text-ink-subtle">
                This disagrees with the verdict, so the reason is kept as part of the record.
              </span>
            </label>

            <p v-if="outcomeError" class="text-sm text-danger">{{ outcomeError }}</p>

            <button
              type="button"
              :disabled="!outcomeChoice || outcomeReasonMissing || outcomeSaving"
              class="min-h-11 rounded-md bg-navy px-5 text-sm font-semibold text-ink-inverse disabled:cursor-not-allowed disabled:bg-sunken disabled:text-ink-subtle"
              @click="recordOutcome"
            >
              {{ outcomeSaving ? 'Recording…' : 'Record' }}
            </button>
          </div>
        </div>
      </section>

      <!-- technical details, below the evidence -->
      <details class="border-t border-border">
        <summary class="min-h-11 cursor-pointer py-3 text-sm font-medium text-ink marker:text-ink-subtle">
          Technical details
        </summary>
        <dl class="grid gap-x-10 gap-y-3 pb-3 sm:grid-cols-2 xl:grid-cols-4">
          <div>
            <dt class="text-2xs font-semibold uppercase tracking-wide text-ink-muted">Model version</dt>
            <dd class="tabular mt-0.5 text-sm text-ink">{{ result.model_version }}</dd>
          </div>
          <div class="min-w-0">
            <dt class="text-2xs font-semibold uppercase tracking-wide text-ink-muted">Request reference</dt>
            <dd class="tabular mt-0.5 break-all text-sm text-ink">{{ result.request_id }}</dd>
          </div>
          <div>
            <dt class="text-2xs font-semibold uppercase tracking-wide text-ink-muted">Checked at</dt>
            <dd class="tabular mt-0.5 text-sm text-ink">{{ formatDateTime(result.verified_at) }}</dd>
          </div>
          <div>
            <dt class="text-2xs font-semibold uppercase tracking-wide text-ink-muted">Distance and threshold</dt>
            <dd class="tabular mt-0.5 text-sm text-ink">
              {{ formatDistance(result.distance) }} against {{ formatDistance(result.threshold) }}
            </dd>
          </div>
        </dl>
      </details>
    </section>
  </div>
</template>
