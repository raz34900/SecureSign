<script setup>
// One place where a level becomes a colour. Three separate systems for this had grown up
// across the views, all using the same tokens, all free to drift apart.
const THEMES = {
  good: 'border-valid-border bg-valid-surface text-valid',
  warning: 'border-warning-border bg-warning-surface text-warning',
  error: 'border-danger-border bg-danger-surface text-danger',
}

defineProps({
  level: { type: String, default: 'error' },
  title: { type: String, default: '' },
})
</script>

<template>
  <div class="rounded-lg border px-4 py-3 text-sm space-y-1" :class="THEMES[level] ?? THEMES.error">
    <p v-if="title" class="font-medium">{{ title }}</p>
    <slot />
  </div>
</template>
