<script setup lang="ts">
import { computed, nextTick, ref, shallowRef, useId } from 'vue'
import { previewWorkflowRun, startWorkflowRun } from './api'
import FileUploadField from './FileUploadField.vue'
import type { AuthUser, FormField, FormSchema, FormValues, WorkflowRunResult, WorkflowSchema } from './types'

defineProps<{ directory: AuthUser[] }>()
const emit = defineEmits<{ submitted: [run: WorkflowRunResult] }>()
type PreviewInput = {
  workflow: WorkflowSchema
  form: FormSchema
  values: FormValues
  recalled?: Pick<WorkflowRunResult, 'id' | 'values'>
}

const headingId = useId()
const dialog = ref<HTMLDialogElement>()
const request = shallowRef<PreviewInput>()
const verifiedVersion = ref<number>()
const submitting = ref(false)
const error = ref('')
const active = computed(() => Boolean(request.value))
const fieldPermissions = computed(() => new Map(
  (request.value?.workflow.publishedSnapshot?.applicantFieldPermissions ??
    request.value?.workflow.applicantFieldPermissions ?? []).map(item => [item.fieldId, item.permission]),
))
const fields = computed(() => request.value?.form.fields.filter(field =>
  field.type !== 'description' && fieldPermissions.value.get(field.id) !== 'hidden',
) ?? [])

function fieldValue(field: FormField) {
  return fieldPermissions.value.get(field.id) === 'readonly'
    ? field.defaultValue
    : request.value?.values[field.id]
}

function displayValue(field: FormField, directory: AuthUser[]) {
  const value = fieldValue(field)
  if (Array.isArray(value)) return value.filter(item => item !== '').join(field.type === 'dateRange' ? ' 至 ' : '、') || '—'
  if (value === undefined || value === '') return '—'
  if (field.type === 'member') return directory.find(person => person.username === value)?.displayName ?? value
  return String(value)
}

function files(field: FormField, fromOriginal: boolean) {
  const value = fieldValue(field)
  const original = request.value?.recalled?.values?.[field.id]
  return Array.isArray(value)
    ? value.filter(id => (Array.isArray(original) && original.includes(id)) === fromOriginal)
    : []
}

async function open(input: PreviewInput) {
  if (active.value || !dialog.value) return
  const snapshot = { ...input, values: JSON.parse(JSON.stringify(input.values)) as FormValues }
  verifiedVersion.value = undefined
  error.value = ''
  request.value = snapshot
  await nextTick()
  dialog.value?.showModal()
  try {
    const result = await previewWorkflowRun(input.workflow.id, { values: snapshot.values })
    if (request.value !== snapshot) return
    const version = input.workflow.publishedSnapshot?.version ?? input.workflow.publishedVersion ?? 1
    if (result.version !== version) {
      error.value = '流程已更新，请关闭当前表单并重新打开后再提交。'
      return
    }
    verifiedVersion.value = result.version
  } catch (cause) {
    if (request.value === snapshot) error.value = cause instanceof Error ? cause.message : '审批预览加载失败，请返回重试。'
  }
}

function finish() {
  dialog.value?.close()
  request.value = undefined
}

function returnToEdit() {
  if (!submitting.value) finish()
}

async function confirm() {
  const snapshot = request.value
  const expectedVersion = verifiedVersion.value
  if (!snapshot || expectedVersion === undefined || submitting.value) return
  submitting.value = true
  error.value = ''
  try {
    const run = await startWorkflowRun(snapshot.workflow.id, { values: snapshot.values, expectedVersion })
    finish()
    emit('submitted', run)
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '提交失败，请重试。'
  } finally {
    submitting.value = false
  }
}

defineExpose({ open, active })
</script>

