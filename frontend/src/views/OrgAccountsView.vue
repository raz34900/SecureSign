<script setup>
import { computed, onMounted, ref } from 'vue'
import { get, postJson, del, ApiError } from '../api.js'
import { formatDateTime } from '../format.js'
import { state } from '../auth.js'

const MIN_PASSWORD_LENGTH = 12

/* Mirrors the server, which is the authority. "engineer" is absent on purpose: it
   belongs to the operator, and no institution can create one. */
const ROLES_BY_ORG_TYPE = {
  financial: ['clerk', 'verifier', 'org_admin'],
  subscriber: ['verifier', 'org_admin'],
}

const organisation = ref(null)
const users = ref([])
const loading = ref(true)
const loadError = ref('')
const actionError = ref('')
const notice = ref('')

const form = ref({ username: '', role: '', password: '' })
const saving = ref(false)

const resettingId = ref('')
const resetPassword = ref('')
const confirmingDeleteId = ref('')

const availableRoles = computed(() => ROLES_BY_ORG_TYPE[organisation.value?.type] ?? [])

const formValid = computed(
  () => /^[a-z0-9][a-z0-9._-]{2,79}$/.test(form.value.username.trim())
    && availableRoles.value.includes(form.value.role)
    && form.value.password.length >= MIN_PASSWORD_LENGTH,
)

async function loadUsers() {
  try {
    const body = await get('/org/users')
    organisation.value = body.organisation
    users.value = body.users
    if (!form.value.role) form.value.role = availableRoles.value[0] ?? ''
  } catch (err) {
    loadError.value = err instanceof ApiError ? err.message : 'Failed to load the team.'
  }
}

async function addUser() {
  if (!formValid.value || saving.value) return
  saving.value = true
  actionError.value = ''
  notice.value = ''
  try {
    const created = await postJson('/org/users', {
      username: form.value.username.trim(),
      role: form.value.role,
      password: form.value.password,
    })
    notice.value = `${created.username} added. Give them the password you set - they will be asked to replace it when they first sign in.`
    form.value = { username: '', role: availableRoles.value[0] ?? '', password: '' }
    await loadUsers()
  } catch (err) {
    actionError.value = err.message || 'Failed to add the user.'
  } finally {
    saving.value = false
  }
}

function startReset(row) {
  resettingId.value = resettingId.value === row.user_id ? '' : row.user_id
  resetPassword.value = ''
  actionError.value = ''
  notice.value = ''
}

async function submitReset(row) {
  if (resetPassword.value.length < MIN_PASSWORD_LENGTH) return
  actionError.value = ''
  try {
    await postJson(`/org/users/${row.user_id}/password`, { password: resetPassword.value })
    notice.value = `${row.username}'s password was reset and they were signed out everywhere.`
    resettingId.value = ''
    resetPassword.value = ''
    await loadUsers()
  } catch (err) {
    actionError.value = err.message || 'Failed to reset the password.'
  }
}

async function setActive(row, isActive) {
  actionError.value = ''
  notice.value = ''
  try {
    await postJson(`/org/users/${row.user_id}/active`, { is_active: isActive })
    await loadUsers()
  } catch (err) {
    actionError.value = err.message || 'Failed to change the account.'
  }
}

async function removeUser(row) {
  actionError.value = ''
  notice.value = ''
  try {
    await del(`/org/users/${row.user_id}`)
    notice.value = `${row.username} was deleted.`
    confirmingDeleteId.value = ''
    await loadUsers()
  } catch (err) {
    actionError.value = err.message || 'Failed to delete the user.'
    confirmingDeleteId.value = ''
  }
}

onMounted(async () => {
  await loadUsers()
  loading.value = false
})
</script>

