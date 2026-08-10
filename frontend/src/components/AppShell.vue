<script setup>
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { state, isClerk, isVerifier, logout } from '../auth.js'

const route = useRoute()
const router = useRouter()

const showNav = computed(() => route.path !== '/login')

const links = computed(() => {
  if (isClerk.value) {
    return [
      { to: '/enrol', label: 'Enrol' },
      { to: '/verify', label: 'Verify' },
      { to: '/customers', label: 'Customers' },
      { to: '/history', label: 'History' },
    ]
  }
  if (isVerifier.value) {
    return [
      { to: '/verify', label: 'Verify' },
      { to: '/history', label: 'History' },
    ]
  }
  return []
})

async function handleLogout() {
  await logout()
  router.push('/login')
}
</script>

<template>
  <div class="min-h-screen">
    <nav v-if="showNav" class="bg-navy text-ink-inverse">
      <div
        class="mx-auto flex max-w-5xl flex-wrap items-center gap-x-6 gap-y-1 px-4 py-2 sm:px-6"
      >
        <span class="text-lg font-bold tracking-tight">SecureSign</span>

        <div
          class="order-last -mx-1 flex w-full items-center gap-1 overflow-x-auto sm:order-none sm:mx-0 sm:w-auto"
        >
          <router-link
            v-for="link in links"
            :key="link.to"
            :to="link.to"
            class="min-h-11 shrink-0 rounded px-3 py-2 text-sm font-medium text-white/85 transition-colors hover:bg-white/10 hover:text-white flex items-center"
            active-class="bg-white/15 text-white"
          >
            {{ link.label }}
          </router-link>
        </div>

        <div class="ml-auto flex items-center gap-3">
          <span class="hidden text-right leading-tight sm:block">
            <span class="block text-sm font-medium">{{ state.user?.org_name }}</span>
            <span class="block text-xs text-white/70">{{ state.user?.username }}</span>
          </span>
          <span class="text-sm text-white/80 sm:hidden">{{ state.user?.username }}</span>
          <button
            class="min-h-11 rounded bg-brand-green px-4 text-sm font-semibold text-navy transition-colors hover:brightness-95"
            @click="handleLogout"
          >
            Logout
          </button>
        </div>
      </div>
    </nav>

    <main class="mx-auto max-w-5xl px-4 py-8 sm:px-6">
      <router-view />
    </main>
  </div>
</template>
