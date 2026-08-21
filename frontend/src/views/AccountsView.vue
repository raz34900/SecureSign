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

/* Both tables sit on one screen with their forms below them, so a page has to be
   short enough that the whole panel is still readable without scrolling past it. */
const PAGE_SIZE = 5

const organisations = ref([])
const orgTotal = ref(0)
const orgOffset = ref(0)
const orgSearch = ref('')
const orgTypeFilter = ref('')
/* Every organisation, for the "add user" picker only. Separate from the paged table
   because the picker must offer organisations that are not on the page being read.
   Bounded by MAX_PAGE on the server; past that this needs a search-picker rather than a
   dropdown, and it will be obvious because the list stops at 200. */
const pickerOrganisations = ref([])
const users = ref([])
const userTotal = ref(0)
const userOffset = ref(0)
const userSearch = ref('')
const userRoleFilter = ref('')
const renamingCode = ref('')
const renameValue = ref('')
const rowError = ref('')
const loading = ref(true)
const loadError = ref('')

const orgForm = ref({ code: '', name: '', type: 'financial' })
const orgError = ref('')
const orgNotice = ref('')
const orgSaving = ref(false)

const userForm = ref({ org_code: '', username: '', role: 'clerk' })
/* Shown once, after creation or a reset. Nobody can look it up again. */
const issuedPassword = ref(null)
const userError = ref('')
const userNotice = ref('')
const userSaving = ref(false)

const activeOrganisations = computed(
  () => pickerOrganisations.value.filter((org) => org.is_active),
)

const selectedOrgType = computed(
  () => pickerOrganisations.value.find((org) => org.code === userForm.value.org_code)?.type,
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
    && availableRoles.value.includes(userForm.value.role),
)

/* Which roles this account could hold, given the type of organisation it belongs to.
   Mirrors the server, which is the authority and re-checks every change. */
function rolesForOrgType(row) {
  // From the row itself. Looking it up in `organisations` broke as soon as that list
  // became a page: an account whose organisation was not on it had no type, and its
  // role picker came back empty.
  if (!row.org_type) return [row.role]
  return Object.keys(ROLE_ORG_TYPES).filter((role) => ROLE_ORG_TYPES[role].includes(row.org_type))
}

function orgQuery() {
  const params = new URLSearchParams()
  if (orgSearch.value.trim()) params.set('q', orgSearch.value.trim())
  if (orgTypeFilter.value) params.set('type', orgTypeFilter.value)
  params.set('limit', String(PAGE_SIZE))
  params.set('offset', String(orgOffset.value))
  return params.toString()
}

async function loadOrganisations() {
  const orgs = await get(`/admin/organisations?${orgQuery()}`)
  organisations.value = orgs.organisations
  orgTotal.value = orgs.total ?? orgs.organisations.length
}

async function applyOrgSearch() {
  orgOffset.value = 0
  rowError.value = ''
  try {
    await loadOrganisations()
  } catch (err) {
    rowError.value = err.message || 'Failed to search organisations.'
  }
}

async function pageOrganisations(delta) {
  orgOffset.value = Math.max(0, orgOffset.value + delta * PAGE_SIZE)
  rowError.value = ''
  try {
    await loadOrganisations()
  } catch (err) {
    rowError.value = err.message || 'Failed to load organisations.'
  }
}

function userQuery() {
  const params = new URLSearchParams()
  if (userSearch.value.trim()) params.set('q', userSearch.value.trim())
  if (userRoleFilter.value) params.set('role', userRoleFilter.value)
  params.set('limit', String(PAGE_SIZE))
  params.set('offset', String(userOffset.value))
  return params.toString()
}

async function loadUsers() {
  const people = await get(`/admin/users?${userQuery()}`)
  users.value = people.users
  userTotal.value = people.total ?? people.users.length
}

/* Searching resets to the first page. Keeping the offset across a new search lands the
   reader on an empty page of a shorter result set, which reads as "no matches". */
