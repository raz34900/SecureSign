<script setup>
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { state, isClerk, isVerifier, logout } from '../auth.js'

const route = useRoute()

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
}
</script>

<template>
  <div>
    <nav v-if="showNav" class="bg-navy text-white px-6 py-3 flex items-center justify-between">
      <div class="flex items-center gap-8">
        <span class="font-bold text-lg">SecureSign</span>
        <router-link
          v-for="link in links"
          :key="link.to"
          :to="link.to"
          class="text-white/90 hover:text-brand-green"
        >
          {{ link.label }}
        </router-link>
      </div>
      <div class="flex items-center gap-4">
        <span class="text-white/80">{{ state.user?.username }}</span>
        <button
          class="bg-brand-green text-navy font-semibold px-3 py-1 rounded"
          @click="handleLogout"
        >
          Logout
        </button>
      </div>
    </nav>
    <main class="max-w-5xl mx-auto px-6 py-8">
      <router-view />
    </main>
  </div>
</template>
