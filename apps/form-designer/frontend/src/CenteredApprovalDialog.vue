<script setup lang="ts">
import { backdropDismiss as vBackdropDismiss } from '@platform-ui/backdrop-dismiss.js'
import { onBeforeUnmount, onMounted, ref } from 'vue'

const props = defineProps<{ label: string; suspended?: boolean }>()
const emit = defineEmits<{ close: [] }>()
const dialog = ref<HTMLDialogElement | null>(null)

function requestClose() {
  if (!props.suspended) emit('close')
}

onMounted(() => dialog.value?.showModal())
onBeforeUnmount(() => dialog.value?.close())
</script>

<template>
  <Teleport to="body">
    <dialog ref="dialog" class="oa-centered-dialog" :aria-label="label" @cancel.prevent="requestClose" @keydown.esc.stop>
      <div class="oa-centered-overlay" v-backdrop-dismiss="requestClose">
        <div class="oa-centered-panel" @click.stop>
          <slot />
        </div>
      </div>
    </dialog>
  </Teleport>
</template>

<style scoped>
.oa-centered-dialog {
  position: fixed;
  inset: 0;
  width: 100%;
  height: 100%;
  max-width: none;
  max-height: none;
  margin: 0;
  padding: 0;
  border: 0;
  background: transparent;
  color: inherit;
}

.oa-centered-dialog::backdrop { background: rgb(15 23 42 / 40%); }
.oa-centered-overlay { display: grid; place-items: center; min-height: 100%; padding: 16px; }
.oa-centered-panel { width: min(440px, 100%); }
.oa-centered-panel :deep(.employee-dialog) {
  width: 100%;
  max-height: calc(100dvh - 32px);
  border-radius: 10px;
}
</style>