async function applyUserSearch() {
  userOffset.value = 0
  rowError.value = ''
  try {
    await loadUsers()
  } catch (err) {
    rowError.value = err.message || 'Failed to search accounts.'
  }
}

async function pageUsers(delta) {
  userOffset.value = Math.max(0, userOffset.value + delta * PAGE_SIZE)
  await applyUserSearchKeepingPage()
}

async function applyUserSearchKeepingPage() {
  rowError.value = ''
  try {
    await loadUsers()
  } catch (err) {
    rowError.value = err.message || 'Failed to load accounts.'
  }
}

async function startRename(org) {
  renamingCode.value = org.code
  renameValue.value = org.name
  rowError.value = ''
}

async function saveRename() {
  const code = renamingCode.value
  if (!code || renameValue.value.trim().length < 2) return
  rowError.value = ''
  try {
    await postJson(`/admin/organisations/${code}/name`, { name: renameValue.value.trim() })
    renamingCode.value = ''
    await loadAll()
  } catch (err) {
    rowError.value = err.message || 'Failed to rename the organisation.'
  }
}

async function changeRole(row, role) {
  if (!role || role === row.role) return
  rowError.value = ''
  try {
    await postJson(`/admin/users/${row.user_id}/role`, { role })
    await loadUsers()
  } catch (err) {
    rowError.value = err.message || 'Failed to change the role.'
    await loadUsers()  // put the select back to what the server actually holds
  }
}

async function loadAll() {
  loadError.value = ''
  try {
    const [orgs, picker, people] = await Promise.all([
      get(`/admin/organisations?${orgQuery()}`),
      get('/admin/organisations?limit=200'),
      get(`/admin/users?${userQuery()}`)])
    organisations.value = orgs.organisations
    orgTotal.value = orgs.total ?? orgs.organisations.length
    pickerOrganisations.value = picker.organisations
    users.value = people.users
    userTotal.value = people.total ?? people.users.length
  } catch (err) {
    // A 404 means the public entrypoint. It does not get told where the panel lives.
    loadError.value = err instanceof ApiError && err.status === 404
      ? 'Not available.'
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
    orgNotice.value = `${created.code} — ${created.name} created.`
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
    })
    userNotice.value = ''
    issuedPassword.value = { username: created.username, org_code: created.org_code,
                             password: created.initial_password }
    userForm.value = { org_code: '', username: '', role: 'clerk' }
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
const confirmingDeleteUser = ref('')
const confirmingDeleteOrg = ref('')

function startReset(row) {
  resettingId.value = resettingId.value === row.user_id ? '' : row.user_id
  userError.value = ''
  userNotice.value = ''
}

