<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import { get, postJson, postForm, ApiError } from '../api.js'
import { assessCapture } from '../capture.js'
import { save as saveWizard, load as loadWizard, clear as clearWizard } from '../enrolStorage.js'
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

const captureNotice = ref(null) // { level: 'good' | 'warning' | 'error', title, message }

function onFileSelected(e) {
  const file = e.target.files && e.target.files[0]
  if (!file) return
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

const selectionRule = computed(() =>
  minReferences.value === 1
    ? 'need at least 1'
    : `need ${minReferences.value} to ${MAX_REFERENCES}`,
)

/* The way out of the loop the clerk used to be stuck in: short of the minimum is not a
   dead end that requires re-shooting the whole card, it is a prompt for another photo. */
const shortfall = computed(() => Math.max(0, minReferences.value - selectedCount.value))

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
       the one thing that cannot be restored — the file itself never left the browser. */
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

function circleClass(n) {
  const status = stepStatus(n)
  if (status === 'current') return 'bg-navy border-navy text-ink-inverse'
  if (status === 'complete') return 'bg-brand-green border-brand-green text-navy'
  return 'bg-surface border-border-strong text-ink-muted'
}

function labelClass(n) {
  const status = stepStatus(n)
  if (status === 'current') return 'text-navy font-semibold'
  if (status === 'complete') return 'text-ink font-medium'
  return 'text-ink-subtle font-medium'
}

function connectorClass(n) {
  // Connector before step n is "filled" once step n has been reached.
  return typeof step.value === 'number' && step.value >= n ? 'bg-brand-green' : 'bg-border-strong'
}

function bannerClass(level) {
  if (level === 'good') return 'border-valid-border bg-valid-surface text-valid'
  if (level === 'warning') return 'border-warning-border bg-warning-surface text-warning'
  return 'border-danger-border bg-danger-surface text-danger'
}
</script>

<template>
  <div class="max-w-2xl mx-auto">
    <h1 class="text-2xl font-bold text-navy mb-6">Enrol customer</h1>

    <div v-if="expiredMessage" class="mb-6 rounded-lg border px-4 py-3 text-sm" :class="bannerClass('warning')">
      {{ expiredMessage }}
    </div>

    <div
      v-if="enrolMode === 'append' && (step === 2 || step === 3)"
      class="mb-6 rounded-lg border border-navy/30 bg-navy/5 text-navy px-4 py-3 text-sm"
    >
      Customer already registered. New signatures will be verified against the registered references before acceptance.
    </div>

    <nav v-if="step !== 'success'" aria-label="Enrolment progress" class="mb-8">
      <ol class="flex items-start">
        <li v-for="(s, i) in STEPS" :key="s.n" class="flex items-start" :class="i < STEPS.length - 1 ? 'flex-1' : ''">
          <div class="flex flex-col items-center gap-1.5 shrink-0">
            <div
              class="w-8 h-8 rounded-full border-2 flex items-center justify-center font-semibold text-sm"
              :class="circleClass(s.n)"
              :aria-current="stepStatus(s.n) === 'current' ? 'step' : undefined"
            >
              <svg v-if="stepStatus(s.n) === 'complete'" xmlns="http://www.w3.org/2000/svg" class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="3">
                <path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7" />
              </svg>
              <span v-else>{{ s.n }}</span>
            </div>
            <span class="text-2xs sm:text-xs text-center leading-tight max-w-[5rem]" :class="labelClass(s.n)">{{ s.label }}</span>
          </div>
          <div v-if="i < STEPS.length - 1" class="flex-1 h-0.5 mx-1.5 sm:mx-2 mt-4 rounded" :class="connectorClass(s.n + 1)"></div>
        </li>
      </ol>
    </nav>

    <!-- Step 1: Details -->
    <div v-if="step === 1" class="bg-surface border border-border rounded-lg shadow-sm p-6 space-y-4">
      <div>
        <label class="block text-sm font-medium text-ink-muted mb-1">National ID</label>
        <input
          v-model="nationalId"
          type="text"
          inputmode="numeric"
          maxlength="9"
          class="w-full min-h-11 rounded-lg border border-border bg-surface text-ink px-3 py-2"
          placeholder="9-digit national ID"
        />
        <p v-if="nationalId.length > 0 && !nationalIdValid" class="text-sm text-danger mt-1">
          National ID must be exactly 9 digits.
        </p>
      </div>

      <div>
        <label class="block text-sm font-medium text-ink-muted mb-1">Full name</label>
        <input
          v-model="fullName"
          type="text"
          class="w-full min-h-11 rounded-lg border border-border bg-surface text-ink px-3 py-2"
          placeholder="Customer full name"
        />
      </div>

      <div>
        <label class="block text-sm font-medium text-ink-muted mb-1">Consent method</label>
        <select
          v-model="consentMethod"
          class="w-full min-h-11 rounded-lg border border-border bg-surface text-ink px-3 py-2"
        >
          <option value="signed_form">Signed form</option>
          <option value="in_person">In person</option>
        </select>
      </div>

      <label class="flex items-center gap-2 text-sm text-ink min-h-11">
        <input v-model="consentGranted" type="checkbox" class="shrink-0" />
        <span>Customer consents to shared verification by subscribing organisations</span>
      </label>

      <div v-if="step1Error" class="rounded-lg border px-4 py-3 text-sm" :class="bannerClass('error')">
        {{ step1Error }}
      </div>

      <button
        type="button"
        :disabled="!step1Valid || step1Submitting"
        class="w-full min-h-11 bg-brand-green text-navy font-semibold rounded-lg py-2 disabled:bg-sunken disabled:text-ink-subtle disabled:cursor-not-allowed"
        @click="submitStep1"
      >
        {{ step1Submitting ? 'Submitting…' : 'Continue' }}
      </button>
    </div>

    <!-- Step 2: Specimen card -->
    <div v-else-if="step === 2" class="bg-surface border border-border rounded-lg shadow-sm p-6 space-y-4">
      <p class="text-sm text-ink-muted">
        {{ cardGuidance }}
      </p>

      <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <label class="flex flex-col min-h-11 justify-center">
          <span class="block text-sm font-medium text-ink-muted mb-1">Upload file</span>
          <input
            ref="cardFileInput"
            type="file"
            accept="image/*"
            class="w-full text-sm"
            @change="onFileSelected"
          />
        </label>
        <label class="flex flex-col min-h-11 justify-center">
          <span class="block text-sm font-medium text-ink-muted mb-1">Use camera</span>
          <input
            type="file"
            accept="image/*"
            capture="environment"
            class="w-full text-sm"
            @change="onFileSelected"
          />
        </label>
      </div>

      <details class="rounded-lg border border-border bg-surface">
        <summary class="min-h-11 cursor-pointer px-4 py-3 text-sm font-medium text-ink marker:text-ink-subtle">
          How to photograph a signature
        </summary>
        <div class="border-t border-border px-4 py-3">
          <CaptureGuide />
        </div>
      </details>

      <div v-if="cardPreviewUrl" class="rounded-lg border border-border p-2">
        <img :src="cardPreviewUrl" alt="Specimen card preview" class="max-h-80 mx-auto rounded" />
      </div>

      <!-- Advice about the picture, never a block on uploading it. -->
      <div
        v-if="captureNotice"
        class="rounded-lg border px-4 py-3 text-sm space-y-1"
        :class="bannerClass(captureNotice.level)"
      >
        <p class="font-semibold">{{ captureNotice.title }}</p>
        <p class="text-ink">{{ captureNotice.message }}</p>
        <button
          type="button"
          class="mt-1 min-h-11 px-3 rounded-lg border border-border-strong bg-surface text-ink font-medium"
          @click="reopenFilePicker"
        >
          Choose a different picture
        </button>
      </div>

      <div v-if="step2Error" class="rounded-lg border px-4 py-3 text-sm" :class="bannerClass(step2Error.level)">
        {{ step2Error.message }}
      </div>

      <div class="flex flex-wrap gap-3">
        <button
          type="button"
          class="min-h-11 px-4 rounded-lg border border-border-strong bg-surface text-ink font-medium"
          @click="goBack"
        >
          Back
        </button>
        <button
          type="button"
          class="min-h-11 px-4 rounded-lg text-ink-muted font-medium underline underline-offset-2"
          @click="requestCancel"
        >
          Cancel enrolment
        </button>
        <button
          type="button"
          :disabled="!cardFile || step2Uploading"
          class="flex-1 min-h-11 bg-brand-green text-navy font-semibold rounded-lg py-2 disabled:bg-sunken disabled:text-ink-subtle disabled:cursor-not-allowed"
          @click="uploadCard"
        >
          {{ step2Uploading ? 'Uploading…' : 'Upload' }}
        </button>
      </div>

      <div v-if="showCancelConfirm" class="rounded-lg border px-4 py-3 text-sm space-y-2" :class="bannerClass('warning')">
        <p>Cancel this enrolment. The entered details and uploaded specimen will be discarded.</p>
        <div class="flex flex-wrap gap-2">
          <button type="button" class="min-h-11 px-3 rounded-lg border border-border-strong bg-surface text-ink font-medium" @click="dismissCancel">
            Keep editing
          </button>
          <button type="button" class="min-h-11 px-3 rounded-lg bg-danger text-ink-inverse font-medium" @click="confirmCancel">
            Discard and cancel
          </button>
        </div>
      </div>
    </div>

    <!-- Step 3: Approve crops -->
    <div v-else-if="step === 3" class="bg-surface border border-border rounded-lg shadow-sm p-6 space-y-4">
      <p class="text-sm font-medium text-ink">
        {{ selectedCount }} of {{ crops.length }} selected ({{ selectionRule }})
      </p>

      <!-- A card photographed at an angle groups two signatures into one region or drops
           one at the edge. Re-shooting the whole card to fix a single specimen is a loop
           with no exit; another photograph adds to what is already here. -->
      <div class="rounded-lg border border-border bg-sunken p-3 space-y-2">
        <p v-if="shortfall > 0" class="text-sm text-ink">
          {{ shortfall }} more {{ shortfall === 1 ? 'signature is' : 'signatures are' }} needed.
          Photograph the missing {{ shortfall === 1 ? 'one' : 'ones' }} — on the card or on
          their own — and they will be added to these.
        </p>
        <p v-else class="text-sm text-ink-muted">
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
          class="min-h-11 rounded-lg border border-border-strong bg-surface px-3 text-sm font-medium text-navy disabled:text-ink-subtle"
          @click="openExtraPhotoPicker"
        >
          {{ addingPhoto ? 'Reading photograph…' : 'Add another photo' }}
        </button>
      </div>

      <div class="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
        <button
          v-for="crop in crops"
          :key="crop.crop_id"
          :data-position="crop.position"
          type="button"
          :aria-pressed="crop.selected"
          class="relative flex flex-col items-center gap-2 rounded-lg border-2 p-2 min-h-11 text-left"
          :class="crop.selected ? 'border-valid-border bg-valid-surface' : 'border-border bg-sunken'"
          @click="toggleCrop(crop)"
        >
          <span
            class="absolute top-1.5 right-1.5 flex h-5 w-5 items-center justify-center rounded-full border"
            :class="crop.selected ? 'bg-valid border-valid text-ink-inverse' : 'bg-surface border-border-strong'"
            aria-hidden="true"
          >
            <svg v-if="crop.selected" xmlns="http://www.w3.org/2000/svg" class="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="3">
              <path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7" />
            </svg>
          </span>
          <span
            class="absolute top-1.5 left-1.5 flex h-5 min-w-5 items-center justify-center rounded-full border border-border-strong bg-surface px-1 text-2xs font-semibold text-ink"
          >{{ crop.position }}</span>
          <img :src="'data:image/png;base64,' + crop.preview_png_base64" :alt="`Signature ${crop.position} found on the card`" class="w-full h-auto rounded" />
          <span class="text-2xs font-medium" :class="crop.selected ? 'text-valid' : 'text-ink-subtle'">
            {{ crop.selected ? 'Selected' : 'Not selected' }}
          </span>
        </button>
      </div>

      <div v-if="step3Error" class="rounded-lg border px-4 py-3 text-sm space-y-1" :class="bannerClass(step3Error.level)">
        <p>{{ step3Error.message }}</p>
        <p v-if="step3Error.note" class="font-medium">{{ step3Error.note }}</p>
      </div>

      <div class="flex flex-wrap gap-3">
        <button
          type="button"
          class="min-h-11 px-4 rounded-lg border border-border-strong bg-surface text-ink font-medium"
          @click="goBack"
        >
          Back
        </button>
        <button
          type="button"
          class="min-h-11 px-4 rounded-lg text-ink-muted font-medium underline underline-offset-2"
          @click="requestCancel"
        >
          Cancel enrolment
        </button>
        <button
          type="button"
          :disabled="!canApprove || step3Submitting"
          class="flex-1 min-h-11 bg-brand-green text-navy font-semibold rounded-lg py-2 disabled:bg-sunken disabled:text-ink-subtle disabled:cursor-not-allowed"
          @click="approveReferences"
        >
          {{ step3Submitting ? 'Approving…' : 'Approve' }}
        </button>
      </div>

      <div v-if="showCancelConfirm" class="rounded-lg border px-4 py-3 text-sm space-y-2" :class="bannerClass('warning')">
        <p>Cancel this enrolment. The entered details and uploaded specimen will be discarded.</p>
        <div class="flex flex-wrap gap-2">
          <button type="button" class="min-h-11 px-3 rounded-lg border border-border-strong bg-surface text-ink font-medium" @click="dismissCancel">
            Keep editing
          </button>
          <button type="button" class="min-h-11 px-3 rounded-lg bg-danger text-ink-inverse font-medium" @click="confirmCancel">
            Discard and cancel
          </button>
        </div>
      </div>
    </div>

    <!-- Success -->
    <div v-else class="bg-surface border border-border rounded-lg shadow-sm p-8 text-center space-y-4">
      <div class="mx-auto w-16 h-16 rounded-full bg-valid-surface flex items-center justify-center">
        <svg xmlns="http://www.w3.org/2000/svg" class="w-10 h-10 text-valid" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
          <path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7" />
        </svg>
      </div>
      <h2 class="text-xl font-bold text-navy">
        {{ successMode === 'append' ? 'Signatures appended to existing customer' : 'New customer enrolled' }}
      </h2>

      <div class="flex items-center justify-center gap-2">
        <code class="bg-sunken rounded px-3 py-1 text-sm text-ink">{{ successCustomerId }}</code>
        <button
          type="button"
          class="text-sm text-navy underline min-h-11 px-1"
          @click="copyCustomerId"
        >
          {{ copied ? 'Copied!' : 'Copy' }}
        </button>
      </div>

      <p class="text-sm text-ink-muted">{{ successReferenceCount }} reference signatures stored</p>

      <button
        type="button"
        class="min-h-11 bg-navy text-ink-inverse font-semibold rounded-lg px-4 py-2"
        @click="enrolAnother"
      >
        Enrol another customer
      </button>
    </div>
  </div>
</template>
