<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { get, postJson, del, ApiError } from '../api.js'
import { formatDateTime } from '../format.js'
import IssuedPassword from '../components/IssuedPassword.vue'
import NoticeBanner from '../components/NoticeBanner.vue'

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

// Display only. The value sent and compared is always the raw role from the server.
const ROLE_LABELS = {
  clerk: 'Clerk',
  verifier: 'Verifier',
  org_admin: 'Org admin',
  engineer: 'Engineer',
}

function roleLabel(role) {
  return ROLE_LABELS[role] ?? role
}

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

// A role left over from the previous organisation would be rejected by the server, and
// the picker no longer offers it, so the form would sit invalid with nothing to fix.
watch(availableRoles, (roles) => {
  if (roles.length && !roles.includes(userForm.value.role)) userForm.value.role = roles[0]
})

const orgFiltered = computed(() => !!(orgSearch.value.trim() || orgTypeFilter.value))
const userFiltered = computed(() => !!(userSearch.value.trim() || userRoleFilter.value))

// A page of rows that does not say how many exist is a page that hides data.
const orgRangeStart = computed(() => (organisations.value.length ? orgOffset.value + 1 : 0))
const orgRangeEnd = computed(() => orgOffset.value + organisations.value.length)
const userRangeStart = computed(() => (users.value.length ? userOffset.value + 1 : 0))
const userRangeEnd = computed(() => userOffset.value + users.value.length)

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