<template>
  <Teleport to="body">
    <dialog ref="dialog" class="approval-confirm-dialog" :aria-labelledby="headingId" @cancel.prevent="returnToEdit">
      <div v-if="request" class="approval-confirm-content">
        <header class="approval-confirm-header">
          <h2 :id="headingId">提交预览</h2>
          <p>{{ request.form.name }}</p>
        </header>
        <div class="approval-confirm-body">
          <section class="approval-confirm-section" aria-label="申请内容">
            <h3>申请内容</h3>
            <dl v-if="fields.length" class="start-approval-form-grid approval-confirm-fields">
              <div v-for="field in fields" :key="field.id" :class="['start-approval-field', field.width]">
                <dt>{{ field.label }}</dt>
                <dd v-if="field.type === 'image' || field.type === 'attachment'">
                  <FileUploadField v-if="files(field, true).length" :model-value="files(field, true)"
                    :field-id="field.id" :label="field.label" :image="field.type === 'image'" :run-id="request.recalled?.id" readonly />
                  <FileUploadField v-if="files(field, false).length || !files(field, true).length" :model-value="files(field, false)"
                    :field-id="field.id" :label="field.label" :image="field.type === 'image'" readonly />
                </dd>
                <dd v-else class="approval-confirm-value">{{ displayValue(field, directory) }}</dd>
              </div>
            </dl>
            <p v-else class="approval-confirm-note">没有可显示的表单字段</p>
          </section>
        </div>
        <footer class="approval-confirm-footer">
          <p v-if="error" class="start-submit-error" role="alert">{{ error }}</p>
          <p v-else-if="verifiedVersion === undefined" class="approval-confirm-note" role="status">正在校验提交内容…</p>
          <div class="start-footer-actions">
            <button type="button" autofocus :disabled="submitting" @click="returnToEdit">返回修改</button>
            <button type="button" class="start-submit-button" :disabled="verifiedVersion === undefined || submitting" @click="confirm">
              {{ submitting ? '提交中…' : '确认提交' }}
            </button>
          </div>
        </footer>
      </div>
    </dialog>
  </Teleport>
</template>

<style scoped>
.approval-confirm-dialog {
  width: min(580px, calc(100vw - 24px));
  max-height: min(760px, calc(100dvh - 32px));
  padding: 0;
  border: 1px solid #dce4ee;
  border-radius: 10px;
  overflow: hidden;
  background: #fff;
  color: #27364b;
  box-shadow: 0 16px 42px #152a4533;
}
.approval-confirm-dialog::backdrop { background: #17273970; }
.approval-confirm-content { display: flex; flex-direction: column; max-height: inherit; }
.approval-confirm-header { padding: 17px 20px; border-bottom: 1px solid #e2e8f0; }
.approval-confirm-header h2 { margin: 0; font-size: 18px; }
.approval-confirm-header p { margin: 4px 0 0; color: #596e86; font-size: 13px; overflow-wrap: anywhere; }
.approval-confirm-body { min-height: 0; overflow: auto; padding: 14px 18px; background: #f5f7fb; }
.approval-confirm-section { min-width: 0; padding: 12px 14px; border: 1px solid #dce4ee; border-radius: 8px; background: #fff; }
.approval-confirm-section h3 { margin: 0 0 10px; font-size: 14px; }
.approval-confirm-fields { margin: 0; gap: 10px 12px; }
.approval-confirm-fields .start-approval-field { gap: 4px; }
.approval-confirm-fields dt { color: #596e86; font-size: 12px; overflow-wrap: anywhere; }
.approval-confirm-fields dd { margin: 0; min-width: 0; }
.approval-confirm-value {
  padding: 6px 9px;
  border: 1px solid #e0e7f0;
  border-radius: 5px;
  background: #f7f9fc;
  font-size: 13px;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
.approval-confirm-note { margin: 6px 0 0; color: #596e86; font-size: 12px; }
.approval-confirm-footer { display: grid; justify-items: end; gap: 8px; padding: 12px 18px; border-top: 1px solid #e2e8f0; }
.approval-confirm-footer p { justify-self: stretch; margin: 0; color: #596e86; font-size: 13px; overflow-wrap: anywhere; }
.approval-confirm-footer .start-submit-error { color: #a33131; }
</style>
