<script setup>
import { computed, onMounted, ref } from 'vue'
import { get, postJson, del } from '../api.js'
import { formatDateTime } from '../format.js'
import { state } from '../auth.js'
import IssuedPassword from '../components/IssuedPassword.vue'
import NoticeBanner from '../components/NoticeBanner.vue'


/* Mirrors the server, which is the authority. "engineer" is absent on purpose: it
   belongs to the operator, and no institution can create one. */
const ROLES_BY_ORG_TYPE = {
  financial: ['clerk', 'verifier', 'org_admin'],
  subscriber: ['verifier', 'org_admin'],
}

// Display only. The value sent to the server is always the raw role.
const ROLE_LABELS = {
  clerk: 'Clerk',
  verifier: 'Verifier',
  org_admin: 'Org admin',
}

function roleLabel(role) {
  return ROLE_LABELS[role] ?? role
}

// A branch team is small; a page this size keeps the whole table on one screen.
const PAGE_SIZE = 10

const organisation = ref(null)
const users = ref([])
const total = ref(0)
const offset = ref(0)
const search = ref('')
const loading = ref(true)
const loadError = ref('')
const actionError = ref('')
const notice = ref('')

const form = ref({ username: '', role: '' })
/* Shown once, after creation or a reset. Nobody can look it up again. */
const issuedPassword = ref(null)
const saving = ref(false)

const resettingId = ref('')
const confirmingDeleteId = ref('')

const availableRoles = computed(() => ROLES_BY_ORG_TYPE[organisation.value?.type] ?? [])

const filtered = computed(() => !!search.value.trim())
const rangeStart = computed(() => (users.value.length ? offset.value + 1 : 0))
const rangeEnd = computed(() => offset.value + users.value.length)

const formValid = computed(
  () => /^[a-z0-9][a-z0-9._-]{2,79}$/.test(form.value.username.trim())
    && availableRoles.value.includes(form.value.role)
,
)

function query() {
  const params = new URLSearchParams()
  if (search.value.trim()) params.set('q', search.value.trim())
  params.set('limit', String(PAGE_SIZE))
  params.set('offset', String(offset.value))
  return params.toString()
}

async function loadUsers() {
  try {
    const body = await get(`/org/users?${query()}`)
    organisation.value = body.organisation
    users.value = body.users
    total.value = body.total ?? body.users.length
    if (!form.value.role) form.value.role = availableRoles.value[0] ?? ''
  } catch (err) {
    loadError.value = err.message || 'Failed to load the team.'
  }
}

/* Searching resets to the first page. Keeping the offset across a new search lands the
   reader on an empty page of a shorter result set, which reads as "no matches". */
async function applySearch() {
  offset.value = 0
  await loadUsers()
}

function clearSearch() {
  search.value = ''
  return applySearch()
}

async function page(delta) {
  offset.value = Math.max(0, offset.value + delta * PAGE_SIZE)
  await loadUsers()
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
    })
    notice.value = ''
    issuedPassword.value = { username: created.username, password: created.initial_password }
    form.value = { username: '', role: availableRoles.value[0] ?? '' }
    await loadUsers()
  } catch (err) {
    actionError.value = err.message || 'Failed to add the user.'
  } finally {
    saving.value = false
  }
}

function startReset(row) {
  resettingId.value = resettingId.value === row.user_id ? '' : row.user_id
  actionError.value = ''
  notice.value = ''
}

