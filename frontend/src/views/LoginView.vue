<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { login, roleHome } from '../auth.js'
import { ApiError } from '../api.js'
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
  <div class="min-h-screen flex items-center justify-center px-4">
    <div class="w-full max-w-sm bg-surface border border-border rounded-lg shadow-sm p-8">
      <h1 class="text-3xl font-bold text-navy text-center mb-6">SecureSign</h1>

      <form class="space-y-4" @submit.prevent="handleSubmit">
        <NoticeBanner v-if="errorMessage">
          {{ errorMessage }}
        </NoticeBanner>

        <div>
          <label for="org-code" class="block text-sm font-medium text-ink-muted mb-1">
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
            class="w-full min-h-11 rounded-lg border border-border bg-surface text-ink px-3 py-2 font-mono uppercase"
          />
          <p class="text-xs text-ink-subtle mt-1">
            The code issued to your institution, for example: BA11
          </p>
        </div>

        <div>
          <label for="username" class="block text-sm font-medium text-ink-muted mb-1">Username</label>
          <input
            id="username"
            v-model="username"
            type="text"
            required
            autocomplete="username"
            class="w-full min-h-11 rounded-lg border border-border bg-surface text-ink px-3 py-2"
          />
        </div>

        <div>
          <label for="password" class="block text-sm font-medium text-ink-muted mb-1">Password</label>
          <input
            id="password"
            v-model="password"
            type="password"
            required
            autocomplete="current-password"
            class="w-full min-h-11 rounded-lg border border-border bg-surface text-ink px-3 py-2"
          />
        </div>

        <button
          type="submit"
          :disabled="pending"
          class="w-full min-h-11 font-semibold rounded-lg py-2.5 transition-colors bg-brand-green text-navy hover:brightness-95 disabled:bg-sunken disabled:text-ink-subtle disabled:cursor-not-allowed"
        >
          {{ pending ? 'Signing in…' : 'Sign in' }}
        </button>
      </form>
    </div>
  </div>
</template>
