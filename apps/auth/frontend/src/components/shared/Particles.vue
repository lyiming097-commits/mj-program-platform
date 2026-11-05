<script setup>
const dots = Array.from({ length: 30 }, (_, i) => ({
  id: i,
  left: Math.random() * 100,
  top: Math.random() * 100,
  size: Math.random() * 2 + 1,
  delay: Math.random() * 5,
  duration: Math.random() * 4 + 3,
}));
</script>

<template>
  <div class="absolute inset-0 overflow-hidden">
    <div
      v-for="dot in dots"
      :key="dot.id"
      class="absolute rounded-full bg-cyan-400/30 animate-pulse"
      :style="{
        left: `${dot.left}%`,
        top: `${dot.top}%`,
        width: `${dot.size}px`,
        height: `${dot.size}px`,
        animationDelay: `${dot.delay}s`,
        animationDuration: `${dot.duration}s`,
      }"
    />
  </div>
</template>
