<script setup>
// Two lessons that are opposites: verification wants one signature filling the frame,
// enrolment wants the whole specimen card in one picture. Same component, so the two
// screens cannot drift apart in style.
defineProps({
  mode: { type: String, default: 'verify' },
})
</script>

<template>
  <svg
    v-if="mode === 'enrol'"
    class="capture-guide h-50 w-full"
    viewBox="0 0 340 200"
    xmlns="http://www.w3.org/2000/svg"
    role="img"
    aria-label="Photograph the whole specimen card: several signatures on a blank white page, all in one picture."
  >
    <defs>
      <path
        id="cg-sig"
        d="M 0 8 C 4 -2, 8 14, 12 5 S 18 -3, 22 7 C 25 13, 29 0, 33 6 L 39 2"
        fill="none"
        stroke="var(--color-ink)"
        stroke-width="2"
        stroke-linecap="round"
        stroke-linejoin="round"
      />
    </defs>

    <!-- ------------------------------- left: one signature cropped on its own -->
    <circle cx="82" cy="10" r="8.5" fill="var(--color-danger-surface)" stroke="var(--color-danger-border)" />
    <path
      d="M 78.5 6.5 L 85.5 13.5 M 85.5 6.5 L 78.5 13.5"
      fill="none"
      stroke="var(--color-danger)"
      stroke-width="2"
      stroke-linecap="round"
    />

    <rect
      x="24"
      y="56"
      width="116"
      height="62"
      rx="5"
      fill="var(--color-surface)"
      stroke="var(--color-danger)"
      stroke-width="2"
      stroke-dasharray="7 5"
    />
    <g transform="translate(38, 76) scale(2.2)">
      <use href="#cg-sig" />
    </g>

    <!-- --------------------------- right: the whole card, signatures stacked -->
    <circle cx="258" cy="10" r="8.5" fill="var(--color-valid-surface)" stroke="var(--color-valid-border)" />
    <path
      d="M 254 10 L 257 13.5 L 262.5 6.5"
      fill="none"
      stroke="var(--color-valid)"
      stroke-width="2"
      stroke-linecap="round"
      stroke-linejoin="round"
    />

    <rect
      x="214"
      y="28"
      width="88"
      height="116"
      rx="4"
      fill="var(--color-surface)"
      stroke="var(--color-border)"
    />
    <g transform="translate(238, 40)">
      <use href="#cg-sig" />
      <use href="#cg-sig" y="24" />
      <use href="#cg-sig" y="48" />
      <use href="#cg-sig" y="72" />
    </g>

    <rect
      class="capture-guide__spread"
      x="208"
      y="23"
      width="100"
      height="126"
      rx="5"
      fill="none"
      stroke="var(--color-valid)"
      stroke-width="2"
      stroke-dasharray="7 5"
      vector-effect="non-scaling-stroke"
    />

    <!-- ----------------------------------------------------------- labels -->
    <text
      x="82"
      y="168"
      text-anchor="middle"
      font-size="11"
      font-weight="600"
      fill="var(--color-ink-muted)"
    >
      Not one signature alone
    </text>
    <text
      x="258"
      y="168"
      text-anchor="middle"
      font-size="11"
      font-weight="600"
      fill="var(--color-ink-muted)"
    >
      <tspan x="258">The whole card on a blank page,</tspan>
      <tspan x="258" dy="15">every signature in the picture</tspan>
    </text>
  </svg>

  <svg
    v-else
    class="capture-guide h-50 w-full"
    viewBox="0 0 340 200"
    xmlns="http://www.w3.org/2000/svg"
    role="img"
    aria-label="Photograph the signature on its own so it fills the picture, rather than photographing the whole page."
  >
    <!-- ------------------------------------------------ left: the whole page -->
    <circle cx="82" cy="10" r="8.5" fill="var(--color-danger-surface)" stroke="var(--color-danger-border)" />
    <path
      d="M 78.5 6.5 L 85.5 13.5 M 85.5 6.5 L 78.5 13.5"
      fill="none"
      stroke="var(--color-danger)"
      stroke-width="2"
      stroke-linecap="round"
    />

    <rect
      x="30"
      y="26"
      width="104"
      height="118"
      rx="4"
      fill="var(--color-surface)"
      stroke="var(--color-border)"
    />
    <g stroke="var(--color-border-strong)" stroke-width="2.5" stroke-linecap="round">
      <line x1="42" y1="42" x2="122" y2="42" />
      <line x1="42" y1="54" x2="122" y2="54" />
      <line x1="42" y1="66" x2="110" y2="66" />
      <line x1="42" y1="78" x2="122" y2="78" />
      <line x1="42" y1="90" x2="100" y2="90" />
    </g>
    <path
      d="M 44 128 C 52 108, 60 140, 68 121 S 80 105, 88 125 C 94 137, 102 111, 110 123 L 122 114"
      fill="none"
      stroke="var(--color-ink)"
      stroke-width="2.5"
      stroke-linecap="round"
      stroke-linejoin="round"
    />

    <rect
      class="capture-guide__frame"
      x="22"
      y="22"
      width="120"
      height="126"
      rx="5"
      fill="none"
      stroke="var(--color-danger)"
      stroke-width="2"
      stroke-dasharray="7 5"
      vector-effect="non-scaling-stroke"
    />

    <!-- ------------------------------------------ right: just the signature -->
    <circle cx="258" cy="10" r="8.5" fill="var(--color-valid-surface)" stroke="var(--color-valid-border)" />
    <path
      d="M 254 10 L 257 13.5 L 262.5 6.5"
      fill="none"
      stroke="var(--color-valid)"
      stroke-width="2"
      stroke-linecap="round"
      stroke-linejoin="round"
    />

    <rect
      x="190"
      y="42"
      width="136"
      height="88"
      rx="5"
      fill="var(--color-surface)"
      stroke="var(--color-valid)"
      stroke-width="2"
      stroke-dasharray="7 5"
    />
    <path
      d="M 202 103 C 214 60, 226 125, 238 92 S 258 54, 270 99 C 280 121, 292 71, 302 96 L 316 84"
      fill="none"
      stroke="var(--color-ink)"
      stroke-width="3.5"
      stroke-linecap="round"
      stroke-linejoin="round"
    />

    <!-- ----------------------------------------------------------- labels -->
    <text
      x="82"
      y="168"
      text-anchor="middle"
      font-size="11"
      font-weight="600"
      fill="var(--color-ink-muted)"
    >
      Not the whole page
    </text>
    <text
      x="258"
      y="168"
      text-anchor="middle"
      font-size="11"
      font-weight="600"
      fill="var(--color-ink-muted)"
    >
      <tspan x="258">Fill the frame</tspan>
      <tspan x="258" dy="15">with the signature</tspan>
    </text>
  </svg>
</template>

<style scoped>
@media (prefers-reduced-motion: no-preference) {
  .capture-guide__frame {
    transform-box: fill-box;
    transform-origin: 50% 80%;
    animation: capture-guide-tighten 7s ease-in-out infinite;
  }
  .capture-guide__spread {
    transform-box: fill-box;
    transform-origin: 50% 12%;
    animation: capture-guide-spread 7s ease-in-out infinite;
  }
}

@keyframes capture-guide-tighten {
  0%,
  18% {
    transform: scale(1, 1);
  }
  55%,
  78% {
    transform: scale(0.74, 0.27);
  }
  100% {
    transform: scale(1, 1);
  }
}

/* The inverse story: the frame starts cropped around the top signature and grows until
   the whole card is inside it. */
@keyframes capture-guide-spread {
  0%,
  18% {
    transform: scale(0.6, 0.22);
  }
  55%,
  78% {
    transform: scale(1, 1);
  }
  100% {
    transform: scale(0.6, 0.22);
  }
}
</style>
