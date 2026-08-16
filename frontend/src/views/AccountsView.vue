<script setup>
import { computed, onMounted, ref } from 'vue'
import { get, postJson, del, ApiError } from '../api.js'
import { formatDateTime } from '../format.js'

const ORG_TYPES = [
  { value: 'financial', label: 'Financial institution', hint: 'Enrols customers' },
  { value: 'subscriber', label: 'Subscriber', hint: 'Verifies only' },
  { value: 'operator', label: 'Operator', hint: 'Runs the registry' },
]

/* Mirrors ROLE_ORG_TYPES on the server, which is the authority. This only keeps the
   form from offering a combination that would be rejected. */
const ROLE_ORG_TYPES = {
  clerk: ['financial'],
  verifier: ['subscriber', 'financial'],
  org_admin: ['financial', 'subscriber'],
  engineer: ['operator'],
}

const MIN_PASSWORD_LENGTH = 12

const organisations = ref([])
const users = ref([])
const loading = ref(true)
const loadError = ref('')

const orgForm = ref({ code: '', name: '', type: 'financial' })
const orgError = ref('')
const orgNotice = ref('')
const orgSaving = ref(false)

const userForm = ref({ org_code: '', username: '', role: 'clerk', password: '' })
const userError = ref('')
const userNotice = ref('')
const userSaving = ref(false)

const activeOrganisations = computed(() => organisations.value.filter((org) => org.is_active))

const selectedOrgType = computed(
  () => organisations.value.find((org) => org.code === userForm.value.org_code)?.type,
)

const availableRoles = computed(() => {
  const type = selectedOrgType.value
  if (!type) return []
  return Object.keys(ROLE_ORG_TYPES).filter((role) => ROLE_ORG_TYPES[role].includes(type))
})

const orgFormValid = computed(
  () => /^[A-Z0-9]{2,12}$/.test(orgForm.value.code.trim().toUpperCase())
    && orgForm.value.name.trim().length >= 2,
)

const userFormValid = computed(
  () => !!userForm.value.org_code
    && /^[a-z0-9][a-z0-9._-]{2,79}$/.test(userForm.value.username.trim())
    && availableRoles.value.includes(userForm.value.role)
    && userForm.value.password.length >= MIN_PASSWORD_LENGTH,
)

async function loadAll() {
  loadError.value = ''
  try {
    const [orgs, people] = await Promise.all([get('/admin/organisations'), get('/admin/users')])
    organisations.value = orgs.organisations
    users.value = people.users
  } catch (err) {
    loadError.value = err instanceof ApiError && err.status === 404
      ? 'Account administration is internal only. Open it from the machine running SecureSign, at http://localhost:8081/accounts.'
      : err.message || 'Failed to load accounts.'
  }
}

async function createOrganisation() {
  if (!orgFormValid.value || orgSaving.value) return
  orgSaving.value = true
  orgError.value = ''
  orgNotice.value = ''
  try {
    const created = await postJson('/admin/organisations', {
      code: orgForm.value.code.trim().toUpperCase(),
      name: orgForm.value.name.trim(),
      type: orgForm.value.type,
    })
    orgNotice.value = `${created.code} - ${created.name} created.`
    orgForm.value = { code: '', name: '', type: 'financial' }
    await loadAll()
  } catch (err) {
    orgError.value = err.message || 'Failed to create the organisation.'
  } finally {
    orgSaving.value = false
  }
}

async function createUser() {
  if (!userFormValid.value || userSaving.value) return
  userSaving.value = true
  userError.value = ''
  userNotice.value = ''
  try {
    const created = await postJson('/admin/users', {
      org_code: userForm.value.org_code,
      username: userForm.value.username.trim(),
      role: userForm.value.role,
      password: userForm.value.password,
    })
    userNotice.value = `${created.username} created in ${created.org_code}. Give them the password you set; it cannot be shown again.`
    userForm.value = { org_code: '', username: '', role: 'clerk', password: '' }
    await loadAll()
  } catch (err) {
    userError.value = err.message || 'Failed to create the user.'
  } finally {
    userSaving.value = false
  }
}

async function setUserActive(row, isActive) {
  userError.value = ''
  try {
    await postJson(`/admin/users/${row.user_id}/active`, { is_active: isActive })
    await loadAll()
  } catch (err) {
    userError.value = err.message || 'Failed to change the account.'
  }
}

const resettingId = ref('')
const resetPassword = ref('')
const confirmingDeleteUser = ref('')
const confirmingDeleteOrg = ref('')