<template>
  <div class="max-w-4xl mx-auto space-y-6">
    <div>
      <h1 class="text-2xl font-bold text-navy">Team</h1>
      <p class="text-sm text-ink-muted mt-1">
        The people who sign in for
        <span class="font-medium text-ink">{{ organisation?.name || state.user?.org_name }}</span>.
        You can only see and manage your own organisation's accounts.
      </p>
    </div>

    <div v-if="loadError" class="bg-danger-surface border border-danger-border text-danger text-sm rounded-lg px-4 py-3">
      {{ loadError }}
    </div>

    <div v-else-if="loading" class="text-center text-ink-subtle py-12">Loading…</div>

    <template v-else>
      <p v-if="actionError" class="rounded-lg border border-danger-border bg-danger-surface text-danger text-sm px-4 py-3">
        {{ actionError }}
      </p>
      <p v-if="notice" class="rounded-lg border border-valid-border bg-valid-surface text-valid text-sm px-4 py-3">
        {{ notice }}
      </p>

      <div class="bg-surface rounded-lg shadow divide-y divide-border">
        <div v-for="row in users" :key="row.user_id" class="p-4 space-y-3">
          <div class="flex flex-wrap items-center justify-between gap-3">
            <div>
              <p class="font-medium text-ink">
                {{ row.username }}
                <span v-if="row.user_id === state.user?.user_id" class="text-xs text-ink-subtle">(you)</span>
              </p>
              <p class="text-xs text-ink-muted">
                {{ row.role }} · added {{ formatDateTime(row.created_at) }}
                <span v-if="row.must_change_password" class="text-borderline font-medium">
                  · has not set their own password yet
                </span>
              </p>
            </div>

            <div class="flex flex-wrap gap-2">
              <button
                type="button"
                class="min-h-11 rounded-lg border border-border-strong bg-surface px-3 text-xs font-medium text-ink"
                @click="startReset(row)"
              >
                {{ resettingId === row.user_id ? 'Cancel' : 'Reset password' }}
              </button>
              <button
                type="button"
                class="min-h-11 rounded-lg border px-3 text-xs font-semibold"
                :class="row.is_active
                  ? 'border-valid-border bg-valid-surface text-valid'
                  : 'border-border-strong bg-sunken text-ink-muted'"
                @click="setActive(row, !row.is_active)"
              >
                {{ row.is_active ? 'Active' : 'Disabled' }}
              </button>
              <button
                v-if="row.deletable && row.user_id !== state.user?.user_id"
                type="button"
                class="min-h-11 rounded-lg border border-danger-border bg-surface px-3 text-xs font-medium text-danger"
                @click="confirmingDeleteId = confirmingDeleteId === row.user_id ? '' : row.user_id"
              >
                Delete
              </button>
              <span
                v-else-if="!row.deletable"
                class="min-h-11 inline-flex items-center px-3 text-xs text-ink-subtle"
                title="This account has verifications on record, so deleting it would break the audit trail."
              >
                Has history
              </span>
            </div>
          </div>

          <div v-if="resettingId === row.user_id" class="flex flex-wrap gap-2 items-center">
            <input
              v-model="resetPassword"
              type="password"
              autocomplete="new-password"
              :placeholder="`New password, at least ${MIN_PASSWORD_LENGTH} characters`"
              class="flex-1 min-w-[16rem] min-h-11 rounded-lg border border-border-strong bg-surface text-ink px-3 py-2 text-sm"
            />
            <button
              type="button"
              :disabled="resetPassword.length < MIN_PASSWORD_LENGTH"
              class="min-h-11 rounded-lg bg-navy px-4 text-sm font-semibold text-ink-inverse disabled:opacity-50"
              @click="submitReset(row)"
            >
              Set password
            </button>
            <p class="w-full text-xs text-ink-muted">
              They will be signed out everywhere and asked to choose their own password.
            </p>
          </div>

          <div v-if="confirmingDeleteId === row.user_id" class="rounded-lg border border-warning-border bg-warning-surface px-4 py-3 text-sm space-y-2">
            <p class="text-warning">Delete {{ row.username }}? This cannot be undone.</p>
            <div class="flex gap-2">
              <button
                type="button"
                class="min-h-11 rounded-lg bg-danger px-4 text-sm font-semibold text-ink-inverse"
                @click="removeUser(row)"
              >
                Delete
              </button>
              <button
                type="button"
                class="min-h-11 rounded-lg border border-border-strong bg-surface px-4 text-sm font-medium text-ink"
                @click="confirmingDeleteId = ''"
              >
                Keep
              </button>
            </div>
          </div>
        </div>
      </div>

      <div class="bg-surface rounded-lg shadow p-6 space-y-4">
        <h2 class="text-lg font-semibold text-navy">Add someone</h2>
        <form class="grid gap-3 sm:grid-cols-4 items-end" @submit.prevent="addUser">
          <label class="block">
            <span class="block text-sm font-medium text-ink mb-1">Username</span>
            <input
              v-model="form.username"
              type="text"
              maxlength="80"
              placeholder="clerk5"
              autocomplete="off"
              class="w-full min-h-11 rounded-lg border border-border-strong bg-surface text-ink px-3 py-2 lowercase"
            />
          </label>
          <label class="block">
            <span class="block text-sm font-medium text-ink mb-1">Role</span>
            <select
              v-model="form.role"
              class="w-full min-h-11 rounded-lg border border-border-strong bg-surface text-ink px-3 py-2"
            >
              <option v-for="role in availableRoles" :key="role" :value="role">{{ role }}</option>
            </select>
          </label>
          <label class="block">
            <span class="block text-sm font-medium text-ink mb-1">Initial password</span>
            <input
              v-model="form.password"
              type="password"
              autocomplete="new-password"
              :placeholder="`At least ${MIN_PASSWORD_LENGTH} characters`"
              class="w-full min-h-11 rounded-lg border border-border-strong bg-surface text-ink px-3 py-2"
            />
          </label>
          <button
            type="submit"
            :disabled="!formValid || saving"
            class="min-h-11 rounded-lg bg-brand-green px-4 font-semibold text-navy disabled:bg-sunken disabled:text-ink-subtle disabled:cursor-not-allowed"
          >
            {{ saving ? 'Adding…' : 'Add user' }}
          </button>
        </form>
      </div>
    </template>
  </div>
</template>
