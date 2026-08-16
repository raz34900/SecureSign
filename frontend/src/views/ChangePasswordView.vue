<script setup>
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { postJson, ApiError } from '../api.js'
import { state, load, roleHome, mustChangePassword } from '../auth.js'

const MIN_LENGTH = 12

const router = useRouter()

const currentPassword = ref('')
const newPassword = ref('')
const confirmPassword = ref('')
const errorMessage = ref('')
const pending = ref(false)

const longEnough = computed(() => newPassword.value.length >= MIN_LENGTH)
const matches = computed(
  () => confirmPassword.value.length > 0 && newPassword.value === confirmPassword.value,
)
const isDifferent = computed(
  () => newPassword.value.length === 0 || newPassword.value !== currentPassword.value,
)
const canSubmit = computed(
  () => currentPassword.value.length > 0 && longEnough.value && matches.value && isDifferent.value,
)

async function handleSubmit() {
  if (!canSubmit.value || pending.value) return
  errorMessage.value = ''
  pending.value = true
  try {
    await postJson('/auth/password', {
      current_password: currentPassword.value,
      new_password: newPassword.value,
    })
    await load() // clears must_change_password, which the router guard reads
    router.push(roleHome())
  } catch (err) {
    errorMessage.value = err instanceof ApiError ? err.message : 'Could not change the password.'
  } finally {
    pending.value = false
  }
}
</script>

<template>
  <div class="max-w-md mx-auto">
    <div class="bg-surface border border-border rounded-lg shadow-sm p-8 space-y-5">
      <div>
        <h1 class="text-2xl font-bold text-navy">
          {{ mustChangePassword ? 'Choose your password' : 'Change your password' }}
        </h1>
        <p v-if="mustChangePassword" class="text-sm text-ink-muted mt-2">
          Your account was created with a password someone else chose, so it is not private
          yet. Pick your own before continuing — nothing else will open until you do.
        </p>
        <p v-else class="text-sm text-ink-muted mt-2">
          Signed in as {{ state.user?.username }} at {{ state.user?.org_name }}.
        </p>
      </div>

      <form class="space-y-4" @submit.prevent="handleSubmit">
        <div v-if="errorMessage" class="rounded-lg border border-danger-border bg-danger-surface text-danger text-sm px-4 py-3">
          {{ errorMessage }}
        </div>

        <label class="block">
          <span class="block text-sm font-medium text-ink-muted mb-1">Current password</span>
          <input
            v-model="currentPassword"
            type="password"
            required
            autocomplete="current-password"
            class="w-full min-h-11 rounded-lg border border-border bg-surface text-ink px-3 py-2"
          />
        </label>

        <label class="block">
          <span class="block text-sm font-medium text-ink-muted mb-1">New password</span>
          <input
            v-model="newPassword"
            type="password"
            required
            autocomplete="new-password"
            class="w-full min-h-11 rounded-lg border border-border bg-surface text-ink px-3 py-2"
          />
          <p class="text-xs mt-1" :class="longEnough ? 'text-valid' : 'text-ink-subtle'">
            At least {{ MIN_LENGTH }} characters.
          </p>
          <p v-if="!isDifferent" class="text-xs text-danger mt-1">
            It must be different from your current password.
          </p>
        </label>

        <label class="block">
          <span class="block text-sm font-medium text-ink-muted mb-1">Confirm new password</span>
          <input
            v-model="confirmPassword"
            type="password"
            required
            autocomplete="new-password"
            class="w-full min-h-11 rounded-lg border border-border bg-surface text-ink px-3 py-2"
          />
          <p v-if="confirmPassword.length > 0 && !matches" class="text-xs text-danger mt-1">
            The two entries do not match.
          </p>
        </label>

        <button
          type="submit"
          :disabled="!canSubmit || pending"
          class="w-full min-h-11 bg-brand-green text-navy font-semibold rounded-lg py-2 disabled:bg-sunken disabled:text-ink-subtle disabled:cursor-not-allowed"
        >
          {{ pending ? 'Saving…' : 'Save password' }}
        </button>
      </form>
    </div>
  </div>
</template>
