<script setup lang="ts">
import { PlatformDetailDrawer } from '@platform-ui'
import DrawerResizeHandle from './DrawerResizeHandle.vue'

defineOptions({ inheritAttrs: false })
defineProps<{ open?: boolean; suspended?: boolean; labelledBy?: string; resizeLabel?: string }>()
const emit = defineEmits<{ close: [] }>()
</script>

<template>
  <PlatformDetailDrawer v-bind="$attrs" :open="open" :suspended="suspended" :labelled-by="labelledBy" @close="emit('close')">
    <DrawerResizeHandle v-if="open" :label="resizeLabel" />
    <slot />
  </PlatformDetailDrawer>
</template>
