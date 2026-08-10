<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { login, roleHome } from '../auth.js'
import { ApiError } from '../api.js'

const router = useRouter()

const orgName = ref('')
const username = ref('')
const password = ref('')
const errorMessage = ref('')
const pending = ref(false)

async function handleSubmit() {
  errorMessage.value = ''
  pending.value = true
  try {
    await login(orgName.value, username.value, password.value)
    router.push(roleHome())
  } catch (err) {
    errorMessage.value = err instanceof ApiError ? err.message : 'Login failed. Please try again.'
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
        <div v-if="errorMessage" class="rounded-lg border border-danger-border bg-danger-surface text-danger text-sm px-4 py-3">
          {{ errorMessage }}
        </div>

        <div>
          <label for="org-name" class="block text-sm font-medium text-ink-muted mb-1">Organization</label>
          <input
            id="org-name"
            v-model="orgName"
            type="text"
            required
            autocomplete="organization"
            class="w-full min-h-11 rounded-lg border border-border bg-surface text-ink px-3 py-2"
          />
          <p class="text-xs text-ink-subtle mt-1">
            Your institution's registered name, for example: Bank A
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
