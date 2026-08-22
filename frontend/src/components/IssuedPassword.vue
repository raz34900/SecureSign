<script setup>
// Shown once. Nothing can look this up again, so if the panel does not render it the
// account is unusable and the only way out is another reset.
defineProps({
  username: { type: String, required: true },
  password: { type: String, required: true },
  orgCode: { type: String, default: '' },
})
defineEmits(['done'])
</script>

<template>
  <div class="rounded-lg border-2 border-brand-green bg-valid-surface p-4 space-y-2 lg:max-w-2xl">
    <p class="text-sm font-semibold text-ink">
      One-time password for {{ username }}<template v-if="orgCode"> ({{ orgCode }})</template>
    </p>
    <code class="block select-all rounded bg-surface px-3 py-2 font-mono text-lg tracking-wider text-ink">{{ password }}</code>
    <p class="text-xs text-ink-muted">
      Give this to them directly. It is shown once, cannot be looked up again, and must be
      replaced by the owner before the account can do anything.
    </p>
    <button
      type="button"
      class="min-h-11 rounded-lg border border-border-strong bg-surface px-3 text-sm font-medium text-navy"
      @click="$emit('done')"
    >
      Done
    </button>
  </div>
</template>