function startReset(row) {
  resettingId.value = resettingId.value === row.user_id ? '' : row.user_id
  resetPassword.value = ''
  userError.value = ''
  userNotice.value = ''
}

async function submitReset(row) {
  if (resetPassword.value.length < MIN_PASSWORD_LENGTH) return
  userError.value = ''
  try {
    await postJson(`/admin/users/${row.user_id}/password`, { password: resetPassword.value })
    userNotice.value = `${row.username}'s password was reset. They were signed out everywhere and must choose their own.`
    resettingId.value = ''
    resetPassword.value = ''
    await loadAll()
  } catch (err) {
    userError.value = err.message || 'Failed to reset the password.'
  }
}

async function removeUser(row) {
  userError.value = ''
  userNotice.value = ''
  try {
    await del(`/admin/users/${row.user_id}`)
    userNotice.value = `${row.username} was deleted.`
    await loadAll()
  } catch (err) {
    userError.value = err.message || 'Failed to delete the user.'
  } finally {
    confirmingDeleteUser.value = ''
  }
}

async function removeOrganisation(org) {
  orgError.value = ''
  orgNotice.value = ''
  try {
    await del(`/admin/organisations/${org.code}`)
    orgNotice.value = `${org.code} was deleted.`
    await loadAll()
  } catch (err) {
    orgError.value = err.message || 'Failed to delete the organisation.'
  } finally {
    confirmingDeleteOrg.value = ''
  }
}

async function setOrgActive(org, isActive) {
  orgError.value = ''
  try {
    await postJson(`/admin/organisations/${org.code}/active`, { is_active: isActive })
    await loadAll()
  } catch (err) {
    orgError.value = err.message || 'Failed to change the organisation.'
  }
}

onMounted(async () => {
  await loadAll()
  loading.value = false
})
</script>

