<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import { get, postJson, postForm, ApiError } from '../api.js'
import { assessCapture } from '../capture.js'
import { save as saveWizard, load as loadWizard, clear as clearWizard } from '../enrolStorage.js'
import { noticeClass, pngSrc } from '../format.js'
import CaptureGuide from '../components/CaptureGuide.vue'

/** Most references a customer may hold. */
const MAX_REFERENCES = 10

/** A brand new customer needs a full card. An append only needs one more signature. */
const MIN_REFERENCES_NEW = 8
const MIN_REFERENCES_APPEND = 1

const route = useRoute()

const STEPS = [
  { n: 1, label: 'Details' },
  { n: 2, label: 'Specimen card' },
  { n: 3, label: 'Approve' },
]

const step = ref(1) // 1 | 2 | 3 | 'success'
const showCancelConfirm = ref(false)

// --- Step 1: details ---
const nationalId = ref('')
const fullName = ref('')
const consentGranted = ref(false)
const consentMethod = ref('signed_form')
const step1Error = ref('')
const step1Submitting = ref(false)

const nationalIdValid = computed(() => /^\d{9}$/.test(nationalId.value))
const fullNameValid = computed(() => fullName.value.trim().length > 0)
const step1Valid = computed(() => nationalIdValid.value && fullNameValid.value && consentGranted.value)

const enrolmentId = ref(null)
const enrolMode = ref(null) // 'new' | 'append'

async function submitStep1() {
  if (!step1Valid.value || step1Submitting.value) return
  step1Error.value = ''
  step1Submitting.value = true
  try {
    const res = await postJson('/customers', {
      national_id: nationalId.value,
      full_name: fullName.value.trim(),
      consent: { granted: consentGranted.value, method: consentMethod.value },
    })
    enrolmentId.value = res.enrolment_id
    enrolMode.value = res.mode
    step.value = 2
  } catch (err) {
    step1Error.value = err.message || 'Failed to start enrolment.'
  } finally {
    step1Submitting.value = false
  }
}

// --- Step 2: specimen card upload ---
const cardFile = ref(null)
const cardPreviewUrl = ref('')
const step2Error = ref(null) // { level: 'warning' | 'error', message }
const step2Uploading = ref(false)
const cardFileInput = ref(null)
const cardCameraInput = ref(null)
const dragging = ref(false)

const captureNotice = ref(null) // { level: 'good' | 'warning' | 'error', title, message }

function onFileSelected(e) {
  const file = e.target.files && e.target.files[0]
  if (file) selectCard(file)
}

function selectCard(file) {
  if (cardPreviewUrl.value) URL.revokeObjectURL(cardPreviewUrl.value)
  cardFile.value = file
  cardPreviewUrl.value = URL.createObjectURL(file)
  step2Error.value = null
  assessFile(file)
}

/* A second pick while the first reading is still running wins. */
async function assessFile(file) {
  captureNotice.value = null
  const verdict = await assessCapture(file)
  if (cardFile.value !== file) return
  captureNotice.value = verdict
}

function onDrop(event) {
  dragging.value = false
  const file = event.dataTransfer?.files?.[0]
  if (file) selectCard(file)
}

function reopenFilePicker() {
  cardFileInput.value?.click()
}

const crops = ref([])
const extraFileInput = ref(null)
const addingPhoto = ref(false)

/* Photographs accumulate on the server, so a response always carries the whole set.
   Selection is preserved by crop_id: re-selecting everything after each photo would
   silently re-tick specimens the clerk had deliberately rejected. */
function absorbCrops(returned) {
  const previous = new Map(crops.value.map((c) => [c.crop_id, c.selected]))
  crops.value = returned.map((c, index) => ({
    ...c,
    position: index + 1,
    selected: previous.has(c.crop_id) ? previous.get(c.crop_id) : true,
  }))
}

function openExtraPhotoPicker() {
  extraFileInput.value?.click()
}

