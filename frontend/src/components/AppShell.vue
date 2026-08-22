<script setup>
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import BrandMark from './BrandMark.vue'
import {
  state, isClerk, isVerifier, isEngineer, isOrgAdmin, mustChangePassword, logout,
} from '../auth.js'

const route = useRoute()
const router = useRouter()

const showNav = computed(() => route.path !== '/login')
const mobileNavOpen = ref(false)

// While a handed-out password is still in force nothing else is reachable, so offering
// the links would only produce bounces.
const links = computed(() => {
  if (mustChangePassword.value) return []
  if (isEngineer.value) {
    return [
      { to: '/engineering', label: 'Model' },
      { to: '/accounts', label: 'Accounts' },
    ]
  }
  const forRole = isClerk.value
    ? [
        { to: '/enrol', label: 'Enrol' },
        { to: '/verify', label: 'Verify' },
        { to: '/customers', label: 'Customers' },
        { to: '/history', label: 'History' },
      ]
    : isVerifier.value
      ? [
          { to: '/verify', label: 'Verify' },
          { to: '/history', label: 'History' },
        ]
      : []
  return isOrgAdmin.value ? [...forRole, { to: '/team', label: 'Team' }] : forRole
})

watch(() => route.path, () => { mobileNavOpen.value = false })

async function handleLogout() {
  await logout()
  router.push('/login')
}
</script>

<template>
  <div v-if="!showNav">
    <router-view />
  </div>

  <div v-else class="min-h-screen w-full lg:grid lg:grid-cols-[15rem_minmax(0,1fr)]">
    <!-- A persistent rail, so content keeps the whole remaining width instead of sitting
         in a centred column with the screen empty on either side of it. -->
    <aside class="flex flex-col bg-navy text-ink-inverse lg:sticky lg:top-0 lg:h-screen">
      <div class="flex items-center justify-between gap-3 px-4 py-3 lg:px-5 lg:py-4">
        <span class="flex items-center gap-2.5">
          <BrandMark :size="20" class="shrink-0" />
          <span class="text-base font-semibold tracking-tight">SecureSign</span>
        </span>
        <button
          type="button"
          class="min-h-11 rounded px-2 text-sm text-white/80 lg:hidden"
          :aria-expanded="mobileNavOpen"
          aria-label="Navigation"
          @click="mobileNavOpen = !mobileNavOpen"
        >
          {{ mobileNavOpen ? 'Close' : 'Menu' }}
        </button>
      </div>

      <nav
        class="flex-1 gap-0.5 px-2 pb-2 lg:flex lg:flex-col lg:px-3"
        :class="mobileNavOpen ? 'flex flex-col' : 'hidden'"
      >
        <router-link
          v-for="link in links"
          :key="link.to"
          :to="link.to"
          class="flex min-h-11 items-center rounded-md px-3 text-sm font-medium text-white/75 transition-colors hover:bg-white/10 hover:text-white"
          active-class="bg-white/12 font-semibold text-white"
        >
          {{ link.label }}
        </router-link>
      </nav>

      <!-- Whose data is on screen, at the foot of the rail where it stays in view. -->
      <div
        class="border-t border-white/12 px-4 py-3 lg:px-5"
        :class="mobileNavOpen ? 'block' : 'hidden lg:block'"
      >
        <p class="truncate text-sm font-medium">{{ state.user?.org_name }}</p>
        <p class="truncate text-xs text-white/55">
          {{ state.user?.username }}
          <span v-if="state.user?.org_code" class="tabular">({{ state.user.org_code }})</span>
        </p>
        <div class="mt-2 flex gap-1">
          <router-link
            v-if="!mustChangePassword"
            :to="{ name: 'change-password', query: { voluntary: '1' } }"
            class="flex min-h-11 flex-1 items-center rounded-md px-2 text-xs font-medium text-white/75 transition-colors hover:bg-white/10 hover:text-white"
          >
            Password
          </router-link>
          <button
            type="button"
            class="min-h-11 rounded-md px-2 text-xs font-medium text-white/75 transition-colors hover:bg-white/10 hover:text-white"
            @click="handleLogout"
          >
            Sign out
          </button>
        </div>
      </div>
    </aside>

    <main class="min-w-0 px-4 py-6 sm:px-6 lg:px-8">
      <router-view />
    </main>
  </div>
</template>