<template>
  <div class="space-y-8">
    <div>
      <h1 class="text-2xl font-bold text-navy">Accounts</h1>
      <p class="text-sm text-ink-muted mt-1">
        Organisations subscribing to the registry and the people who sign in for them.
        Reachable only from inside the network, because creating an account is the most
        privileged thing this system does.
      </p>
    </div>

    <div v-if="loadError" class="bg-danger-surface border border-danger-border text-danger text-sm rounded-lg px-4 py-3">
      {{ loadError }}
    </div>

    <div v-else-if="loading" class="text-center text-ink-subtle py-12">Loading…</div>

    <template v-else>
      <!-- Organisations -->
      <div class="bg-surface rounded-lg shadow p-6 space-y-4">
        <h2 class="text-lg font-semibold text-navy">Organisations</h2>

        <div class="overflow-x-auto">
          <table class="min-w-full text-sm">
            <thead class="bg-navy text-ink-inverse">
              <tr>
                <th scope="col" class="px-4 py-2 text-left font-semibold">Code</th>
                <th scope="col" class="px-4 py-2 text-left font-semibold">Name</th>
                <th scope="col" class="px-4 py-2 text-left font-semibold">Type</th>
                <th scope="col" class="px-4 py-2 text-left font-semibold">Users</th>
                <th scope="col" class="px-4 py-2 text-left font-semibold">Status</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-border">
              <tr v-for="org in organisations" :key="org.code">
                <td class="px-4 py-2 font-mono font-semibold text-navy">{{ org.code }}</td>
                <td class="px-4 py-2 text-ink">{{ org.name }}</td>
                <td class="px-4 py-2 text-ink-muted capitalize">{{ org.type }}</td>
                <td class="px-4 py-2 text-ink-muted">{{ org.active_users }}</td>
                <td class="px-4 py-2">
                  <div class="flex flex-wrap gap-2">
                    <button
                      type="button"
                      class="min-h-11 rounded-lg border px-3 text-xs font-semibold"
                      :class="org.is_active
                        ? 'border-valid-border bg-valid-surface text-valid'
                        : 'border-border-strong bg-sunken text-ink-muted'"
                      @click="setOrgActive(org, !org.is_active)"
                    >
                      {{ org.is_active ? 'Active' : 'Disabled' }}
                    </button>
                    <button
                      v-if="org.type !== 'operator'"
                      type="button"
                      class="min-h-11 rounded-lg border border-danger-border bg-surface px-3 text-xs font-medium text-danger"
                      @click="confirmingDeleteOrg = confirmingDeleteOrg === org.code ? '' : org.code"
                    >
                      {{ confirmingDeleteOrg === org.code ? 'Cancel' : 'Delete' }}
                    </button>
                    <button
                      v-if="confirmingDeleteOrg === org.code"
                      type="button"
                      class="min-h-11 rounded-lg bg-danger px-3 text-xs font-semibold text-ink-inverse"
                      @click="removeOrganisation(org)"
                    >
                      Confirm delete
                    </button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <p class="text-xs text-ink-muted">
          An organisation can only be deleted while it holds nothing - no users, customers,
          references or verifications. Once it has records, disable it instead; that blocks
          sign-in without erasing what it did.
        </p>

        <p v-if="orgError" class="text-sm text-danger">{{ orgError }}</p>
        <p v-if="orgNotice" class="text-sm text-valid font-medium">{{ orgNotice }}</p>

        <form class="grid gap-3 sm:grid-cols-4 items-end" @submit.prevent="createOrganisation">
          <label class="block sm:col-span-1">
            <span class="block text-sm font-medium text-ink mb-1">Code</span>
            <input
              v-model="orgForm.code"
              type="text"
              maxlength="12"
              placeholder="NB77"
              class="w-full min-h-11 rounded-lg border border-border-strong bg-surface text-ink px-3 py-2 font-mono uppercase"
            />
          </label>
          <label class="block sm:col-span-1">
            <span class="block text-sm font-medium text-ink mb-1">Display name</span>
            <input
              v-model="orgForm.name"
              type="text"
              maxlength="120"
              placeholder="New Bank"
              class="w-full min-h-11 rounded-lg border border-border-strong bg-surface text-ink px-3 py-2"
            />
          </label>
          <label class="block sm:col-span-1">
            <span class="block text-sm font-medium text-ink mb-1">Type</span>
            <select
              v-model="orgForm.type"
              class="w-full min-h-11 rounded-lg border border-border-strong bg-surface text-ink px-3 py-2"
            >
              <option v-for="type in ORG_TYPES" :key="type.value" :value="type.value">
                {{ type.label }} - {{ type.hint }}
              </option>
            </select>
          </label>
          <button
            type="submit"
            :disabled="!orgFormValid || orgSaving"
            class="min-h-11 rounded-lg bg-brand-green px-4 font-semibold text-navy disabled:bg-sunken disabled:text-ink-subtle disabled:cursor-not-allowed"
          >
            {{ orgSaving ? 'Adding…' : 'Add organisation' }}
          </button>
        </form>
      </div>

      <!-- Users -->
      <div class="bg-surface rounded-lg shadow p-6 space-y-4">
        <h2 class="text-lg font-semibold text-navy">Users</h2>

        <div class="overflow-x-auto">
          <table class="min-w-full text-sm">
            <thead class="bg-navy text-ink-inverse">
              <tr>
                <th scope="col" class="px-4 py-2 text-left font-semibold">Organisation</th>
                <th scope="col" class="px-4 py-2 text-left font-semibold">Username</th>
                <th scope="col" class="px-4 py-2 text-left font-semibold">Role</th>
                <th scope="col" class="px-4 py-2 text-left font-semibold">Created</th>
                <th scope="col" class="px-4 py-2 text-left font-semibold">Status</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-border">
              <tr v-for="row in users" :key="row.user_id">
                <td class="px-4 py-2">
                  <span class="font-mono font-semibold text-navy">{{ row.org_code }}</span>
                  <span class="text-ink-subtle text-xs ml-2">{{ row.org_name }}</span>
                </td>
                <td class="px-4 py-2 text-ink">
                  {{ row.username }}
                  <span v-if="row.must_change_password" class="block text-2xs text-borderline font-medium">
                    password not yet set by owner
                  </span>
                </td>
                <td class="px-4 py-2 text-ink-muted">{{ row.role }}</td>
                <td class="px-4 py-2 text-ink-muted">{{ formatDateTime(row.created_at) }}</td>
                <td class="px-4 py-2">
                  <div class="flex flex-wrap gap-2">
                    <button
                      type="button"
                      class="min-h-11 rounded-lg border px-3 text-xs font-semibold"
                      :class="row.is_active
                        ? 'border-valid-border bg-valid-surface text-valid'
                        : 'border-border-strong bg-sunken text-ink-muted'"
                      @click="setUserActive(row, !row.is_active)"
                    >
                      {{ row.is_active ? 'Active' : 'Disabled' }}
                    </button>
                    <button
                      type="button"
                      class="min-h-11 rounded-lg border border-border-strong bg-surface px-3 text-xs font-medium text-ink"
                      @click="startReset(row)"
                    >
                      {{ resettingId === row.user_id ? 'Cancel' : 'Reset password' }}
                    </button>
                    <button
                      v-if="row.deletable"
                      type="button"
                      class="min-h-11 rounded-lg border border-danger-border bg-surface px-3 text-xs font-medium text-danger"
                      @click="confirmingDeleteUser = confirmingDeleteUser === row.user_id ? '' : row.user_id"
                    >
                      {{ confirmingDeleteUser === row.user_id ? 'Cancel' : 'Delete' }}
                    </button>
                    <span
                      v-else
                      class="min-h-11 inline-flex items-center px-2 text-xs text-ink-subtle"
                      title="This account has verifications or reports on record; deleting it would break the audit trail."
                    >
                      Has history
                    </span>
                    <button
                      v-if="confirmingDeleteUser === row.user_id"
                      type="button"
                      class="min-h-11 rounded-lg bg-danger px-3 text-xs font-semibold text-ink-inverse"
                      @click="removeUser(row)"
                    >
                      Confirm delete
                    </button>
                  </div>

                  <div v-if="resettingId === row.user_id" class="mt-2 flex flex-wrap gap-2 items-center">
                    <input
                      v-model="resetPassword"
                      type="password"
                      autocomplete="new-password"
                      :placeholder="`At least ${MIN_PASSWORD_LENGTH} characters`"
                      class="min-w-[14rem] min-h-11 rounded-lg border border-border-strong bg-surface text-ink px-3 py-2 text-sm"
                    />
                    <button
                      type="button"
                      :disabled="resetPassword.length < MIN_PASSWORD_LENGTH"
                      class="min-h-11 rounded-lg bg-navy px-4 text-sm font-semibold text-ink-inverse disabled:opacity-50"
                      @click="submitReset(row)"
                    >
                      Set password
                    </button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <p v-if="userError" class="text-sm text-danger">{{ userError }}</p>
        <p v-if="userNotice" class="text-sm text-valid font-medium">{{ userNotice }}</p>

        <form class="grid gap-3 sm:grid-cols-5 items-end" @submit.prevent="createUser">
          <label class="block">
            <span class="block text-sm font-medium text-ink mb-1">Organisation</span>
            <select
              v-model="userForm.org_code"
              class="w-full min-h-11 rounded-lg border border-border-strong bg-surface text-ink px-3 py-2"
            >
              <option value="" disabled>Choose…</option>
              <option v-for="org in activeOrganisations" :key="org.code" :value="org.code">
                {{ org.code }} - {{ org.name }}
              </option>
            </select>
          </label>
          <label class="block">
            <span class="block text-sm font-medium text-ink mb-1">Username</span>
            <input
              v-model="userForm.username"
              type="text"
              maxlength="80"
              placeholder="clerk9"
              autocomplete="off"
              class="w-full min-h-11 rounded-lg border border-border-strong bg-surface text-ink px-3 py-2 lowercase"
            />
          </label>
          <label class="block">
            <span class="block text-sm font-medium text-ink mb-1">Role</span>
            <select
              v-model="userForm.role"
              :disabled="!availableRoles.length"
              class="w-full min-h-11 rounded-lg border border-border-strong bg-surface text-ink px-3 py-2 disabled:bg-sunken"
            >
              <option v-for="role in availableRoles" :key="role" :value="role">{{ role }}</option>
            </select>
          </label>
          <label class="block">
            <span class="block text-sm font-medium text-ink mb-1">Initial password</span>
            <input
              v-model="userForm.password"
              type="password"
              autocomplete="new-password"
              :placeholder="`At least ${MIN_PASSWORD_LENGTH} characters`"
              class="w-full min-h-11 rounded-lg border border-border-strong bg-surface text-ink px-3 py-2"
            />
          </label>
          <button
            type="submit"
            :disabled="!userFormValid || userSaving"
            class="min-h-11 rounded-lg bg-brand-green px-4 font-semibold text-navy disabled:bg-sunken disabled:text-ink-subtle disabled:cursor-not-allowed"
          >
            {{ userSaving ? 'Adding…' : 'Add user' }}
          </button>
        </form>

        <p class="text-xs text-ink-muted">
          Choose an organisation first - the roles offered are the ones that organisation
          can hold. An engineer account exists only in the operator.
        </p>
      </div>
    </template>
  </div>
</template>
