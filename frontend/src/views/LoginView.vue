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
  <div class="min-h-screen bg-gray-100 flex items-center justify-center px-4">
    <div class="w-full max-w-sm bg-white rounded-lg shadow-md p-8">
      <h1 class="text-3xl font-bold text-navy text-center mb-6">SecureSign</h1>

      <form class="space-y-4" @submit.prevent="handleSubmit">
        <div v-if="errorMessage" class="bg-red-50 border border-red-200 text-red-700 text-sm rounded-lg px-4 py-3">
          {{ errorMessage }}
        </div>

        <div>
          <label for="org-name" class="block text-sm font-medium text-gray-700 mb-1">Organization</label>
          <input
            id="org-name"
            v-model="orgName"
            type="text"
            required
            class="w-full rounded-lg border border-gray-300 px-3 py-2 focus:outline-none focus:ring-2 focus:ring-brand-green"
          />
        </div>

        <div>
          <label for="username" class="block text-sm font-medium text-gray-700 mb-1">Username</label>
          <input
            id="username"
            v-model="username"
            type="text"
            required
            class="w-full rounded-lg border border-gray-300 px-3 py-2 focus:outline-none focus:ring-2 focus:ring-brand-green"
          />
        </div>

        <div>
          <label for="password" class="block text-sm font-medium text-gray-700 mb-1">Password</label>
          <input
            id="password"
            v-model="password"
            type="password"
            required
            class="w-full rounded-lg border border-gray-300 px-3 py-2 focus:outline-none focus:ring-2 focus:ring-brand-green"
          />
        </div>

        <button
          type="submit"
          :disabled="pending"
          class="w-full bg-brand-green text-navy font-semibold rounded-lg py-2.5 hover:brightness-95 disabled:opacity-50 disabled:cursor-not-allowed transition"
        >
          {{ pending ? 'Signing in…' : 'Sign in' }}
        </button>
      </form>
    </div>
  </div>
</template>
