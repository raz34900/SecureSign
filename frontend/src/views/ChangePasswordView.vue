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
const metCount = computed(() => checks.value.filter((rule) => rule.met).length)
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
  <div class="max-w-4xl space-y-6">
    <header>
      <h1 class="text-xl font-semibold text-ink">
        {{ mustChangePassword ? 'Choose your password' : 'Change your password' }}
      </h1>
      <p v-if="mustChangePassword" class="mt-1 max-w-prose text-sm text-ink-muted">
        Your account was created with a password someone else chose, so it is not private
        yet. Pick your own before continuing — nothing else will open until you do.
      </p>
      <p v-else class="mt-1 max-w-prose text-sm text-ink-muted">
        Signed in as {{ state.user?.username }} at {{ state.user?.org_name }}.
      </p>
    </header>

    <form class="border-t border-border pt-4" @submit.prevent="handleSubmit">
      <NoticeBanner v-if="errorMessage" level="error" class="mb-4">
        {{ errorMessage }}
      </NoticeBanner>

      <div class="grid gap-x-10 gap-y-6 sm:grid-cols-[minmax(0,20rem)_minmax(0,18rem)]">
        <div class="space-y-3">
          <label class="block">
            <span class="block text-xs font-semibold uppercase tracking-wide text-ink-muted">Current password</span>
            <input
              v-model="currentPassword"
              type="password"
              required
              autocomplete="current-password"
              class="mt-1.5 w-full min-h-11 rounded-md border border-border-strong bg-surface px-3 py-2 text-sm text-ink"
            />
          </label>

          <label class="block">
            <span class="block text-xs font-semibold uppercase tracking-wide text-ink-muted">New password</span>
            <input
              v-model="newPassword"
              type="password"
              required
              autocomplete="new-password"
              aria-describedby="password-requirements"
              class="mt-1.5 w-full min-h-11 rounded-md border border-border-strong bg-surface px-3 py-2 text-sm text-ink"
            />
            <p v-if="!isDifferent" class="mt-1.5 text-xs text-danger">
              It must be different from your current password.
            </p>
          </label>

          <label class="block">
            <span class="block text-xs font-semibold uppercase tracking-wide text-ink-muted">Confirm new password</span>
            <input
              v-model="confirmPassword"
              type="password"
              required
              autocomplete="new-password"
              class="mt-1.5 w-full min-h-11 rounded-md border border-border-strong bg-surface px-3 py-2 text-sm text-ink"
            />
            <p v-if="confirmPassword.length > 0 && !matches" class="mt-1.5 text-xs text-danger">
              The two entries do not match.
            </p>
          </label>
        </div>

        <!-- Beside the field rather than under it: the rules are a reference the reader
             checks while typing, not a verdict delivered afterwards. -->
        <section id="password-requirements" class="sm:border-l sm:border-border sm:pl-8">
          <h2 class="text-xs font-semibold uppercase tracking-wide text-ink-muted">
            Requirements
            <span class="tabular ml-1 font-normal">{{ metCount }}/{{ checks.length }}</span>
          </h2>
          <ul class="mt-3 space-y-2">
            <li
              v-for="rule in checks"
              :key="rule.key"
              class="flex items-center gap-2.5 text-sm"
            >
              <span
                aria-hidden="true"
                class="h-1.5 w-1.5 shrink-0 rounded-full transition-colors"
                :class="rule.met ? 'bg-brand-green-deep' : 'bg-border-strong'"
              ></span>
              <span class="tabular transition-colors" :class="rule.met ? 'text-ink' : 'text-ink-muted'">
                {{ rule.label }}
              </span>
              <span class="sr-only">{{ rule.met ? 'met' : 'not met' }}</span>
            </li>
          </ul>
        </section>
      </div>

      <div class="mt-6 flex items-center gap-2 border-t border-border pt-4">
        <button
          type="submit"
          :disabled="!canSubmit || pending"
          class="min-h-11 rounded-md bg-navy px-5 text-sm font-semibold text-ink-inverse disabled:bg-sunken disabled:text-ink-subtle disabled:cursor-not-allowed"
        >
          {{ pending ? 'Saving…' : 'Save password' }}
        </button>
        <!-- Only offered when there is somewhere to go back to; a handed-out password
             leaves nothing else open. -->
        <button
          v-if="!mustChangePassword"
          type="button"
          class="min-h-11 rounded-md px-4 text-sm font-medium text-ink-muted hover:text-ink"
          @click="router.push(roleHome())"
        >
          Cancel
        </button>
      </div>
    </form>
  </div>
</template>
