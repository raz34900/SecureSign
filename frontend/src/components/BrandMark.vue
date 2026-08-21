<script setup>
// The shield, drawn rather than shipped as the 156px JPEG the README carries. Geometry
// and colours measured off the source: four bands tapering to a point, green over navy
// down the vertical axis, and a single deeper navy arrowhead below. Custom properties so
// the mark can sit on navy as well as on paper.
defineProps({
  size: { type: Number, default: 28 },
  title: { type: String, default: '' },
})
</script>

<template>
  <svg
    :width="size"
    :height="Math.round(size * 1.29)"
    viewBox="0 0 100 129"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    :role="title ? 'img' : 'presentation'"
    :aria-hidden="title ? undefined : 'true'"
  >
    <title v-if="title">{{ title }}</title>
    <g fill="var(--mark-green, #46b32d)">
      <path d="M50 0 L4 21 H50 Z" />
      <path d="M1 27 H50 V49 H3 Z" />
      <path d="M4 55 H50 V70 H5 Z" />
      <path d="M12 76 H50 V94 H22 Z" />
    </g>
    <g fill="var(--mark-navy, #143676)">
      <path d="M50 0 L96 21 H50 Z" />
      <path d="M50 27 H99 L97 49 H50 Z" />
      <path d="M50 55 H96 L95 70 H50 Z" />
      <path d="M50 76 H88 L78 94 H50 Z" />
    </g>
    <path d="M30 101 H70 L50 129 Z" fill="var(--mark-point, #0b2a5c)" />
  </svg>
</template>
