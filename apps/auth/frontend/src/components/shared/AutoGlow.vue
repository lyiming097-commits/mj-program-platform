<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from "vue";

const pos = ref({ x: 30, y: 30 });
let frame = 0;

const bg1 = computed(
  () => `radial-gradient(800px circle at ${pos.value.x}% ${pos.value.y}%, rgba(56,189,248,0.18), transparent 50%)`,
);
const bg2 = computed(
  () =>
    `radial-gradient(600px circle at ${100 - pos.value.x}% ${100 - pos.value.y}%, rgba(139,92,246,0.14), transparent 45%)`,
);
const bg3 = computed(
  () => `radial-gradient(400px circle at ${pos.value.y}% ${pos.value.x}%, rgba(14,165,233,0.1), transparent 50%)`,
);

onMounted(() => {
  const speed = 0.0004;
  const animate = (t) => {
    pos.value = {
      x: 50 + Math.sin(t * speed) * 30 + Math.sin(t * speed * 1.7) * 10,
      y: 50 + Math.cos(t * speed * 0.8) * 25 + Math.cos(t * speed * 1.3) * 10,
    };
    frame = requestAnimationFrame(animate);
  };
  frame = requestAnimationFrame(animate);
});

onBeforeUnmount(() => {
  cancelAnimationFrame(frame);
});
</script>

<template>
  <div class="absolute inset-0 pointer-events-none" :style="{ background: bg1 }" />
  <div class="absolute inset-0 pointer-events-none" :style="{ background: bg2 }" />
  <div class="absolute inset-0 pointer-events-none" :style="{ background: bg3 }" />
</template>
