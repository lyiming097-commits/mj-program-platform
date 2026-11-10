<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

const props = withDefaults(defineProps<{ inline?: boolean; label?: string }>(), { label: '调整侧栏宽度' })
const handle = ref<HTMLElement | null>(null)
const available = ref(window.innerWidth)
const minimum = computed(() => Math.min(props.inline ? 300 : 460, available.value))
const width = ref(0)
let preferredWidth = 0
let panel: HTMLElement | null = null
let originalStyle: { width: string; maxWidth: string; position: string } | undefined
let drag: { pointer: number; x: number; width: number } | null = null

function applyWidth() {
  width.value = Math.round(Math.max(minimum.value, Math.min(available.value, preferredWidth)))
  if (panel) panel.style.width = `${width.value}px`
}

function measureAvailable() {
  available.value = props.inline ? panel?.parentElement?.clientWidth || window.innerWidth : window.innerWidth
  applyWidth()
}

function resizeTo(nextWidth: number) {
  preferredWidth = Math.max(minimum.value, Math.min(available.value, nextWidth))
  applyWidth()
}

function start(event: PointerEvent) {
  if (!panel || event.button !== 0 || drag) return
  handle.value?.setPointerCapture(event.pointerId)
  drag = { pointer: event.pointerId, x: event.clientX, width: width.value }
}

function move(event: PointerEvent) {
  if (drag?.pointer === event.pointerId) resizeTo(drag.width + drag.x - event.clientX)
}

function stop(event: PointerEvent) {
  if (drag?.pointer === event.pointerId) drag = null
}

function resizeByKey(event: KeyboardEvent) {
  const sizes: Record<string, number> = { ArrowLeft: width.value + 32, ArrowRight: width.value - 32, Home: minimum.value, End: available.value }
  if (!Object.hasOwn(sizes, event.key)) return
  event.preventDefault()
  resizeTo(sizes[event.key]!)
}

onMounted(() => {
  const parent = handle.value?.parentElement
  panel = (props.inline ? parent : parent?.closest<HTMLElement>('[role="dialog"]') ?? parent) ?? null
  if (!panel) return
  const { width: originalWidth, maxWidth, position } = panel.style
  originalStyle = { width: originalWidth, maxWidth, position }
  preferredWidth = panel.getBoundingClientRect().width || minimum.value
  if (getComputedStyle(panel).position === 'static') panel.style.position = 'relative'
  panel.style.maxWidth = props.inline ? '100%' : '100vw'
  measureAvailable()
  window.addEventListener('resize', measureAvailable)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', measureAvailable)
  if (panel && originalStyle) Object.assign(panel.style, originalStyle)
})
</script>

<template>
  <div ref="handle" v-show="available > minimum" class="drawer-resize-handle" role="separator" tabindex="0"
    :aria-label="label" aria-orientation="vertical" :aria-valuemin="minimum" :aria-valuemax="available" :aria-valuenow="width"
    @pointerdown.stop.prevent="start" @pointermove="move" @pointerup="stop" @pointercancel="stop" @lostpointercapture="stop" @keydown="resizeByKey" />
</template>

<style scoped>
.drawer-resize-handle {
  position: absolute;
  z-index: 5;
  inset: 0 auto 0 0;
  width: 10px;
  cursor: ew-resize;
  touch-action: none;
}

.drawer-resize-handle::after {
  position: absolute;
  top: 50%;
  left: 3px;
  width: 3px;
  height: 30px;
  border-radius: 3px;
  background: #b2c1d4;
  transform: translateY(-50%);
  content: '';
}

.drawer-resize-handle:hover,
.drawer-resize-handle:focus-visible { background: #dbeafe; }
</style>