async function addAnotherPhoto(event) {
  const file = event.target.files?.[0]
  event.target.value = ''
  if (!file || addingPhoto.value) return
  addingPhoto.value = true
  step3Error.value = null
  try {
    const formData = new FormData()
    formData.append('file', file)
    const res = await postForm(`/customers/${enrolmentId.value}/card`, formData)
    absorbCrops(res.crops)
  } catch (err) {
    if (err instanceof ApiError && err.code === 'CUSTOMER_NOT_FOUND') {
      expireAndRestart()
    } else {
      step3Error.value = {
        level: 'warning',
        message: err.message || 'That photograph could not be read. The signatures already collected are kept.',
      }
    }
  } finally {
    addingPhoto.value = false
  }
}

async function uploadCard() {
  if (!cardFile.value || step2Uploading.value) return
  step2Error.value = null
  step2Uploading.value = true
  try {
    const formData = new FormData()
    formData.append('file', cardFile.value)
    const res = await postForm(`/customers/${enrolmentId.value}/card`, formData)
    absorbCrops(res.crops)
    step.value = 3
  } catch (err) {
    if (err instanceof ApiError && ['INSUFFICIENT_SIGNATURES', 'DUPLICATE_SIGNATURES'].includes(err.code)) {
      step2Error.value = { level: 'warning', message: err.message || 'No signature was detected. Please rephotograph the card.' }
    } else if (err instanceof ApiError && err.code === 'CUSTOMER_NOT_FOUND') {
      expireAndRestart()
    } else {
      step2Error.value = { level: 'error', message: err.message || 'Failed to upload specimen card.' }
    }
  } finally {
    step2Uploading.value = false
  }
}

// --- Step 3: approve crops ---
const step3Error = ref(null) // { level: 'warning' | 'error', message, note? }
const step3Submitting = ref(false)

const selectedCount = computed(() => crops.value.filter((c) => c.selected).length)

const minReferences = computed(() =>
  enrolMode.value === 'append' ? MIN_REFERENCES_APPEND : MIN_REFERENCES_NEW,
)

const canApprove = computed(
  () => selectedCount.value >= minReferences.value && selectedCount.value <= MAX_REFERENCES,
)

const requirementText = computed(() =>
  minReferences.value === 1
    ? 'At least 1 required'
    : `${minReferences.value} to ${MAX_REFERENCES} required`,
)

/* The way out of the loop the clerk used to be stuck in: short of the minimum is not a
   dead end that requires re-shooting the whole card, it is a prompt for another photo. */
const shortfall = computed(() => Math.max(0, minReferences.value - selectedCount.value))

/* The count is the screen's headline, so its state is spelled out in words as well as
   in the tint: a clerk glancing at it must not have to count backwards. */
const selectionStatus = computed(() => {
  if (shortfall.value > 0) {
    return {
      ok: false,
      text: `${shortfall.value} more ${shortfall.value === 1 ? 'signature' : 'signatures'} needed`,
    }
  }
  if (selectedCount.value > MAX_REFERENCES) {
    return { ok: false, text: `${selectedCount.value - MAX_REFERENCES} too many selected` }
  }
  return { ok: true, text: 'Ready to approve' }
})

const cardGuidance = computed(() =>
  minReferences.value === 1
    ? 'Photograph the signature on its own, filling the frame. One clear signature is enough for a customer already on file.'
    : `Card must contain ${minReferences.value} to ${MAX_REFERENCES} signatures, one below the other, with clear spacing.`,
)

function toggleCrop(crop) {
  crop.selected = !crop.selected
}

