<script setup>
import { computed, ref } from 'vue'
import { postForm, ApiError } from '../api.js'
import { isClerk } from '../auth.js'

const NATIONAL_ID_PATTERN = /^\d{9}$/

const nationalId = ref('')
const file = ref(null)
const previewUrl = ref('')
const pending = ref(false)
const result = ref(null)
const errorNotice = ref(null) // { kind: 'amber' | 'red', message: string }

const fileInput = ref(null)
const cameraInput = ref(null)

const nationalIdTouched = ref(false)
const nationalIdValid = computed(() => NATIONAL_ID_PATTERN.test(nationalId.value))
const canSubmit = computed(() => nationalIdValid.value && !!file.value && !pending.value)

const referencesPassedCount = computed(() =>
  (result.value?.references ?? []).filter((r) => r.passed).length,
)

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

async function handleSubmit() {
  if (!canSubmit.value) return
  errorNotice.value = null
  result.value = null
  pending.value = true
  try {
    const formData = new FormData()
    formData.append('national_id', nationalId.value)
    formData.append('file', file.value)
    result.value = await postForm('/verify', formData)
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) {
      errorNotice.value = { kind: 'amber', message: err.message }
    } else if (err instanceof ApiError && err.status === 422) {
      errorNotice.value = { kind: 'red', message: err.message }
    } else if (err instanceof ApiError) {
      errorNotice.value = { kind: 'red', message: err.message }
    } else {
      errorNotice.value = { kind: 'red', message: 'Something went wrong. Please try again.' }
    }
  } finally {
    pending.value = false
  }
}

function reset() {
  nationalId.value = ''
  nationalIdTouched.value = false
  file.value = null
  if (previewUrl.value) URL.revokeObjectURL(previewUrl.value)
  previewUrl.value = ''
  errorNotice.value = null
  result.value = null
}
</script>

<template>
  <div class="max-w-2xl mx-auto">
    <h1 class="text-2xl font-bold text-navy mb-6">Verify Signature</h1>

    <div v-if="!result" class="bg-white rounded-lg shadow p-6 space-y-6">
      <div v-if="errorNotice" :class="[
        'rounded-lg px-4 py-3 text-sm border',
        errorNotice.kind === 'amber'
          ? 'bg-amber-50 border-amber-200 text-amber-800'
          : 'bg-red-50 border-red-200 text-red-700',
      ]">
        {{ errorNotice.message }}
      </div>

      <div>
        <label for="national-id" class="block text-sm font-medium text-gray-700 mb-1">National ID</label>
        <input
          id="national-id"
          v-model="nationalId"
          type="text"
          inputmode="numeric"
          maxlength="9"
          placeholder="9-digit ID"
          class="w-full rounded-lg border border-gray-300 px-3 py-2 focus:outline-none focus:ring-2 focus:ring-brand-green"
          @blur="nationalIdTouched = true"
        />
        <p v-if="nationalIdTouched && !nationalIdValid" class="text-sm text-red-600 mt-1">
          National ID must be exactly 9 digits.
        </p>
      </div>

      <div>
        <span class="block text-sm font-medium text-gray-700 mb-1">Signature image</span>
        <input ref="fileInput" type="file" accept="image/*" class="hidden" @change="handleFileChange" />
        <input ref="cameraInput" type="file" accept="image/*" capture="environment" class="hidden" @change="handleFileChange" />

        <div class="flex flex-col sm:flex-row gap-3">
          <button
            type="button"
            class="flex-1 border-2 border-dashed border-gray-300 rounded-lg py-6 px-4 text-gray-600 hover:border-brand-green hover:text-navy transition"
            @click="openFilePicker"
          >
            Choose file
          </button>
          <button
            type="button"
            class="flex-1 border-2 border-dashed border-gray-300 rounded-lg py-6 px-4 text-gray-600 hover:border-brand-green hover:text-navy transition"
            @click="openCamera"
          >
            Use camera
          </button>
        </div>

        <div v-if="previewUrl" class="mt-4">
          <img :src="previewUrl" alt="Selected signature preview" class="max-h-56 rounded-lg border border-gray-200 mx-auto" />
        </div>
      </div>

      <button
        type="button"
        :disabled="!canSubmit"
        class="w-full bg-brand-green text-navy font-semibold rounded-lg py-2.5 hover:brightness-95 disabled:opacity-50 disabled:cursor-not-allowed transition"
        @click="handleSubmit"
      >
        {{ pending ? 'Verifying…' : 'Verify' }}
      </button>
    </div>

    <div v-else class="bg-white rounded-lg shadow p-8 text-center space-y-6">
      <div>
        <span
          :class="[
            'inline-block rounded-full px-8 py-4 text-3xl font-extrabold tracking-wide',
            result.verdict === 'VALID' ? 'bg-brand-green/20 text-green-700' : 'bg-red-100 text-red-700',
          ]"
        >
          {{ result.verdict }}
        </span>
      </div>

      <div class="text-5xl font-bold text-navy">{{ result.confidence }}%</div>

      <div class="font-mono text-sm text-gray-500 space-x-4">
        <span>distance: {{ result.distance }}</span>
        <span>threshold: {{ result.threshold }}</span>
      </div>

      <div class="border-t border-gray-200 pt-4 text-xs text-gray-400 space-y-1">
        <p>model: {{ result.model_version }}</p>
        <p>request: {{ result.request_id }}</p>
        <p>verified at: {{ result.verified_at }}</p>
      </div>

      <div v-if="isClerk && result.references" class="border-t border-gray-200 pt-6 text-left space-y-4">
        <h3 class="text-sm font-medium text-gray-700">Signature comparison</h3>

        <div class="border-2 border-navy rounded-lg p-2 max-w-xs mx-auto">
          <img :src="previewUrl" alt="Submitted signature" class="w-full h-auto rounded" />
          <p class="text-center text-xs text-navy font-medium mt-1">Submitted signature</p>
        </div>

        <div class="grid grid-cols-3 sm:grid-cols-4 lg:grid-cols-5 gap-3">
          <div
            v-for="(anchor, index) in result.references"
            :key="anchor.reference_id"
            :class="[
              'bg-white rounded-lg p-2 border-2',
              anchor.passed ? 'border-green-500' : 'border-red-500',
            ]"
          >
            <img
              :src="'data:image/png;base64,' + anchor.image_png_base64"
              alt="Reference signature anchor"
              class="w-full h-auto rounded"
            />
            <p
              :class="[
                'text-center text-xs font-medium mt-1',
                anchor.passed ? 'text-green-700' : 'text-red-700',
              ]"
            >
              Anchor {{ index + 1 }} - {{ anchor.passed ? 'PASS' : 'FAIL' }}
              {{ Number(anchor.confidence).toFixed(1) }}%
            </p>
            <p class="text-center font-mono text-[10px] text-gray-400">
              distance: {{ anchor.distance }}
            </p>
          </div>
        </div>

        <p class="text-sm text-gray-600 text-center">
          {{ referencesPassedCount }} of {{ result.references.length }} anchors passed
        </p>
      </div>

      <button
        type="button"
        class="bg-navy text-white font-semibold rounded-lg px-6 py-2.5 hover:brightness-110 transition"
        @click="reset"
      >
        New check
      </button>
    </div>
  </div>
</template>