function clearOrgFilters() {
  orgSearch.value = ''
  orgTypeFilter.value = ''
  return applyOrgSearch()
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

function clearUserFilters() {
  userSearch.value = ''
  userRoleFilter.value = ''
  return applyUserSearch()
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
  <div class="space-y-6">
    <header>
      <h1 class="text-xl font-semibold text-navy">Accounts</h1>
      <p class="mt-1 max-w-prose text-sm text-ink-muted">
        Organisations subscribing to the registry and the people who sign in for them.
        Reachable only from inside the network, because creating an account is the most
        privileged thing this system does.
      </p>
    </header>

    <NoticeBanner v-if="loadError">{{ loadError }}</NoticeBanner>

    <template v-else>
      <!-- Pinned to the top of the viewport for as long as it is on screen: this password -->
      <!-- is shown once and cannot be looked up, so a clerk who scrolls past it has -->
      <!-- locked the account out. -->
      <div
        v-if="issuedPassword"
        class="ss-rise sticky top-0 z-30 -mx-4 border-b border-border bg-canvas px-4 py-3 sm:-mx-6 sm:px-6 lg:-mx-8 lg:px-8"
      >
        <IssuedPassword
          :username="issuedPassword.username"
          :password="issuedPassword.password"
          :org-code="issuedPassword.org_code"
          @done="issuedPassword = null"
        />
      </div>

      <NoticeBanner v-if="rowError">{{ rowError }}</NoticeBanner>

      <!-- Organisations -->
      <section class="space-y-3">
        <div class="flex flex-wrap items-end justify-between gap-x-6 gap-y-3">
          <div>
            <h2 class="text-sm font-semibold text-ink">Organisations</h2>
            <p class="mt-0.5 text-xs text-ink-muted">
              <template v-if="orgTotal">
                <span class="tabular">{{ orgRangeStart }}–{{ orgRangeEnd }}</span>
                of <span class="tabular">{{ orgTotal }}</span>
                {{ orgFiltered ? 'matching' : 'registered' }}
              </template>
              <template v-else-if="!loading">None {{ orgFiltered ? 'matching' : 'registered' }}</template>
            </p>
          </div>

          <div class="flex flex-wrap items-end gap-2">
            <label class="block">
              <span class="mb-1 block text-xs font-medium text-ink-muted">Search</span>
              <input
                v-model="orgSearch"
                type="search"
                placeholder="Code or name"
                class="min-h-11 w-56 rounded-md border border-border-strong bg-surface px-3 text-sm text-ink"
                @keyup.enter="applyOrgSearch"
              />
            </label>
            <label class="block">
              <span class="mb-1 block text-xs font-medium text-ink-muted">Type</span>
              <select
                v-model="orgTypeFilter"
                class="min-h-11 rounded-md border border-border-strong bg-surface px-3 text-sm text-ink"
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
              class="min-h-11 rounded-md border border-border-strong bg-surface px-4 text-sm font-medium text-navy hover:bg-sunken"
              @click="applyOrgSearch"
            >
              Search
            </button>
            <button
              v-if="orgFiltered"
              type="button"
              class="min-h-11 rounded-md px-3 text-sm font-medium text-ink-muted hover:bg-sunken hover:text-navy"
              @click="clearOrgFilters"
            >
              Clear
            </button>
          </div>
        </div>

        <div class="overflow-x-auto rounded-md border border-border bg-surface">
          <table class="min-w-full text-sm">
            <thead class="bg-sunken">
              <tr class="border-b border-border">
                <th scope="col" class="px-3 py-2 text-left text-xs font-semibold uppercase tracking-wide text-ink-muted">Code</th>
                <th scope="col" class="px-3 py-2 text-left text-xs font-semibold uppercase tracking-wide text-ink-muted">Name</th>
                <th scope="col" class="px-3 py-2 text-left text-xs font-semibold uppercase tracking-wide text-ink-muted">Type</th>
                <th scope="col" class="px-3 py-2 text-right text-xs font-semibold uppercase tracking-wide text-ink-muted">Users</th>
                <th scope="col" class="px-3 py-2 text-left text-xs font-semibold uppercase tracking-wide text-ink-muted">Status</th>
                <th scope="col" class="px-3 py-2 text-right text-xs font-semibold uppercase tracking-wide text-ink-muted">Actions</th>
              </tr>
            </thead>

            <!-- Placeholder rows rather than a spinner: the table keeps its shape, so -->
            <!-- nothing jumps under the pointer when the rows arrive. -->
            <tbody v-if="loading" class="divide-y divide-border">
              <tr v-for="n in 3" :key="`org-skeleton-${n}`">
                <td class="px-3 py-3"><span class="block h-3 w-12 rounded-sm bg-sunken" /></td>
                <td class="px-3 py-3"><span class="block h-3 w-44 rounded-sm bg-sunken" /></td>
                <td class="px-3 py-3"><span class="block h-3 w-20 rounded-sm bg-sunken" /></td>
                <td class="px-3 py-3"><span class="ml-auto block h-3 w-6 rounded-sm bg-sunken" /></td>
                <td class="px-3 py-3"><span class="block h-3 w-16 rounded-sm bg-sunken" /></td>
                <td class="px-3 py-3"><span class="ml-auto block h-3 w-28 rounded-sm bg-sunken" /></td>
              </tr>
            </tbody>

            <tbody v-else-if="!organisations.length">
              <tr>
                <td colspan="6" class="px-3 py-12 text-center">
                  <p class="text-sm font-medium text-ink">
                    {{ orgFiltered ? 'Nothing matches this filter' : 'No organisations yet' }}
                  </p>
                  <p class="mx-auto mt-1 max-w-prose text-xs text-ink-muted">
                    {{ orgFiltered
                      ? 'Codes are matched whole or in part, and so are display names.'
                      : 'The registry starts with the institution that runs it. Add the first one below.' }}
                  </p>
                  <button
                    v-if="orgFiltered"
                    type="button"
                    class="mt-3 min-h-11 rounded-md border border-border-strong bg-surface px-4 text-sm font-medium text-navy hover:bg-sunken"
                    @click="clearOrgFilters"
                  >
                    Clear filters
                  </button>
                </td>
              </tr>
            </tbody>

            <tbody v-else class="divide-y divide-border">
              <tr v-for="org in organisations" :key="org.code" class="hover:bg-sunken">
                <td class="px-3 py-2 font-mono font-semibold text-navy tabular">{{ org.code }}</td>
                <td class="px-3 py-2 text-ink">
                  <!-- The code stays fixed: it is what people sign in with and what every
                       audit row records. Only the display name is editable. -->
                  <template v-if="renamingCode === org.code">
                    <span class="flex flex-wrap items-center gap-2">
                      <input
                        v-model="renameValue"
                        type="text"
                        maxlength="120"
                        :aria-label="`Display name for ${org.code}`"
                        class="min-h-11 w-52 rounded-md border border-border-strong bg-surface px-2 text-sm"
                        @keyup.enter="saveRename"
                        @keyup.esc="renamingCode = ''"
                      />
                      <button type="button" class="min-h-11 rounded px-2 text-xs font-semibold text-navy hover:bg-sunken" @click="saveRename">Save</button>
                      <button type="button" class="min-h-11 rounded px-2 text-xs font-medium text-ink-muted hover:bg-sunken" @click="renamingCode = ''">Cancel</button>
                    </span>
                  </template>
                  <template v-else>
                    <span class="flex items-center gap-2">
                      <span>{{ org.name }}</span>
                      <button
                        type="button"
                        class="min-h-11 rounded px-2 text-xs font-medium text-ink-subtle hover:bg-sunken hover:text-navy"
                        @click="startRename(org)"
                      >Rename</button>
                    </span>
                  </template>
                </td>
                <td class="px-3 py-2 capitalize text-ink-muted">{{ org.type }}</td>
                <td class="px-3 py-2 text-right text-ink tabular">{{ org.active_users }}</td>
                <td class="px-3 py-2">
                  <!-- A dot and a word, not a coloured button: state is read, not pressed. -->
                  <span class="flex items-center gap-2 whitespace-nowrap">
                    <span
                      class="h-1.5 w-1.5 shrink-0 rounded-full"
                      :class="org.is_active ? 'bg-brand-green' : 'bg-ink-subtle'"
                    />
                    <span :class="org.is_active ? 'text-ink' : 'text-ink-muted'">
                      {{ org.is_active ? 'Active' : 'Disabled' }}
                    </span>
                  </span>
                </td>
                <td class="px-3 py-1.5">
                  <div class="flex flex-wrap items-center justify-end gap-1">
                    <button
                      type="button"
                      class="min-h-11 rounded px-2 text-xs font-medium text-ink-muted hover:bg-sunken hover:text-navy"
                      @click="setOrgActive(org, !org.is_active)"
                    >
                      {{ org.is_active ? 'Disable' : 'Enable' }}
                    </button>
                    <!-- Offered only when it would succeed. A button that always fails
                         teaches the reader to distrust every other button on the page. -->
                    <button
                      v-if="org.deletable"
                      type="button"
                      class="min-h-11 rounded px-2 text-xs font-medium text-danger hover:bg-danger-surface"
                      @click="confirmingDeleteOrg = confirmingDeleteOrg === org.code ? '' : org.code"
                    >
                      {{ confirmingDeleteOrg === org.code ? 'Cancel' : 'Delete' }}
                    </button>
                    <button
                      v-if="confirmingDeleteOrg === org.code"
                      type="button"
                      class="min-h-11 rounded-md bg-danger px-3 text-xs font-semibold text-ink-inverse"
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

        <div v-if="orgTotal > PAGE_SIZE" class="flex items-center justify-end gap-2">
          <button
            type="button"
            :disabled="orgOffset === 0"
            class="min-h-11 rounded-md border border-border-strong bg-surface px-3 text-sm font-medium text-navy hover:bg-sunken disabled:border-border disabled:text-ink-subtle"
            @click="pageOrganisations(-1)"
          >
            Previous
          </button>
          <button
            type="button"
            :disabled="orgRangeEnd >= orgTotal"
            class="min-h-11 rounded-md border border-border-strong bg-surface px-3 text-sm font-medium text-navy hover:bg-sunken disabled:border-border disabled:text-ink-subtle"
            @click="pageOrganisations(1)"
          >
            Next
          </button>
        </div>
      </section>

      <!-- Add an organisation -->
      <section class="space-y-3 border-t border-border pt-5">
        <h2 class="text-sm font-semibold text-ink">Add an organisation</h2>

        <NoticeBanner v-if="orgError">{{ orgError }}</NoticeBanner>
        <NoticeBanner v-if="orgNotice" level="good">{{ orgNotice }}</NoticeBanner>

        <form class="flex flex-wrap items-end gap-3" @submit.prevent="createOrganisation">
          <label class="block">
            <span class="mb-1 block text-xs font-medium text-ink-muted">Code</span>
            <input
              v-model="orgForm.code"
              type="text"
              maxlength="12"
              placeholder="NB77"
              class="min-h-11 w-32 rounded-md border border-border-strong bg-surface px-3 font-mono text-sm uppercase text-ink tabular"
            />
          </label>
          <label class="block min-w-56 flex-1">
            <span class="mb-1 block text-xs font-medium text-ink-muted">Display name</span>
            <input
              v-model="orgForm.name"
              type="text"
              maxlength="120"
              placeholder="New Bank"
              class="min-h-11 w-full rounded-md border border-border-strong bg-surface px-3 text-sm text-ink"
            />
          </label>
          <label class="block">
            <span class="mb-1 block text-xs font-medium text-ink-muted">Type</span>
            <select
              v-model="orgForm.type"
              class="min-h-11 rounded-md border border-border-strong bg-surface px-3 text-sm text-ink"
            >
              <option v-for="type in ORG_TYPES" :key="type.value" :value="type.value">
                {{ type.label }} — {{ type.hint }}
              </option>
            </select>
          </label>
          <button
            type="submit"
            :disabled="!orgFormValid || orgSaving"
            class="min-h-11 rounded-md bg-navy px-4 text-sm font-semibold text-ink-inverse hover:bg-navy-deep disabled:cursor-not-allowed disabled:bg-sunken disabled:text-ink-subtle"
          >
            {{ orgSaving ? 'Adding…' : 'Add organisation' }}
          </button>
        </form>
      </section>

      <!-- Users -->
      <section class="space-y-3 border-t border-border pt-6">
        <div class="flex flex-wrap items-end justify-between gap-x-6 gap-y-3">
          <div>
            <h2 class="text-sm font-semibold text-ink">Users</h2>
            <p class="mt-0.5 text-xs text-ink-muted">
              <template v-if="userTotal">
                <span class="tabular">{{ userRangeStart }}–{{ userRangeEnd }}</span>
                of <span class="tabular">{{ userTotal }}</span>
                {{ userFiltered ? 'matching' : 'across every organisation' }}
              </template>
              <template v-else-if="!loading">No accounts {{ userFiltered ? 'match' : 'yet' }}</template>
            </p>
          </div>

          <!-- Searched on the server. A filter box over a fully-downloaded list stops
               working at exactly the size that makes a filter necessary. -->
          <div class="flex flex-wrap items-end gap-2">
            <label class="block">
              <span class="mb-1 block text-xs font-medium text-ink-muted">Search</span>
              <input
                v-model="userSearch"
                type="search"
                placeholder="Username, organisation code or name"
                class="min-h-11 w-64 rounded-md border border-border-strong bg-surface px-3 text-sm text-ink"
                @keyup.enter="applyUserSearch"
              />
            </label>
            <label class="block">
              <span class="mb-1 block text-xs font-medium text-ink-muted">Role</span>
              <select
                v-model="userRoleFilter"
                class="min-h-11 rounded-md border border-border-strong bg-surface px-3 text-sm text-ink"
                @change="applyUserSearch"
              >
                <option value="">Any</option>
                <option v-for="role in Object.keys(ROLE_ORG_TYPES)" :key="role" :value="role">
                  {{ roleLabel(role) }}
                </option>
              </select>
            </label>
            <button
              type="button"
              class="min-h-11 rounded-md border border-border-strong bg-surface px-4 text-sm font-medium text-navy hover:bg-sunken"
              @click="applyUserSearch"
            >
              Search
            </button>
            <button
              v-if="userFiltered"
              type="button"
              class="min-h-11 rounded-md px-3 text-sm font-medium text-ink-muted hover:bg-sunken hover:text-navy"
              @click="clearUserFilters"
            >
              Clear
            </button>
          </div>
        </div>

        <div class="overflow-x-auto rounded-md border border-border bg-surface">
          <table class="min-w-full text-sm">
            <thead class="bg-sunken">
              <tr class="border-b border-border">
                <th scope="col" class="px-3 py-2 text-left text-xs font-semibold uppercase tracking-wide text-ink-muted">Organisation</th>
                <th scope="col" class="px-3 py-2 text-left text-xs font-semibold uppercase tracking-wide text-ink-muted">Username</th>
                <th scope="col" class="px-3 py-2 text-left text-xs font-semibold uppercase tracking-wide text-ink-muted">Role</th>
                <th scope="col" class="px-3 py-2 text-left text-xs font-semibold uppercase tracking-wide text-ink-muted">Created</th>
                <th scope="col" class="px-3 py-2 text-left text-xs font-semibold uppercase tracking-wide text-ink-muted">Status</th>
                <th scope="col" class="px-3 py-2 text-right text-xs font-semibold uppercase tracking-wide text-ink-muted">Actions</th>
              </tr>
            </thead>

            <tbody v-if="loading" class="divide-y divide-border">
              <tr v-for="n in 3" :key="`user-skeleton-${n}`">
                <td class="px-3 py-3"><span class="block h-3 w-32 rounded-sm bg-sunken" /></td>
                <td class="px-3 py-3"><span class="block h-3 w-24 rounded-sm bg-sunken" /></td>
                <td class="px-3 py-3"><span class="block h-3 w-20 rounded-sm bg-sunken" /></td>
                <td class="px-3 py-3"><span class="block h-3 w-28 rounded-sm bg-sunken" /></td>
                <td class="px-3 py-3"><span class="block h-3 w-16 rounded-sm bg-sunken" /></td>
                <td class="px-3 py-3"><span class="ml-auto block h-3 w-36 rounded-sm bg-sunken" /></td>
              </tr>
            </tbody>

            <tbody v-else-if="!users.length">
              <tr>
                <td colspan="6" class="px-3 py-12 text-center">
                  <p class="text-sm font-medium text-ink">
                    {{ userFiltered ? 'No account matches this filter' : 'No accounts yet' }}
                  </p>
                  <p class="mx-auto mt-1 max-w-prose text-xs text-ink-muted">
                    {{ userFiltered
                      ? 'Usernames, organisation codes and organisation names are all searched.'
                      : 'Every sign-in belongs to one organisation. Add the first account below.' }}
                  </p>
                  <button
                    v-if="userFiltered"
                    type="button"
                    class="mt-3 min-h-11 rounded-md border border-border-strong bg-surface px-4 text-sm font-medium text-navy hover:bg-sunken"
                    @click="clearUserFilters"
                  >
                    Clear filters
                  </button>
                </td>
              </tr>
            </tbody>

            <tbody v-else class="divide-y divide-border">
              <template v-for="row in users" :key="row.user_id">
                <tr class="hover:bg-sunken">
                  <td class="px-3 py-2 whitespace-nowrap">
                    <span class="font-mono font-semibold text-navy tabular">{{ row.org_code }}</span>
                    <span class="ml-2 text-xs text-ink-subtle">{{ row.org_name }}</span>
                  </td>
                  <td class="px-3 py-2 text-ink">
                    {{ row.username }}
                    <span v-if="row.must_change_password" class="block text-2xs font-medium text-borderline">
                      password not yet set by owner
                    </span>
                  </td>
                  <td class="px-3 py-1.5">
                    <!-- Only roles valid for this organisation's type are offered. The
                         server re-checks; this just avoids proposing a rejected change. -->
                    <select
                      :value="row.role"
                      :aria-label="`Role for ${row.username}`"
                      class="min-h-11 rounded-md border border-border-strong bg-surface px-2 text-sm text-ink"
                      @change="changeRole(row, $event.target.value)"
                    >
                      <option v-for="role in rolesForOrgType(row)" :key="role" :value="role">
                        {{ roleLabel(role) }}
                      </option>
                    </select>
                  </td>
                  <td class="px-3 py-2 whitespace-nowrap text-ink-muted tabular">{{ formatDateTime(row.created_at) }}</td>
                  <td class="px-3 py-2">
                    <span class="flex items-center gap-2 whitespace-nowrap">
                      <span
                        class="h-1.5 w-1.5 shrink-0 rounded-full"
                        :class="row.is_active ? 'bg-brand-green' : 'bg-ink-subtle'"
                      />
                      <span :class="row.is_active ? 'text-ink' : 'text-ink-muted'">
                        {{ row.is_active ? 'Active' : 'Disabled' }}
                      </span>
                    </span>
                  </td>
                  <td class="px-3 py-1.5">
                    <div class="flex flex-wrap items-center justify-end gap-1">
                      <button
                        type="button"
                        class="min-h-11 rounded px-2 text-xs font-medium text-ink-muted hover:bg-sunken hover:text-navy"
                        @click="setUserActive(row, !row.is_active)"
                      >
                        {{ row.is_active ? 'Disable' : 'Enable' }}
                      </button>
                      <button
                        type="button"
                        class="min-h-11 rounded px-2 text-xs font-medium text-ink-muted hover:bg-sunken hover:text-navy"
                        @click="startReset(row)"
                      >
                        {{ resettingId === row.user_id ? 'Cancel' : 'Reset password' }}
                      </button>
                      <button
                        v-if="row.deletable"
                        type="button"
                        class="min-h-11 rounded px-2 text-xs font-medium text-danger hover:bg-danger-surface"
                        @click="confirmingDeleteUser = confirmingDeleteUser === row.user_id ? '' : row.user_id"
                      >
                        {{ confirmingDeleteUser === row.user_id ? 'Cancel' : 'Delete' }}
                      </button>
                      <button
                        v-if="confirmingDeleteUser === row.user_id"
                        type="button"
                        class="min-h-11 rounded-md bg-danger px-3 text-xs font-semibold text-ink-inverse"
                        @click="removeUser(row)"
                      >
                        Confirm delete
                      </button>
                    </div>
                  </td>
                </tr>

                <tr v-if="resettingId === row.user_id" class="bg-sunken">
                  <td colspan="6" class="px-3 py-2.5">
                    <div class="flex flex-wrap items-center justify-end gap-3">
                      <p class="mr-auto max-w-prose text-xs text-ink-muted">
                        A new one-time password is generated and shown once.
                        {{ row.username }} is signed out everywhere and must choose their own.
                      </p>
                      <button
                        type="button"
                        class="min-h-11 rounded-md bg-navy px-4 text-sm font-semibold text-ink-inverse hover:bg-navy-deep"
                        @click="submitReset(row)"
                      >
                        Reset and show password
                      </button>
                    </div>
                  </td>
                </tr>
              </template>
            </tbody>
          </table>
        </div>

        <div v-if="userTotal > PAGE_SIZE" class="flex items-center justify-end gap-2">
          <button
            type="button"
            :disabled="userOffset === 0"
            class="min-h-11 rounded-md border border-border-strong bg-surface px-3 text-sm font-medium text-navy hover:bg-sunken disabled:border-border disabled:text-ink-subtle"
            @click="pageUsers(-1)"
          >
            Previous
          </button>
          <button
            type="button"
            :disabled="userRangeEnd >= userTotal"
            class="min-h-11 rounded-md border border-border-strong bg-surface px-3 text-sm font-medium text-navy hover:bg-sunken disabled:border-border disabled:text-ink-subtle"
            @click="pageUsers(1)"
          >
            Next
          </button>
        </div>
      </section>

      <!-- Add a user -->
      <section class="space-y-3 border-t border-border pt-5">
        <h2 class="text-sm font-semibold text-ink">Add a user</h2>
        <p class="max-w-prose text-xs text-ink-muted">
          Choose an organisation first — the roles offered are the ones that organisation
          can hold. An engineer account exists only in the operator. The password is
          generated here and shown once.
        </p>

        <NoticeBanner v-if="userError">{{ userError }}</NoticeBanner>
        <NoticeBanner v-if="userNotice" level="good">{{ userNotice }}</NoticeBanner>

        <form class="flex flex-wrap items-end gap-3" @submit.prevent="createUser">
          <label class="block min-w-56">
            <span class="mb-1 block text-xs font-medium text-ink-muted">Organisation</span>
            <select
              v-model="userForm.org_code"
              class="min-h-11 w-full rounded-md border border-border-strong bg-surface px-3 text-sm text-ink"
            >
              <option value="" disabled>Choose…</option>
              <option v-for="org in activeOrganisations" :key="org.code" :value="org.code">
                {{ org.code }} — {{ org.name }}
              </option>
            </select>
          </label>
          <label class="block">
            <span class="mb-1 block text-xs font-medium text-ink-muted">Username</span>
            <input
              v-model="userForm.username"
              type="text"
              maxlength="80"
              placeholder="clerk9"
              autocomplete="off"
              class="min-h-11 w-48 rounded-md border border-border-strong bg-surface px-3 text-sm lowercase text-ink"
            />
          </label>
          <label v-if="availableRoles.length" class="block">
            <span class="mb-1 block text-xs font-medium text-ink-muted">Role</span>
            <select
              v-model="userForm.role"
              class="min-h-11 rounded-md border border-border-strong bg-surface px-3 text-sm text-ink"
            >
              <option v-for="role in availableRoles" :key="role" :value="role">
                {{ roleLabel(role) }}
              </option>
            </select>
          </label>
          <button
            type="submit"
            :disabled="!userFormValid || userSaving"
            class="min-h-11 rounded-md bg-navy px-4 text-sm font-semibold text-ink-inverse hover:bg-navy-deep disabled:cursor-not-allowed disabled:bg-sunken disabled:text-ink-subtle"
          >
            {{ userSaving ? 'Adding…' : 'Add user' }}
          </button>
        </form>
      </section>
    </template>
  </div>
</template>