async function approveReferences() {
  if (!canApprove.value || step3Submitting.value) return
  step3Error.value = null
  step3Submitting.value = true
  try {
    const cropIds = crops.value.filter((c) => c.selected).map((c) => c.crop_id)
    const res = await postJson(`/customers/${enrolmentId.value}/references`, { crop_ids: cropIds })
    successCustomerId.value = res.customer_id
    successReferenceCount.value = res.reference_count
    successMode.value = enrolMode.value
    step.value = 'success'
    forget()
  } catch (err) {
    if (err instanceof ApiError && err.code === 'CUSTOMER_NOT_FOUND') {
      expireAndRestart()
    } else if (err instanceof ApiError && err.code === 'SIGNATURE_MISMATCH') {
      step3Error.value = {
        level: 'error',
        message: err.message || 'Submitted signatures do not match the registered customer.',
        note: 'This protects the registry against impersonation.',
      }
    } else if (err instanceof ApiError && err.code === 'TOO_MANY_SIGNATURES') {
      step3Error.value = { level: 'warning', message: err.message || 'Too many signatures selected.' }
    } else {
      step3Error.value = { level: 'error', message: err.message || 'Failed to approve references.' }
    }
  } finally {
    step3Submitting.value = false
  }
}

// --- Success ---
const successCustomerId = ref('')
const successReferenceCount = ref(0)
const successMode = ref(null) // 'new' | 'append'
const copied = ref(false)

async function copyCustomerId() {
  try {
    await navigator.clipboard.writeText(successCustomerId.value)
    copied.value = true
    setTimeout(() => { copied.value = false }, 1500)
  } catch {
    copied.value = false
  }
}

// --- Surviving a refresh ---

/* Only the identifiers and what the clerk typed. The candidate images are re-fetched
   from the staged enrolment, which the server keeps for fifteen minutes. */
function persist() {
  if (step.value === 'success') return
  saveWizard(sessionStorage, {
    step: step.value,
    nationalId: nationalId.value,
    fullName: fullName.value,
    consentGranted: consentGranted.value,
    consentMethod: consentMethod.value,
    enrolmentId: enrolmentId.value,
    enrolMode: enrolMode.value,
    /* Which specimens were ticked, by id. Restoring without this would silently re-tick
       specimens the clerk had deliberately rejected. */
    deselected: crops.value.filter((c) => !c.selected).map((c) => c.crop_id),
  })
}

function forget() {
  clearWizard(sessionStorage)
}

async function restore() {
  const saved = loadWizard(sessionStorage)
  if (!saved) return false

  nationalId.value = saved.nationalId
  fullName.value = saved.fullName
  consentGranted.value = saved.consentGranted
  consentMethod.value = saved.consentMethod

  if (!saved.enrolmentId) return true

  enrolmentId.value = saved.enrolmentId
  enrolMode.value = saved.enrolMode
  try {
    const { crops: staged } = await get(`/customers/${saved.enrolmentId}/card`)
    absorbCrops(staged)
    const rejected = new Set(saved.deselected)
    crops.value.forEach((crop) => { crop.selected = !rejected.has(crop.crop_id) })
    /* Back to step 3 only if there is something there to approve. The card upload is
       the one thing that cannot be restored - the file itself never left the browser. */
    step.value = staged.length ? saved.step : 2
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) {
      expireAndRestart()
    } else {
      enrolmentId.value = null
      enrolMode.value = null
      step.value = 1
    }
  }
  return true
}

watch([step, nationalId, fullName, consentGranted, consentMethod, enrolmentId, enrolMode, crops],
      persist, { deep: true })

/* Arriving from a customer's page: the identity is already known, so skip retyping it. */
onMounted(async () => {
  if (await restore()) return
  const prefillId = String(route.query.national_id ?? '')
  if (/^\d{9}$/.test(prefillId)) {
    nationalId.value = prefillId
    fullName.value = String(route.query.full_name ?? '')
  }
})

// --- Navigation: back, cancel, expiry ---
const expiredMessage = ref('')

function goBack() {
  if (typeof step.value === 'number' && step.value > 1) {
    step.value -= 1
  }
}

function requestCancel() {
  showCancelConfirm.value = true
}

function dismissCancel() {
  showCancelConfirm.value = false
}

function confirmCancel() {
  showCancelConfirm.value = false
  resetWizard()
}

/**
 * The staging record behind enrolmentId has expired server-side. Show the
 * notice before clearing anything, and keep what the clerk already typed
 * (national ID, name, consent) so they are not forced to retype it.
 */
