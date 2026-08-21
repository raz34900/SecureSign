<script setup>
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { postJson } from '../api.js'
import { state, load, roleHome, mustChangePassword } from '../auth.js'
import NoticeBanner from '../components/NoticeBanner.vue'

const MIN_LENGTH = 12

/* Mirrors PASSWORD_RULES in backend/app/services/accounts.py, which is the authority and
   re-checks every one of these. Kept here so the reader sees a rule turn green as they
   type rather than being told what was wrong after submitting. A test fails if the two
   lists drift apart. */
const RULES = [
  { key: 'length', label: `At least ${MIN_LENGTH} characters`, holds: (t) => t.length >= MIN_LENGTH },
  { key: 'uppercase', label: 'An upper-case letter', holds: (t) => /[A-Z]/.test(t) },
  { key: 'lowercase', label: 'A lower-case letter', holds: (t) => /[a-z]/.test(t) },
  { key: 'digit', label: 'A number', holds: (t) => /[0-9]/.test(t) },
  { key: 'symbol', label: 'A symbol', holds: (t) => /[^A-Za-z0-9]/.test(t) },
]

const router = useRouter()

const currentPassword = ref('')
const newPassword = ref('')
const confirmPassword = ref('')
const errorMessage = ref('')
const pending = ref(false)

const checks = computed(() =>
  RULES.map((rule) => ({ ...rule, met: rule.holds(newPassword.value) })),
)
const allRulesMet = computed(() => checks.value.every((rule) => rule.met))
const matches = computed(
  () => confirmPassword.value.length > 0 && newPassword.value === confirmPassword.value,
)
const isDifferent = computed(
  () => newPassword.value.length === 0 || newPassword.value !== currentPassword.value,
)
const canSubmit = computed(
  () => currentPassword.value.length > 0 && allRulesMet.value && matches.value
    && isDifferent.value,
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
    errorMessage.value = err.message || 'Could not change the password.'
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
          yet. Pick your own before continuing - nothing else will open until you do.
        </p>
        <p v-else class="text-sm text-ink-muted mt-2">
          Signed in as {{ state.user?.username }} at {{ state.user?.org_name }}.
        </p>
      </div>

      <form class="space-y-4" @submit.prevent="handleSubmit">
        <NoticeBanner v-if="errorMessage">
          {{ errorMessage }}
        </NoticeBanner>

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
          <ul class="mt-2 space-y-1" aria-label="Password requirements">
            <li
              v-for="rule in checks"
              :key="rule.key"
              class="flex items-center gap-2 text-xs"
              :class="rule.met ? 'text-valid' : 'text-ink-subtle'"
            >
              <span aria-hidden="true" class="w-3 shrink-0 text-center">{{ rule.met ? '✓' : '○' }}</span>
              <span>{{ rule.label }}</span>
              <span class="sr-only">{{ rule.met ? 'met' : 'not met' }}</span>
            </li>
          </ul>
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
