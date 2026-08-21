<script setup>
import { noticeClass } from '../format.js'

defineProps({
  level: { type: String, default: 'error' },
  title: { type: String, default: '' },
})
</script>

<template>
  <div class="rounded-lg border px-4 py-3 text-sm space-y-1" :class="noticeClass(level)">
    <p v-if="title" class="font-medium">{{ title }}</p>
    <slot />
  </div>
</template>