function expireAndRestart() {
  expiredMessage.value = 'This enrolment session expired before it finished. Your national ID, name and consent are still filled in below, so you can continue.'
  showCancelConfirm.value = false
  step.value = 1
  enrolmentId.value = null
  enrolMode.value = null
  if (cardPreviewUrl.value) URL.revokeObjectURL(cardPreviewUrl.value)
  cardFile.value = null
  cardPreviewUrl.value = ''
  step2Error.value = null
  captureNotice.value = null
  crops.value = []
  step3Error.value = null
}

function resetWizard() {
  forget()
  expiredMessage.value = ''
  step.value = 1
  nationalId.value = ''
  fullName.value = ''
  consentGranted.value = false
  consentMethod.value = 'signed_form'
  step1Error.value = ''
  enrolmentId.value = null
  enrolMode.value = null
  if (cardPreviewUrl.value) URL.revokeObjectURL(cardPreviewUrl.value)
  cardFile.value = null
  cardPreviewUrl.value = ''
  step2Error.value = null
  captureNotice.value = null
  crops.value = []
  step3Error.value = null
  successCustomerId.value = ''
  successReferenceCount.value = 0
  successMode.value = null
  showCancelConfirm.value = false
}

function enrolAnother() {
  resetWizard()
}

// --- Stepper ---
function stepStatus(n) {
  if (step.value === n) return 'current'
  if (typeof step.value === 'number' && step.value > n) return 'complete'
  return 'upcoming'
}

/* The step reads as a tab on the rule under the page title, not as a bubble on a wire. */
function stepClass(n) {
  const status = stepStatus(n)
  if (status === 'current') return 'border-navy text-navy font-semibold'
  if (status === 'complete') return 'border-brand-green text-ink'
  return 'border-transparent text-ink-subtle'
}

function ordinalClass(n) {
  const status = stepStatus(n)
  if (status === 'current') return 'border-navy bg-navy text-ink-inverse'
  if (status === 'complete') return 'border-brand-green bg-brand-green text-navy'
  return 'border-border-strong bg-surface text-ink-muted'
}
</script>