async function submitReset(row) {
  actionError.value = ''
  try {
    const result = await postJson(`/org/users/${row.user_id}/password`, {})
    notice.value = ''
    issuedPassword.value = { username: row.username, password: result.initial_password }
    resettingId.value = ''
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
  <div class="space-y-6">
    <header>
      <h1 class="text-xl font-semibold text-navy">Team</h1>
      <p class="mt-1 max-w-prose text-sm text-ink-muted">
        The people who sign in for
        <span class="font-medium text-ink">{{ organisation?.name || state.user?.org_name }}</span
        ><span v-if="organisation?.code || state.user?.org_code" class="tabular">
          ({{ organisation?.code || state.user?.org_code }})</span>.
        You can only see and manage your own organisation's accounts.
      </p>
    </header>

    <NoticeBanner v-if="loadError">{{ loadError }}</NoticeBanner>

    <template v-else>
      <!-- Pinned to the top of the viewport for as long as it is on screen: this password -->
      <!-- is shown once and cannot be looked up, so scrolling past it locks the account out. -->
      <div
        v-if="issuedPassword"
        class="ss-rise sticky top-0 z-30 -mx-4 border-b border-border bg-canvas px-4 py-3 sm:-mx-6 sm:px-6 lg:-mx-8 lg:px-8"
      >
        <IssuedPassword
          :username="issuedPassword.username"
          :password="issuedPassword.password"
          @done="issuedPassword = null"
        />
      </div>

      <NoticeBanner v-if="actionError">{{ actionError }}</NoticeBanner>
      <NoticeBanner v-if="notice" level="good">{{ notice }}</NoticeBanner>

      <section class="space-y-3">
        <div class="flex flex-wrap items-end justify-between gap-x-6 gap-y-3">
          <div>
            <h2 class="text-sm font-semibold text-ink">Accounts</h2>
            <p class="mt-0.5 text-xs text-ink-muted">
              <template v-if="total">
                <span class="tabular">{{ rangeStart }}–{{ rangeEnd }}</span>
                of <span class="tabular">{{ total }}</span>
                {{ filtered ? 'matching' : 'in this organisation' }}
              </template>
              <template v-else-if="!loading">No accounts {{ filtered ? 'match' : 'yet' }}</template>
            </p>
          </div>

          <div class="flex flex-wrap items-end gap-2">
            <label class="block">
              <span class="mb-1 block text-xs font-medium text-ink-muted">Search</span>
              <input
                v-model="search"
                type="search"
                placeholder="Username"
                class="min-h-11 w-56 rounded-md border border-border-strong bg-surface px-3 text-sm text-ink"
                @keyup.enter="applySearch"
              />
            </label>
            <button
              type="button"
              class="min-h-11 rounded-md border border-border-strong bg-surface px-4 text-sm font-medium text-navy hover:bg-sunken"
              @click="applySearch"
            >
              Search
            </button>
            <button
              v-if="filtered"
              type="button"
              class="min-h-11 rounded-md px-3 text-sm font-medium text-ink-muted hover:bg-sunken hover:text-navy"
              @click="clearSearch"
            >
              Clear
            </button>
          </div>
        </div>

        <div class="overflow-x-auto rounded-md border border-border bg-surface">
          <table class="min-w-full text-sm">
            <thead class="bg-sunken">
              <tr class="border-b border-border">
                <th scope="col" class="px-3 py-2 text-left text-xs font-semibold uppercase tracking-wide text-ink-muted">Username</th>
                <th scope="col" class="px-3 py-2 text-left text-xs font-semibold uppercase tracking-wide text-ink-muted">Role</th>
                <th scope="col" class="px-3 py-2 text-left text-xs font-semibold uppercase tracking-wide text-ink-muted">Added</th>
                <th scope="col" class="px-3 py-2 text-left text-xs font-semibold uppercase tracking-wide text-ink-muted">Status</th>
                <th scope="col" class="px-3 py-2 text-right text-xs font-semibold uppercase tracking-wide text-ink-muted">Actions</th>
              </tr>
            </thead>

            <!-- Placeholder rows rather than a spinner: the table keeps its shape, so -->
            <!-- nothing jumps under the pointer when the rows arrive. -->
            <tbody v-if="loading" class="divide-y divide-border">
              <tr v-for="n in 4" :key="`skeleton-${n}`">
                <td class="px-3 py-3"><span class="block h-3 w-28 rounded-sm bg-sunken" /></td>
                <td class="px-3 py-3"><span class="block h-3 w-20 rounded-sm bg-sunken" /></td>
                <td class="px-3 py-3"><span class="block h-3 w-32 rounded-sm bg-sunken" /></td>
                <td class="px-3 py-3"><span class="block h-3 w-16 rounded-sm bg-sunken" /></td>
                <td class="px-3 py-3"><span class="ml-auto block h-3 w-40 rounded-sm bg-sunken" /></td>
              </tr>
            </tbody>

            <tbody v-else-if="!users.length">
              <tr>
                <td colspan="5" class="px-3 py-12 text-center">
                  <p class="text-sm font-medium text-ink">
                    {{ filtered ? 'No one here matches that' : 'No accounts yet' }}
                  </p>
                  <p class="mx-auto mt-1 max-w-prose text-xs text-ink-muted">
                    {{ filtered
                      ? 'Only usernames in this organisation are searched.'
                      : 'Add the first colleague below. They receive a one-time password to replace.' }}
                  </p>
                  <button
                    v-if="filtered"
                    type="button"
                    class="mt-3 min-h-11 rounded-md border border-border-strong bg-surface px-4 text-sm font-medium text-navy hover:bg-sunken"
                    @click="clearSearch"
                  >
                    Clear search
                  </button>
                </td>
              </tr>
            </tbody>

            <tbody v-else class="divide-y divide-border">
              <template v-for="row in users" :key="row.user_id">
                <tr class="hover:bg-sunken">
                  <td class="px-3 py-2 text-ink">
                    {{ row.username }}
                    <span v-if="row.user_id === state.user?.user_id" class="ml-1 text-xs text-ink-subtle">(you)</span>
                    <span v-if="row.must_change_password" class="block text-2xs font-medium text-borderline">
                      password not yet set by owner
                    </span>
                  </td>
                  <td class="px-3 py-2 text-ink-muted">{{ roleLabel(row.role) }}</td>
                  <td class="px-3 py-2 whitespace-nowrap text-ink-muted tabular">{{ formatDateTime(row.created_at) }}</td>
                  <td class="px-3 py-2">
                    <!-- A dot and a word, not a coloured button: state is read, not pressed. -->
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
                        @click="setActive(row, !row.is_active)"
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
                      <!-- Offered only when it would succeed. A button that always fails
                           teaches the reader to distrust every other button on the page. -->
                      <button
                        v-if="row.deletable && row.user_id !== state.user?.user_id"
                        type="button"
                        class="min-h-11 rounded px-2 text-xs font-medium text-danger hover:bg-danger-surface"
                        @click="confirmingDeleteId = confirmingDeleteId === row.user_id ? '' : row.user_id"
                      >
                        {{ confirmingDeleteId === row.user_id ? 'Cancel' : 'Delete' }}
                      </button>
                      <button
                        v-if="confirmingDeleteId === row.user_id"
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
                  <td colspan="5" class="px-3 py-2.5">
                    <div class="flex flex-wrap items-center justify-end gap-3">
                      <p class="mr-auto max-w-prose text-xs text-ink-muted">
                        A new one-time password is generated and shown once. {{ row.username }} is
                        signed out everywhere and must choose their own before the account works again.
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

        <div v-if="total > PAGE_SIZE" class="flex items-center justify-end gap-2">
          <button
            type="button"
            :disabled="offset === 0"
            class="min-h-11 rounded-md border border-border-strong bg-surface px-3 text-sm font-medium text-navy hover:bg-sunken disabled:border-border disabled:text-ink-subtle"
            @click="page(-1)"
          >
            Previous
          </button>
          <button
            type="button"
            :disabled="rangeEnd >= total"
            class="min-h-11 rounded-md border border-border-strong bg-surface px-3 text-sm font-medium text-navy hover:bg-sunken disabled:border-border disabled:text-ink-subtle"
            @click="page(1)"
          >
            Next
          </button>
        </div>
      </section>

      <section class="space-y-3 border-t border-border pt-5">
        <h2 class="text-sm font-semibold text-ink">Add someone</h2>
        <p class="max-w-prose text-xs text-ink-muted">
          The password is generated here and shown once. Hand it over directly; they replace
          it themselves before the account can do anything.
        </p>

        <form class="flex flex-wrap items-end gap-3" @submit.prevent="addUser">
          <label class="block">
            <span class="mb-1 block text-xs font-medium text-ink-muted">Username</span>
            <input
              v-model="form.username"
              type="text"
              maxlength="80"
              placeholder="clerk5"
              autocomplete="off"
              class="min-h-11 w-48 rounded-md border border-border-strong bg-surface px-3 text-sm lowercase text-ink"
            />
          </label>
          <label class="block">
            <span class="mb-1 block text-xs font-medium text-ink-muted">Role</span>
            <select
              v-model="form.role"
              class="min-h-11 rounded-md border border-border-strong bg-surface px-3 text-sm text-ink"
            >
              <option v-for="role in availableRoles" :key="role" :value="role">
                {{ roleLabel(role) }}
              </option>
            </select>
          </label>
          <button
            type="submit"
            :disabled="!formValid || saving"
            class="min-h-11 rounded-md bg-navy px-4 text-sm font-semibold text-ink-inverse hover:bg-navy-deep disabled:cursor-not-allowed disabled:bg-sunken disabled:text-ink-subtle"
          >
            {{ saving ? 'Adding…' : 'Add user' }}
          </button>
        </form>
      </section>
    </template>
  </div>
</template>
