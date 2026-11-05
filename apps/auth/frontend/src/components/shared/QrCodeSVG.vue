<script setup>
const size = 25;
const cellSize = 6;
const padding = 6;
const totalSize = size * cellSize + padding * 2;

function buildModules() {
  const m = [];
  for (let r = 0; r < size; r++) {
    m[r] = [];
    for (let c = 0; c < size; c++) {
      const inFinderTL = r < 7 && c < 7;
      const inFinderTR = r < 7 && c >= size - 7;
      const inFinderBL = r >= size - 7 && c < 7;

      if (inFinderTL || inFinderTR || inFinderBL) {
        const lr = inFinderTL ? r : inFinderTR ? r : r - (size - 7);
        const lc = inFinderTL ? c : inFinderTR ? c - (size - 7) : c;
        m[r][c] =
          lr === 0 ||
          lr === 6 ||
          lc === 0 ||
          lc === 6 ||
          (lr >= 2 && lr <= 4 && lc >= 2 && lc <= 4);
      } else {
        m[r][c] = Math.random() > 0.5;
      }
    }
  }
  return m;
}

const modules = buildModules();
</script>

<template>
  <svg width="100%" height="100%" :viewBox="`0 0 ${totalSize} ${totalSize}`">
    <template v-for="(row, r) in modules" :key="`row-${r}`">
      <rect
        v-for="(cell, c) in row"
        v-if="cell"
        :key="`${r}-${c}`"
        :x="padding + c * cellSize"
        :y="padding + r * cellSize"
        :width="cellSize"
        :height="cellSize"
        rx="1"
        fill="#0f172a"
      />
    </template>
    <circle :cx="totalSize / 2" :cy="totalSize / 2" r="7" fill="#06b6d4" />
  </svg>
</template>
