<script setup>
import { ref, computed } from 'vue'
import { postJson, postForm, ApiError } from '../api.js'

const STEPS = [
  { n: 1, label: 'Details' },
  { n: 2, label: 'Specimen card' },
  { n: 3, label: 'Approve' },
]

const step = ref(1) // 1 | 2 | 3 | 'success'

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

function onFileSelected(e) {
  const file = e.target.files && e.target.files[0]
  if (!file) return
  if (cardPreviewUrl.value) URL.revokeObjectURL(cardPreviewUrl.value)
  cardFile.value = file
  cardPreviewUrl.value = URL.createObjectURL(file)
  step2Error.value = null
}

const crops = ref([])

async function uploadCard() {
  if (!cardFile.value || step2Uploading.value) return
  step2Error.value = null
  step2Uploading.value = true
  try {
    const formData = new FormData()
    formData.append('file', cardFile.value)
    const res = await postForm(`/customers/${enrolmentId.value}/card`, formData)
    crops.value = res.crops.map((c) => ({ ...c, selected: true }))
    step.value = 3
  } catch (err) {
    if (err instanceof ApiError && err.code === 'INSUFFICIENT_SIGNATURES') {
      step2Error.value = { level: 'warning', message: err.message || 'Not enough signatures were detected. Please rescan the card.' }
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
const canApprove = computed(() => selectedCount.value >= 5 && selectedCount.value <= 10)

async function approveReferences() {
  if (!canApprove.value || step3Submitting.value) return
  step3Error.value = null
  step3Submitting.value = true
  try {
    const cropIds = crops.value.filter((c) => c.selected).map((c) => c.crop_id)
    const res = await postJson(`/customers/${enrolmentId.value}/references`, { crop_ids: cropIds })
    saveRecentCustomer(res.customer_id, nationalId.value, fullName.value.trim())
    successCustomerId.value = res.customer_id
    successReferenceCount.value = res.reference_count
    successMode.value = enrolMode.value
    step.value = 'success'
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

function saveRecentCustomer(customerId, nationalIdValue, fullNameValue) {
  const key = 'ss_recent_customers'
  let list = []
  try {
    list = JSON.parse(localStorage.getItem(key) || '[]')
    if (!Array.isArray(list)) list = []
  } catch {
    list = []
  }
  const entry = {
    customer_id: customerId,
    national_id: nationalIdValue,
    full_name: fullNameValue,
    at: new Date().toISOString(),
  }
  list = [entry, ...list].slice(0, 20)
  localStorage.setItem(key, JSON.stringify(list))
}

const expiredMessage = ref('')

function expireAndRestart() {
  expiredMessage.value = 'Enrolment expired, start again'
  resetWizard()
}

function resetWizard() {
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
  crops.value = []
  step3Error.value = null
  successCustomerId.value = ''
  successReferenceCount.value = 0
  successMode.value = null
}

function enrolAnother() {
  expiredMessage.value = ''
  resetWizard()
}

function stepCircleClass(n) {
  const current = step.value === 'success' ? 4 : step.value
  if (current === n) return 'bg-navy text-white'
  if (current > n) return 'bg-brand-green text-white'
  return 'bg-gray-200 text-gray-500'
}
</script>

<template>
  <div class="max-w-2xl mx-auto">
    <h1 class="text-2xl font-bold text-navy mb-6">Enrol customer</h1>

    <div v-if="expiredMessage" class="mb-6 rounded-lg border border-red-400 bg-red-50 text-red-800 px-4 py-3">
      {{ expiredMessage }}
    </div>

    <div
      v-if="enrolMode === 'append' && (step === 2 || step === 3)"
      class="mb-6 rounded-lg border border-navy/30 bg-navy/5 text-navy px-4 py-3 text-sm"
    >
      Customer already registered — new signatures will be verified against the registered references before acceptance.
    </div>

    <div v-if="step !== 'success'" class="flex items-center justify-center gap-3 mb-8">
      <template v-for="(s, i) in STEPS" :key="s.n">
        <div class="flex items-center gap-2">
          <div :class="stepCircleClass(s.n)" class="w-8 h-8 rounded-full flex items-center justify-center font-semibold text-sm">
            {{ s.n }}
          </div>
          <span :class="step === s.n ? 'text-navy font-semibold' : 'text-gray-500'">{{ s.label }}</span>
        </div>
        <div v-if="i < STEPS.length - 1" class="w-8 h-px bg-gray-300"></div>
      </template>
    </div>

    <!-- Step 1: Details -->
    <div v-if="step === 1" class="bg-white rounded-lg shadow p-6 space-y-4">
      <div>
        <label class="block text-sm font-medium text-gray-700 mb-1">National ID</label>
        <input
          v-model="nationalId"
          type="text"
          inputmode="numeric"
          maxlength="9"
          class="w-full rounded-lg border border-gray-300 px-3 py-2 focus:outline-none focus:ring-2 focus:ring-navy"
          placeholder="9-digit national ID"
        />
        <p v-if="nationalId.length > 0 && !nationalIdValid" class="text-sm text-red-600 mt-1">
          National ID must be exactly 9 digits.
        </p>
      </div>

      <div>
        <label class="block text-sm font-medium text-gray-700 mb-1">Full name</label>
        <input
          v-model="fullName"
          type="text"
          class="w-full rounded-lg border border-gray-300 px-3 py-2 focus:outline-none focus:ring-2 focus:ring-navy"
          placeholder="Customer full name"
        />
      </div>

      <div>
        <label class="block text-sm font-medium text-gray-700 mb-1">Consent method</label>
        <select
          v-model="consentMethod"
          class="w-full rounded-lg border border-gray-300 px-3 py-2 focus:outline-none focus:ring-2 focus:ring-navy"
        >
          <option value="signed_form">Signed form</option>
          <option value="in_person">In person</option>
        </select>
      </div>

      <label class="flex items-start gap-2 text-sm text-gray-700">
        <input v-model="consentGranted" type="checkbox" class="mt-1" />
        <span>Customer consents to shared verification by subscribing organisations</span>
      </label>

      <div v-if="step1Error" class="rounded-lg border border-red-400 bg-red-50 text-red-800 px-4 py-3 text-sm">
        {{ step1Error }}
      </div>

      <button
        type="button"
        :disabled="!step1Valid || step1Submitting"
        class="w-full bg-brand-green text-navy font-semibold rounded-lg py-2 disabled:opacity-50 disabled:cursor-not-allowed"
        @click="submitStep1"
      >
        {{ step1Submitting ? 'Submitting…' : 'Continue' }}
      </button>
    </div>

    <!-- Step 2: Specimen card -->
    <div v-else-if="step === 2" class="bg-white rounded-lg shadow p-6 space-y-4">
      <p class="text-sm text-gray-600">
        Card must contain 5-10 signatures, one below the other, with clear spacing
      </p>

      <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <label class="block">
          <span class="block text-sm font-medium text-gray-700 mb-1">Upload file</span>
          <input
            type="file"
            accept="image/*"
            class="w-full text-sm"
            @change="onFileSelected"
          />
        </label>
        <label class="block">
          <span class="block text-sm font-medium text-gray-700 mb-1">Use camera</span>
          <input
            type="file"
            accept="image/*"
            capture="environment"
            class="w-full text-sm"
            @change="onFileSelected"
          />
        </label>
      </div>

      <div v-if="cardPreviewUrl" class="rounded-lg border border-gray-200 p-2">
        <img :src="cardPreviewUrl" alt="Specimen card preview" class="max-h-80 mx-auto rounded" />
      </div>

      <div
        v-if="step2Error"
        :class="step2Error.level === 'warning'
          ? 'border-amber-400 bg-amber-50 text-amber-800'
          : 'border-red-400 bg-red-50 text-red-800'"
        class="rounded-lg border px-4 py-3 text-sm"
      >
        {{ step2Error.message }}
      </div>

      <button
        type="button"
        :disabled="!cardFile || step2Uploading"
        class="w-full bg-brand-green text-navy font-semibold rounded-lg py-2 disabled:opacity-50 disabled:cursor-not-allowed"
        @click="uploadCard"
      >
        {{ step2Uploading ? 'Uploading…' : 'Upload' }}
      </button>
    </div>

    <!-- Step 3: Approve crops -->
    <div v-else-if="step === 3" class="bg-white rounded-lg shadow p-6 space-y-4">
      <p class="text-sm font-medium text-gray-700">
        {{ selectedCount }} of {{ crops.length }} selected (need 5-10)
      </p>

      <div class="grid grid-cols-3 sm:grid-cols-4 lg:grid-cols-5 gap-3">
        <label
          v-for="crop in crops"
          :key="crop.crop_id"
          class="bg-white border border-gray-200 rounded-lg p-2 flex flex-col items-center gap-2 cursor-pointer"
        >
          <img :src="'data:image/png;base64,' + crop.preview_png_base64" class="w-full h-auto rounded" />
          <input v-model="crop.selected" type="checkbox" />
        </label>
      </div>

      <div
        v-if="step3Error"
        :class="step3Error.level === 'warning'
          ? 'border-amber-400 bg-amber-50 text-amber-800'
          : 'border-red-400 bg-red-50 text-red-800'"
        class="rounded-lg border px-4 py-3 text-sm space-y-1"
      >
        <p>{{ step3Error.message }}</p>
        <p v-if="step3Error.note" class="font-medium">{{ step3Error.note }}</p>
      </div>

      <button
        type="button"
        :disabled="!canApprove || step3Submitting"
        class="w-full bg-brand-green text-navy font-semibold rounded-lg py-2 disabled:opacity-50 disabled:cursor-not-allowed"
        @click="approveReferences"
      >
        {{ step3Submitting ? 'Approving…' : 'Approve' }}
      </button>
    </div>

    <!-- Success -->
    <div v-else class="bg-white rounded-lg shadow p-8 text-center space-y-4">
      <div class="mx-auto w-16 h-16 rounded-full bg-green-100 flex items-center justify-center">
        <svg xmlns="http://www.w3.org/2000/svg" class="w-10 h-10 text-green-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
          <path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7" />
        </svg>
      </div>
      <h2 class="text-xl font-bold text-navy">
        {{ successMode === 'append' ? 'Signatures appended to existing customer' : 'New customer enrolled' }}
      </h2>

      <div class="flex items-center justify-center gap-2">
        <code class="bg-gray-100 rounded px-3 py-1 text-sm">{{ successCustomerId }}</code>
        <button
          type="button"
          class="text-sm text-navy underline"
          @click="copyCustomerId"
        >
          {{ copied ? 'Copied!' : 'Copy' }}
        </button>
      </div>

      <p class="text-sm text-gray-600">{{ successReferenceCount }} reference signatures stored</p>

      <button
        type="button"
        class="bg-navy text-white font-semibold rounded-lg px-4 py-2"
        @click="enrolAnother"
      >
        Enrol another customer
      </button>
    </div>
  </div>
</template>