<template>
  <div class="space-y-5 lg:mx-auto lg:max-w-[56rem]">
    <h1 class="text-xl font-semibold text-navy">Enrol customer</h1>

    <!-- Progress and the record it belongs to on one rule: the clerk always knows which
         customer is on screen, not merely which step. -->
    <div v-if="step !== 'success'" class="flex flex-wrap items-end justify-between gap-x-8 gap-y-1 border-b border-border">
      <nav aria-label="Enrolment progress">
        <ol class="flex items-center gap-x-6 sm:gap-x-8">
          <li v-for="s in STEPS" :key="s.n">
            <span
              class="-mb-px flex items-center gap-2 border-b-2 pb-2.5 text-sm"
              :class="stepClass(s.n)"
              :aria-current="stepStatus(s.n) === 'current' ? 'step' : undefined"
            >
              <span
                class="tabular flex h-5 w-5 shrink-0 items-center justify-center rounded-sm border text-2xs font-semibold"
                :class="ordinalClass(s.n)"
              >
                <svg v-if="stepStatus(s.n) === 'complete'" xmlns="http://www.w3.org/2000/svg" class="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="3">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7" />
                </svg>
                <span v-else>{{ s.n }}</span>
              </span>
              <span>{{ s.label }}</span>
            </span>
          </li>
        </ol>
      </nav>

      <p v-if="enrolmentId" class="pb-2.5 text-xs text-ink-muted">
        <span class="font-medium text-ink">{{ fullName.trim() }}</span>
        <span class="tabular"> · {{ nationalId }}</span>
        <span> · {{ enrolMode === 'append' ? 'Appending to a registered customer' : 'New record' }}</span>
      </p>
    </div>

    <div v-if="expiredMessage" class="max-w-prose rounded-md border px-4 py-3 text-sm" :class="noticeClass('warning')">
      {{ expiredMessage }}
    </div>

    <p v-if="enrolMode === 'append' && (step === 2 || step === 3)" class="max-w-prose text-xs text-ink-muted">
      New signatures are verified against the registered references before acceptance.
    </p>

    <!-- Step 1: Details -->
    <!-- The step caps as one column so the rule above Continue stops where the fields
         stop; a hairline running the full width is what strands the button. -->
    <section v-if="step === 1" class="space-y-5">
      <!-- Each field gets the width its content needs, not a third of the viewport: a
           9-digit id in a 500px box reads as a field the clerk has filled in wrongly. -->
      <div class="grid gap-x-6 gap-y-4 sm:grid-cols-2 lg:grid-cols-[11rem_minmax(0,1fr)_13rem]">
        <div>
          <label for="enrol-national-id" class="mb-1 block text-2xs font-semibold uppercase tracking-wide text-ink-muted">National ID</label>
          <input
            id="enrol-national-id"
            v-model="nationalId"
            type="text"
            inputmode="numeric"
            maxlength="9"
            class="tabular min-h-11 w-full rounded-md border border-border bg-surface px-3 py-2 text-sm text-ink"
            placeholder="9-digit national ID"
          />
          <p v-if="nationalId.length > 0 && !nationalIdValid" class="mt-1 text-xs text-danger">
            National ID must be exactly <span class="tabular">9</span> digits.
          </p>
        </div>

        <div>
          <label for="enrol-full-name" class="mb-1 block text-2xs font-semibold uppercase tracking-wide text-ink-muted">Full name</label>
          <input
            id="enrol-full-name"
            v-model="fullName"
            type="text"
            class="min-h-11 w-full rounded-md border border-border bg-surface px-3 py-2 text-sm text-ink"
            placeholder="Customer full name"
          />
        </div>

        <div>
          <label for="enrol-consent-method" class="mb-1 block text-2xs font-semibold uppercase tracking-wide text-ink-muted">Consent method</label>
          <select
            id="enrol-consent-method"
            v-model="consentMethod"
            class="min-h-11 w-full rounded-md border border-border bg-surface px-3 py-2 text-sm text-ink"
          >
            <option value="signed_form">Signed form</option>
            <option value="in_person">In person</option>
          </select>
        </div>
      </div>

      <label class="flex min-h-11 max-w-prose items-center gap-2 text-sm text-ink">
        <input v-model="consentGranted" type="checkbox" class="shrink-0" />
        <span>Customer consents to shared verification by subscribing organisations</span>
      </label>

      <div v-if="step1Error" class="max-w-prose rounded-md border px-4 py-3 text-sm" :class="noticeClass('error')">
        {{ step1Error }}
      </div>

      <div class="flex flex-wrap items-center gap-3 border-t border-border pt-4">
        <button
          type="button"
          :disabled="!step1Valid || step1Submitting"
          class="min-h-11 rounded-md bg-navy px-5 font-semibold text-ink-inverse disabled:bg-sunken disabled:text-ink-subtle disabled:cursor-not-allowed"
          @click="submitStep1"
        >
          {{ step1Submitting ? 'Submitting…' : 'Continue' }}
        </button>
      </div>
    </section>

    <!-- Step 2: Specimen card -->
    <section v-else-if="step === 2" class="space-y-4">
      <!-- Once there is a photograph the width goes to it: judging the picture is the
           whole task of this step, and a thumbnail cannot be judged. -->
      <div class="grid gap-6" :class="cardPreviewUrl ? 'lg:grid-cols-[minmax(0,24rem)_minmax(0,1fr)]' : ''">
        <div class="space-y-4">
          <p class="max-w-prose text-sm text-ink-muted">{{ cardGuidance }}</p>

          <!-- The default file control is the widget chrome this product replaced; the same
               two targets Verify offers, so the two upload surfaces behave alike. -->
          <input
            ref="cardFileInput"
            type="file"
            accept="image/*"
            class="sr-only"
            @change="onFileSelected"
          />
          <input
            ref="cardCameraInput"
            type="file"
            accept="image/*"
            capture="environment"
            class="sr-only"
            @change="onFileSelected"
          />
          <div
            class="grid max-w-xl grid-cols-1 gap-3 sm:grid-cols-2"
            @dragover.prevent="dragging = true"
            @dragleave.prevent="dragging = false"
            @drop.prevent="onDrop"
          >
            <button
              type="button"
              class="min-h-11 rounded-md border border-dashed px-4 py-4 text-sm font-medium transition-colors"
              :class="dragging
                ? 'border-navy bg-sunken text-navy'
                : 'border-border-strong text-ink-muted hover:border-navy hover:text-navy'"
              @click="cardFileInput?.click()"
            >
              {{ dragging ? 'Drop the photograph' : 'Choose a file' }}
            </button>
            <button
              type="button"
              class="min-h-11 rounded-md border border-dashed border-border-strong px-4 py-4 text-sm font-medium text-ink-muted transition-colors hover:border-navy hover:text-navy"
              @click="cardCameraInput?.click()"
            >
              Use the camera
            </button>
          </div>

          <details class="max-w-xl border-t border-border">
            <summary class="min-h-11 cursor-pointer py-3 text-sm font-medium text-ink marker:text-ink-subtle">
              How to photograph a signature
            </summary>
            <div class="pb-3">
              <CaptureGuide />
            </div>
          </details>
        </div>

        <div v-if="cardPreviewUrl" class="space-y-3">
          <div class="rounded-md border border-border bg-surface p-2">
            <img :src="cardPreviewUrl" alt="Specimen card preview" class="mx-auto max-h-96 rounded-sm" />
          </div>

          <!-- Advice about the picture, never a block on uploading it. -->
          <div
            v-if="captureNotice"
            class="space-y-1 rounded-md border px-4 py-3 text-sm"
            :class="noticeClass(captureNotice.level)"
          >
            <p class="font-semibold">{{ captureNotice.title }}</p>
            <p class="text-ink">{{ captureNotice.message }}</p>
            <button
              type="button"
              class="mt-1 min-h-11 rounded-md border border-border-strong bg-surface px-3 font-medium text-ink"
              @click="reopenFilePicker"
            >
              Choose a different picture
            </button>
          </div>
        </div>
      </div>

      <div v-if="step2Error" class="max-w-prose rounded-md border px-4 py-3 text-sm" :class="noticeClass(step2Error.level)">
        {{ step2Error.message }}
      </div>

      <div class="flex flex-wrap items-center gap-3 border-t border-border pt-4">
        <button
          type="button"
          class="min-h-11 rounded-md border border-border-strong bg-surface px-4 text-sm font-medium text-ink"
          @click="goBack"
        >
          Back
        </button>
        <button
          type="button"
          :disabled="!cardFile || step2Uploading"
          class="min-h-11 rounded-md bg-navy px-5 font-semibold text-ink-inverse disabled:bg-sunken disabled:text-ink-subtle disabled:cursor-not-allowed"
          @click="uploadCard"
        >
          {{ step2Uploading ? 'Uploading…' : 'Upload' }}
        </button>
        <button
          type="button"
          class="ml-auto min-h-11 px-2 text-sm font-medium text-ink-muted underline underline-offset-2 lg:ml-12"
          @click="requestCancel"
        >
          Cancel enrolment
        </button>
      </div>

      <div v-if="showCancelConfirm" class="max-w-prose space-y-2 rounded-md border px-4 py-3 text-sm" :class="noticeClass('warning')">
        <p>Cancel this enrolment. The entered details and uploaded specimen will be discarded.</p>
        <div class="flex flex-wrap gap-2">
          <button type="button" class="min-h-11 rounded-md border border-border-strong bg-surface px-3 font-medium text-ink" @click="dismissCancel">
            Keep editing
          </button>
          <button type="button" class="min-h-11 rounded-md bg-danger px-3 font-medium text-ink-inverse" @click="confirmCancel">
            Discard and cancel
          </button>
        </div>
      </div>
    </section>

    <!-- Step 3: Approve crops -->
    <section v-else-if="step === 3" class="space-y-4">
      <!-- The count is what the clerk is actually doing here, so it rides along the top of
           the viewport while they work down the list, and carries the approval with it. -->
      <div class="sticky top-0 z-10 -mx-4 border-b border-border bg-canvas px-4 py-3 sm:-mx-6 sm:px-6 lg:-mx-8 lg:px-8">
        <div class="flex flex-wrap items-center gap-x-6 gap-y-3">
          <p class="flex items-baseline gap-2">
            <span class="tabular text-2xl font-semibold leading-none" :class="selectionStatus.ok ? 'text-navy' : 'text-warning'">
              {{ selectedCount }}
            </span>
            <span class="text-sm text-ink-muted">
              of <span class="tabular">{{ crops.length }}</span> selected
            </span>
          </p>
          <p class="flex items-center gap-2 text-sm">
            <span
              class="h-1.5 w-1.5 shrink-0 rounded-full"
              :class="selectionStatus.ok ? 'bg-brand-green' : 'bg-warning'"
              aria-hidden="true"
            ></span>
            <span class="font-medium" :class="selectionStatus.ok ? 'text-ink' : 'text-warning'">{{ selectionStatus.text }}</span>
            <span class="text-ink-subtle">·</span>
            <span class="tabular text-xs text-ink-muted">{{ requirementText }}</span>
          </p>
          <button
            type="button"
            :disabled="!canApprove || step3Submitting"
            class="ml-auto min-h-11 rounded-md bg-navy px-5 font-semibold text-ink-inverse disabled:bg-sunken disabled:text-ink-subtle disabled:cursor-not-allowed"
            @click="approveReferences"
          >
            {{ step3Submitting ? 'Approving…' : 'Approve' }}
          </button>
        </div>
      </div>

      <!-- A card photographed at an angle groups two signatures into one region or drops
           one at the edge. Re-shooting the whole card to fix a single specimen is a loop
           with no exit; another photograph adds to what is already here. -->
      <div
        class="flex flex-wrap items-center gap-x-4 gap-y-2 text-sm"
        :class="shortfall > 0 ? 'max-w-prose rounded-md border px-4 py-3 ' + noticeClass('warning') : ''"
      >
        <p v-if="shortfall > 0" class="text-ink">
          Photograph the missing {{ shortfall === 1 ? 'one' : 'ones' }} - on the card or on
          their own - and they will be added to these.
        </p>
        <p v-else class="text-ink-muted">
          Missing or badly cut signatures? Add another photograph instead of starting over.
        </p>
        <input
          ref="extraFileInput"
          type="file"
          accept="image/*"
          capture="environment"
          class="sr-only"
          @change="addAnotherPhoto"
        />
        <button
          type="button"
          :disabled="addingPhoto"
          class="min-h-11 rounded-md border border-border-strong bg-surface px-3 text-sm font-medium text-navy disabled:text-ink-subtle"
          @click="openExtraPhotoPicker"
        >
          {{ addingPhoto ? 'Reading photograph…' : 'Add another photo' }}
        </button>
      </div>

      <!-- Tiles stay in the 220-280px band whatever the viewport: below that a signature
           cannot be judged, above it the clerk scrolls to see a set of ten. -->
      <div class="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-[repeat(auto-fill,minmax(14rem,1fr))]">
        <button
          v-for="crop in crops"
          :key="crop.crop_id"
          :data-position="crop.position"
          type="button"
          :aria-pressed="crop.selected"
          class="flex flex-col gap-1.5 rounded-md border p-2 text-left transition-colors"
          :class="crop.selected
            ? 'border-valid-border bg-valid-surface'
            : 'border-border bg-surface hover:border-border-strong'"
          @click="toggleCrop(crop)"
        >
          <span class="flex items-center justify-between gap-2 text-2xs">
            <span class="tabular font-semibold text-ink-muted">{{ crop.position }}</span>
            <span class="flex items-center gap-1 font-medium" :class="crop.selected ? 'text-valid' : 'text-ink-subtle'">
              <svg v-if="crop.selected" xmlns="http://www.w3.org/2000/svg" class="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="3">
                <path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7" />
              </svg>
              {{ crop.selected ? 'Selected' : 'Not selected' }}
            </span>
          </span>
          <img
            :src="pngSrc(crop.preview_png_base64)"
            :alt="`Signature ${crop.position} found on the card`"
            class="h-28 w-full rounded-sm bg-surface object-contain"
            :class="crop.selected ? '' : 'opacity-50'"
          />
        </button>
      </div>

      <div v-if="step3Error" class="max-w-prose space-y-1 rounded-md border px-4 py-3 text-sm" :class="noticeClass(step3Error.level)">
        <p>{{ step3Error.message }}</p>
        <p v-if="step3Error.note" class="font-medium">{{ step3Error.note }}</p>
      </div>

      <div class="flex flex-wrap items-center gap-3 border-t border-border pt-4">
        <button
          type="button"
          class="min-h-11 rounded-md border border-border-strong bg-surface px-4 text-sm font-medium text-ink"
          @click="goBack"
        >
          Back
        </button>
        <button
          type="button"
          class="ml-auto min-h-11 px-2 text-sm font-medium text-ink-muted underline underline-offset-2 lg:ml-12"
          @click="requestCancel"
        >
          Cancel enrolment
        </button>
      </div>

      <div v-if="showCancelConfirm" class="max-w-prose space-y-2 rounded-md border px-4 py-3 text-sm" :class="noticeClass('warning')">
        <p>Cancel this enrolment. The entered details and uploaded specimen will be discarded.</p>
        <div class="flex flex-wrap gap-2">
          <button type="button" class="min-h-11 rounded-md border border-border-strong bg-surface px-3 font-medium text-ink" @click="dismissCancel">
            Keep editing
          </button>
          <button type="button" class="min-h-11 rounded-md bg-danger px-3 font-medium text-ink-inverse" @click="confirmCancel">
            Discard and cancel
          </button>
        </div>
      </div>
    </section>

    <!-- Success -->
    <section v-else class="max-w-2xl space-y-4">
      <h2 class="flex items-center gap-2 text-lg font-semibold text-navy">
        <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5 shrink-0 text-valid" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5">
          <path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7" />
        </svg>
        {{ successMode === 'append' ? 'Signatures appended to existing customer' : 'New customer enrolled' }}
      </h2>

      <dl class="divide-y divide-border border-y border-border text-sm">
        <div class="flex flex-wrap items-center justify-between gap-x-4 py-2">
          <dt class="text-2xs font-semibold uppercase tracking-wide text-ink-muted">Customer ID</dt>
          <dd class="flex items-center gap-2">
            <code class="tabular rounded-sm bg-sunken px-2 py-0.5 text-sm text-ink">{{ successCustomerId }}</code>
            <button
              type="button"
              class="min-h-11 px-2 text-sm font-medium text-navy underline underline-offset-2"
              @click="copyCustomerId"
            >
              {{ copied ? 'Copied' : 'Copy' }}
            </button>
          </dd>
        </div>
        <div class="flex flex-wrap items-center justify-between gap-x-4 py-2.5">
          <dt class="text-2xs font-semibold uppercase tracking-wide text-ink-muted">Reference signatures stored</dt>
          <dd class="tabular font-medium text-ink">{{ successReferenceCount }}</dd>
        </div>
      </dl>

      <div class="flex flex-wrap items-center gap-3 pt-1">
        <button
          type="button"
          class="min-h-11 rounded-md bg-navy px-5 font-semibold text-ink-inverse"
          @click="enrolAnother"
        >
          Enrol another customer
        </button>
      </div>
    </section>
  </div>
</template>