async function submitReset(row) {
  userError.value = ''
  try {
    const result = await postJson(`/admin/users/${row.user_id}/password`, {})
    userNotice.value = ''
    issuedPassword.value = { username: row.username, org_code: row.org_code,
                             password: result.initial_password }
    resettingId.value = ''
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
        <h2 class="text-lg font-semibold text-navy">
          Organisations
          <span class="ml-2 text-sm font-normal text-ink-muted">{{ orgTotal }} total</span>
        </h2>

        <div class="flex flex-wrap items-end gap-3">
          <label class="block">
            <span class="block text-xs font-medium text-ink mb-1">Search</span>
            <input
              v-model="orgSearch"
              type="search"
              placeholder="Code or name"
              class="w-64 min-h-11 rounded-lg border border-border-strong bg-surface px-3 text-sm text-ink"
              @keyup.enter="applyOrgSearch"
            />
          </label>
          <label class="block">
            <span class="block text-xs font-medium text-ink mb-1">Type</span>
            <select
              v-model="orgTypeFilter"
              class="min-h-11 rounded-lg border border-border-strong bg-surface px-3 text-sm text-ink"
              @change="applyOrgSearch"
            >
              <option value="">Any</option>
              <option v-for="type in ORG_TYPES" :key="type.value" :value="type.value">
                {{ type.label }}
              </option>
            </select>
          </label>
          <button
            type="button"
            class="min-h-11 rounded-lg border border-border-strong bg-surface px-4 text-sm font-medium text-navy"
            @click="applyOrgSearch"
          >
            Search
          </button>
          <button
            v-if="orgSearch || orgTypeFilter"
            type="button"
            class="min-h-11 px-3 text-sm text-ink-muted underline underline-offset-2"
            @click="orgSearch = ''; orgTypeFilter = ''; applyOrgSearch()"
          >
            Clear
          </button>
        </div>

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
                <td class="px-4 py-2 text-ink">
                  <!-- The code stays fixed: it is what people sign in with and what every
                       audit row records. Only the display name is editable. -->
                  <template v-if="renamingCode === org.code">
                    <input
                      v-model="renameValue"
                      type="text"
                      maxlength="120"
                      class="w-44 rounded border border-border-strong bg-surface px-2 py-1 text-sm"
                      @keyup.enter="saveRename"
                      @keyup.esc="renamingCode = ''"
                    />
                    <button type="button" class="ml-2 text-xs font-semibold text-navy underline" @click="saveRename">Save</button>
                    <button type="button" class="ml-2 text-xs text-ink-muted underline" @click="renamingCode = ''">Cancel</button>
                  </template>
                  <template v-else>
                    {{ org.name }}
                    <button
                      type="button"
                      class="ml-2 text-xs text-ink-muted underline underline-offset-2"
                      @click="startRename(org)"
                    >Rename</button>
                  </template>
                </td>
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
                    <!-- Offered only when it would succeed. A button that always fails
                         teaches the reader to distrust every other button on the page. -->
                    <button
                      v-if="org.deletable"
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

        <div v-if="orgTotal > organisations.length || orgOffset > 0"
             class="flex flex-wrap items-center justify-between gap-3 text-sm">
          <p class="text-ink-muted">
            Showing {{ organisations.length ? orgOffset + 1 : 0 }}–{{ orgOffset + organisations.length }}
            of {{ orgTotal }}
          </p>
          <div class="flex gap-2">
            <button
              type="button"
              :disabled="orgOffset === 0"
              class="min-h-11 rounded-lg border border-border-strong bg-surface px-3 font-medium text-navy disabled:text-ink-subtle"
              @click="pageOrganisations(-1)"
            >
              Previous
            </button>
            <button
              type="button"
              :disabled="orgOffset + organisations.length >= orgTotal"
              class="min-h-11 rounded-lg border border-border-strong bg-surface px-3 font-medium text-navy disabled:text-ink-subtle"
              @click="pageOrganisations(1)"
            >
              Next
            </button>
          </div>
        </div>

        <p class="text-xs text-ink-muted">
          An organisation can only be deleted while it holds nothing — no users, customers,
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
                {{ type.label }} — {{ type.hint }}
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
        <h2 class="text-lg font-semibold text-navy">
          Users
          <span class="ml-2 text-sm font-normal text-ink-muted">{{ userTotal }} total</span>
        </h2>

        <!-- Searched on the server. A filter box over a fully-downloaded list stops
             working at exactly the size that makes a filter necessary. -->
        <div class="flex flex-wrap items-end gap-3">
          <label class="block">
            <span class="block text-xs font-medium text-ink mb-1">Search</span>
            <input
              v-model="userSearch"
              type="search"
              placeholder="Username, organisation code or name"
              class="w-72 min-h-11 rounded-lg border border-border-strong bg-surface px-3 text-sm text-ink"
              @keyup.enter="applyUserSearch"
            />
          </label>
          <label class="block">
            <span class="block text-xs font-medium text-ink mb-1">Role</span>
            <select
              v-model="userRoleFilter"
              class="min-h-11 rounded-lg border border-border-strong bg-surface px-3 text-sm text-ink"
              @change="applyUserSearch"
            >
              <option value="">Any</option>
              <option v-for="role in Object.keys(ROLE_ORG_TYPES)" :key="role" :value="role">{{ role }}</option>
            </select>
          </label>
          <button
            type="button"
            class="min-h-11 rounded-lg border border-border-strong bg-surface px-4 text-sm font-medium text-navy"
            @click="applyUserSearch"
          >
            Search
          </button>
          <button
            v-if="userSearch || userRoleFilter"
            type="button"
            class="min-h-11 px-3 text-sm text-ink-muted underline underline-offset-2"
            @click="userSearch = ''; userRoleFilter = ''; applyUserSearch()"
          >
            Clear
          </button>
        </div>

        <p v-if="rowError" class="text-sm text-danger">{{ rowError }}</p>

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
                <td class="px-4 py-2">
                  <!-- Only roles valid for this organisation's type are offered. The
                       server re-checks; this just avoids proposing a rejected change. -->
                  <select
                    :value="row.role"
                    :aria-label="`Role for ${row.username}`"
                    class="rounded border border-border-strong bg-surface px-2 py-1 text-sm text-ink"
                    @change="changeRole(row, $event.target.value)"
                  >
                    <option v-for="role in rolesForOrgType(row)" :key="role" :value="role">
                      {{ role }}
                    </option>
                  </select>
                </td>
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
                    <p class="text-xs text-ink-muted">
                      A new one-time password will be generated and shown once.
                      {{ row.username }} is signed out everywhere and must choose their own.
                    </p>
                    <button
                      type="button"
                      class="min-h-11 rounded-lg bg-navy px-4 text-sm font-semibold text-ink-inverse"
                      @click="submitReset(row)"
                    >
                      Reset and show password
                    </button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <div v-if="userTotal > users.length || userOffset > 0"
             class="flex flex-wrap items-center justify-between gap-3 text-sm">
          <p class="text-ink-muted">
            Showing {{ users.length ? userOffset + 1 : 0 }}–{{ userOffset + users.length }}
            of {{ userTotal }}
          </p>
          <div class="flex gap-2">
            <button
              type="button"
              :disabled="userOffset === 0"
              class="min-h-11 rounded-lg border border-border-strong bg-surface px-3 font-medium text-navy disabled:text-ink-subtle"
              @click="pageUsers(-1)"
            >
              Previous
            </button>
            <button
              type="button"
              :disabled="userOffset + users.length >= userTotal"
              class="min-h-11 rounded-lg border border-border-strong bg-surface px-3 font-medium text-navy disabled:text-ink-subtle"
              @click="pageUsers(1)"
            >
              Next
            </button>
          </div>
        </div>

        <!-- Shown once and never retrievable: the hash is all that is stored. -->
        <div
          v-if="issuedPassword"
          class="rounded-lg border-2 border-brand-green bg-valid-surface p-4 space-y-2"
        >
          <p class="text-sm font-semibold text-ink">
            One-time password for {{ issuedPassword.username }} ({{ issuedPassword.org_code }})
          </p>
          <code class="block select-all rounded bg-surface px-3 py-2 font-mono text-lg tracking-wider text-ink">{{ issuedPassword.password }}</code>
          <p class="text-xs text-ink-muted">
            Give this to them directly. It is shown once, cannot be looked up again, and
            must be replaced by the owner before the account can do anything.
          </p>
          <button
            type="button"
            class="min-h-11 rounded-lg border border-border-strong bg-surface px-3 text-sm font-medium text-navy"
            @click="issuedPassword = null"
          >
            Done
          </button>
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
                {{ org.code }} — {{ org.name }}
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
          <button
            type="submit"
            :disabled="!userFormValid || userSaving"
            class="min-h-11 rounded-lg bg-brand-green px-4 font-semibold text-navy disabled:bg-sunken disabled:text-ink-subtle disabled:cursor-not-allowed"
          >
            {{ userSaving ? 'Adding…' : 'Add user' }}
          </button>
        </form>

        <p class="text-xs text-ink-muted">
          Choose an organisation first — the roles offered are the ones that organisation
          can hold. An engineer account exists only in the operator.
        </p>
      </div>
    </template>
  </div>
</template>
