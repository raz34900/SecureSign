<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { login, roleHome } from '../auth.js'
import BrandMark from '../components/BrandMark.vue'
import NoticeBanner from '../components/NoticeBanner.vue'

const router = useRouter()

const orgCode = ref('')
const username = ref('')
const password = ref('')
const errorMessage = ref('')
const pending = ref(false)

async function handleSubmit() {
  errorMessage.value = ''
  pending.value = true
  try {
    // Codes are issued uppercase; typing them lowercase is not a failed login.
    await login(orgCode.value.trim().toUpperCase(), username.value.trim(), password.value)
    router.push(roleHome())
  } catch (err) {
    errorMessage.value = err.message || 'Login failed. Please try again.'
  } finally {
    pending.value = false
  }
}
</script>

<template>
  <div class="grid min-h-screen grid-rows-[auto_1fr] lg:grid-cols-[5fr_7fr] lg:grid-rows-1">
    <!-- The registry identifies itself before asking who you are. On a narrow screen it
         collapses to a band rather than stacking a full panel above the form. -->
    <aside class="flex flex-col gap-16 bg-navy-ground px-6 py-6 text-ink-inverse sm:px-10 lg:justify-between lg:px-14 lg:py-14">
      <div class="flex items-center gap-3">
        <BrandMark :size="34" title="SecureSign" class="shrink-0" />
        <span class="text-xl font-semibold tracking-tight">SecureSign</span>
      </div>

      <div class="hidden max-w-sm lg:block">
        <p class="text-3xl font-semibold leading-tight tracking-tight">
          Signature verification across institutions.
        </p>
        <p class="mt-4 text-base leading-relaxed text-white/70">
          One customer, enrolled once. Every subscribing organisation checks against the
          same references, and sees only its own records.
        </p>
      </div>

      <p class="hidden text-xs text-white/45 lg:block">
        Access is issued by your institution.
      </p>
    </aside>

    <main class="flex items-start justify-center px-6 py-10 sm:px-10 lg:items-center lg:px-14 lg:py-14">
      <div class="w-full max-w-sm">
        <h1 class="text-2xl font-semibold tracking-tight text-ink">Sign in</h1>
        <p class="mt-1.5 text-sm text-ink-muted">
          Use the credentials issued to you, not a shared account.
        </p>

        <form class="mt-8 space-y-5" @submit.prevent="handleSubmit">
          <NoticeBanner v-if="errorMessage">{{ errorMessage }}</NoticeBanner>

          <div>
            <label for="org-code" class="block text-sm font-medium text-ink mb-1.5">
              Organisation code
            </label>
            <input
              id="org-code"
              v-model="orgCode"
              type="text"
              required
              maxlength="12"
              autocapitalize="characters"
              spellcheck="false"
              autocomplete="organization"
              placeholder="BA11"
              class="w-full min-h-11 rounded-md border border-border-strong bg-surface px-3 py-2 font-mono uppercase tracking-wider text-ink placeholder:text-ink-subtle placeholder:tracking-normal"
            />
          </div>

          <div>
            <label for="username" class="block text-sm font-medium text-ink mb-1.5">Username</label>
            <input
              id="username"
              v-model="username"
              type="text"
              required
              autocomplete="username"
              class="w-full min-h-11 rounded-md border border-border-strong bg-surface px-3 py-2 text-ink"
            />
          </div>

          <div>
            <label for="password" class="block text-sm font-medium text-ink mb-1.5">Password</label>
            <input
              id="password"
              v-model="password"
              type="password"
              required
              autocomplete="current-password"
              class="w-full min-h-11 rounded-md border border-border-strong bg-surface px-3 py-2 text-ink"
            />
          </div>

          <button
            type="submit"
            :disabled="pending"
            class="w-full min-h-11 rounded-md bg-navy py-2.5 font-semibold text-ink-inverse transition-colors hover:bg-navy-deep disabled:bg-sunken disabled:text-ink-subtle disabled:cursor-not-allowed"
          >
            {{ pending ? 'Signing in…' : 'Sign in' }}
          </button>
        </form>
      </div>
    </main>
  </div>
</template>
