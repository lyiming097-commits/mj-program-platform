<script setup lang="ts">
import ResizableDetailDrawer from './ResizableDetailDrawer.vue'
import FileUploadField from './FileUploadField.vue'
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { FileText, Save, Send, X } from '@lucide/vue'
import ApprovalSubmitPreview from './ApprovalSubmitPreview.vue'
import { storageForUser } from './storage'
import { readApplicationDraft, saveApplicationDraft } from './applicationDrafts'
import type { ApplicationDraft } from './applicationDrafts'
import type { AuthUser, FormField, FormSchema, FormValue, FormValues, WorkflowRunResult, WorkflowSchema } from './types'
import './start-approval.css'

const props = defineProps<{
  workflow: WorkflowSchema
  form: FormSchema
  user: AuthUser
  directory: AuthUser[]
  inline?: boolean
  recalled?: Pick<WorkflowRunResult, 'id' | 'workflowVersion' | 'formSchema' | 'values'>
}>()
const emit = defineEmits<{ close: []; submitted: [run: WorkflowRunResult] }>()
const permissions = new Map((props.workflow.publishedSnapshot?.applicantFieldPermissions ?? []).map(item => [item.fieldId, item.permission]))
const fields = computed(() => props.form.fields.filter(field => permissions.get(field.id) !== 'hidden'))
const editable = (field: FormField) => permissions.get(field.id) !== 'readonly'
const version = props.workflow.publishedSnapshot?.version ?? props.workflow.publishedVersion ?? 1
const draftStorage = storageForUser(props.user.username)
const draftKey = props.recalled ? `recalled:${props.recalled.id}` : props.workflow.id
const submission = ref<InstanceType<typeof ApprovalSubmitPreview>>()
const busy = computed(() => submission.value?.active ?? false)
const uploadingFields = ref<string[]>([])
const uploading = computed(() => uploadingFields.value.length > 0)
function uploadBusy(fieldId: string, value: boolean) {
  uploadingFields.value = [...uploadingFields.value.filter(id => id !== fieldId), ...(value ? [fieldId] : [])]
}
const error = ref('')
const invalidFields = ref<string[]>([])
const draftNotice = ref('')

function initialValue(field: FormField): FormValue {
  if (field.type === 'dateRange') return field.defaultValue?.match(/\d{4}-\d{2}-\d{2}/g)?.slice(0, 2) ?? ['', '']
  if (['checkbox', 'multiSelect', 'image', 'attachment'].includes(field.type)) return []
  return field.defaultValue ?? ''
}
function defaultValues(): FormValues {
  return Object.fromEntries(fields.value.map(field => [field.id, initialValue(field)]))
}
function restoredValues(entry: Pick<ApplicationDraft, 'fields' | 'values'>): FormValues {
  const restored = defaultValues()
  for (const field of fields.value) {
    const previousField = entry.fields.find(saved => saved.id === field.id)
    if (entry.fields.length && previousField?.type !== field.type) continue
    const value = entry.values[field.id]
    if (!editable(field) || field.type === 'description') continue
    if (['checkbox', 'multiSelect', 'dateRange', 'image', 'attachment'].includes(field.type)) {
      if (Array.isArray(value) && value.every(item => typeof item === 'string')) {
        restored[field.id] = ['image', 'attachment'].includes(field.type) ? value : field.type === 'dateRange' ? [value[0] ?? '', value[1] ?? ''] : value.filter(item => field.options.includes(item))
      }
    } else if (typeof value === 'string' || (typeof value === 'number' && Number.isFinite(value))) {
      if (['select', 'radio'].includes(field.type) && value !== '' && !field.options.includes(String(value))) continue
      if (field.type === 'member' && value !== '' && !props.directory.some(person => person.username === value)) continue
      restored[field.id] = value
    }
  }
  return restored
}
const values = ref<FormValues>(props.recalled ? restoredValues({
  fields: props.recalled.formSchema?.fields ?? [],
  values: props.recalled.values ?? {},
}) : defaultValues())
if (props.recalled) {
  draftNotice.value = props.recalled.workflowVersion === version
    ? '已带入原申请内容，请确认后重新提交'
    : '已按当前表单带入可用内容，请核对变更的字段'
}
let draftReadFailed = false
try {
  const draft = readApplicationDraft(draftKey, draftStorage)
  if (draft) {
    values.value = restoredValues(draft)
    draftNotice.value = draft.version === version ? '已恢复上次保存的草稿' : '已按当前表单恢复可用的草稿内容，请补充新字段'
  }
} catch {
  draftReadFailed = true
  draftNotice.value = '无法读取本机草稿，可继续填写，暂不覆盖原记录'
}
const savedValues = ref(JSON.stringify(values.value))
const dirty = computed(() => JSON.stringify(values.value) !== savedValues.value)

function canLeave(): boolean {
  if (busy.value || uploading.value) return false
  return !dirty.value || window.confirm('有尚未保存的填写内容，确定放弃本次修改吗？')
}
function requestClose() { if (canLeave()) emit('close') }
function beforeUnload(event: BeforeUnloadEvent) {
  if (!dirty.value && !busy.value && !uploading.value) return
  event.preventDefault()
  event.returnValue = ''
}
onMounted(() => window.addEventListener('beforeunload', beforeUnload))
onBeforeUnmount(() => window.removeEventListener('beforeunload', beforeUnload))
defineExpose({ canLeave })
function saveDraft() {
  if (busy.value || uploading.value) return
  try {
    if (draftReadFailed) throw new Error('无法读取原草稿，暂不能覆盖保存')
    saveApplicationDraft(draftKey, version, values.value, fields.value, draftStorage)
    savedValues.value = JSON.stringify(values.value)
    draftNotice.value = '草稿已保存，下次进入将自动恢复本次内容'
    error.value = ''
  } catch (cause) {
    error.value = draftReadFailed && cause instanceof Error ? cause.message : '草稿保存失败，请检查浏览器存储空间后重试'
  }
}
function rangeValue(fieldId: string, index: number) {
  const value = values.value[fieldId]
  return Array.isArray(value) ? value[index] ?? '' : ''
}
function updateRange(fieldId: string, index: number, event: Event) {
  const range = [rangeValue(fieldId, 0), rangeValue(fieldId, 1)]
  range[index] = (event.target as HTMLInputElement).value
  values.value[fieldId] = range
}
function empty(value: unknown): boolean {
  if (Array.isArray(value)) return !value.some(item => !empty(item))
  return value == null || (typeof value === 'string' && !value.trim())
}
function openSubmissionPreview() {
  if (busy.value || uploading.value) return
  invalidFields.value = []
  const messages: string[] = []
  for (const field of fields.value) {
    const value = values.value[field.id]
    let message = ''
    if (field.required && field.type !== 'description' && empty(value)) message = `请填写“${field.label}”`
    if (field.type === 'dateRange' && (field.required || !empty(value))) {
      const [start, end] = [rangeValue(field.id, 0), rangeValue(field.id, 1)]
      if (!start || !end) message = `请选择完整的“${field.label}”`
      else if (start > end) message = `“${field.label}”的结束日期不能早于开始日期`
    }
    if (message) { invalidFields.value.push(field.id); messages.push(message) }
  }
  if (messages.length) {
    error.value = messages.join('；')
    document.getElementById(`application-${invalidFields.value[0]}`)?.focus()
    return
  }
  error.value = ''
  void submission.value?.open({ workflow: props.workflow, form: props.form, values: values.value, recalled: props.recalled })
}
function onSubmitted(run: WorkflowRunResult) {
  savedValues.value = JSON.stringify(values.value)
  emit('submitted', run)
}
</script>

<template>
  <component :is="inline ? 'div' : ResizableDetailDrawer" :open="inline ? undefined : true" :suspended="busy || uploading" :class="{ 'start-inline-shell': inline }" @close="requestClose">
    <section class="employee-dialog start-form-dialog" :class="{ 'start-form-inline': inline }" :role="inline ? 'region' : 'dialog'" :aria-modal="inline ? undefined : true" :aria-label="`${recalled ? '重新编辑' : '发起'}${form.name}`">
      <header class="start-approval-header">
        <span class="start-approval-icon"><FileText :size="24" /></span>
        <div class="start-approval-heading"><h2>{{ recalled ? '重新编辑' : '发起' }}{{ form.name }}</h2><p>{{ recalled ? '提交后将发起一条新的审批' : '填写申请内容后提交审批' }}</p></div>
        <button v-if="!inline" class="start-approval-close" aria-label="关闭" :disabled="busy" @click="requestClose"><X :size="20" /></button>
      </header>
      <div class="employee-dialog-body start-approval-body">
        <form id="start-approval-form" class="start-approval-card" novalidate @submit.prevent="openSubmissionPreview">
          <div class="start-approval-form-grid">
            <div v-for="field in fields" :key="field.id" :class="['start-approval-field', field.width, { invalid: invalidFields.includes(field.id) }]">
              <label :for="`application-${field.id}`"><span>{{ field.label }}<i v-if="field.required" aria-hidden="true"> *</i></span><small v-if="!editable(field)">只读</small></label>
              <p v-if="field.type === 'description'" class="start-field-description">{{ field.defaultValue || '—' }}</p>
              <textarea v-else-if="field.type === 'textarea'" :id="`application-${field.id}`" v-model="values[field.id] as string" :readonly="!editable(field) || busy" :aria-required="field.required" :aria-invalid="invalidFields.includes(field.id)" :placeholder="field.placeholder" rows="3" />
              <fieldset v-else-if="field.type === 'radio' || field.type === 'checkbox'" :id="`application-${field.id}`" class="start-choice-list" :disabled="!editable(field) || busy" :aria-label="field.label">
                <label v-for="option in field.options" :key="option"><input v-model="values[field.id]" :type="field.type === 'radio' ? 'radio' : 'checkbox'" :name="`application-${field.id}`" :value="option" />{{ option }}</label>
              </fieldset>
              <select v-else-if="field.type === 'select' || field.type === 'multiSelect'" :id="`application-${field.id}`" v-model="values[field.id]" :disabled="!editable(field) || busy" :multiple="field.type === 'multiSelect'" :aria-required="field.required" :aria-invalid="invalidFields.includes(field.id)">
                <option v-if="field.type === 'select'" value="" disabled>{{ field.placeholder || '请选择' }}</option><option v-for="option in field.options" :key="option" :value="option">{{ option }}</option>
              </select>
              <div v-else-if="field.type === 'dateRange'" class="start-date-range" role="group" :aria-label="field.label">
                <input :id="`application-${field.id}`" :value="rangeValue(field.id, 0)" type="date" :max="rangeValue(field.id, 1) || undefined" :aria-label="field.label + '开始日期'" :aria-required="field.required" :readonly="!editable(field) || busy" @input="updateRange(field.id, 0, $event)" />
                <span>至</span>
                <input :value="rangeValue(field.id, 1)" type="date" :min="rangeValue(field.id, 0) || undefined" :aria-label="field.label + '结束日期'" :aria-required="field.required" :readonly="!editable(field) || busy" @input="updateRange(field.id, 1, $event)" />
              </div>
              <select v-else-if="field.type === 'member'" :id="`application-${field.id}`" v-model="values[field.id]" :disabled="!editable(field) || busy" :aria-required="field.required">
                <option value="" disabled>{{ field.placeholder || '请选择成员' }}</option><option v-for="person in directory" :key="person.username" :value="person.username">{{ person.displayName }} · {{ person.department }}（{{ person.username }}）</option>
              </select>
              <FileUploadField v-else-if="field.type === 'image' || field.type === 'attachment'" :model-value="values[field.id]" :field-id="field.id" :label="field.label" :image="field.type === 'image'" :workflow-id="workflow.id" :run-id="recalled?.id" :readonly="!editable(field)" :disabled="busy" @update:model-value="values[field.id] = $event" @busy="uploadBusy(field.id, $event)" />
              <input v-else :id="`application-${field.id}`" v-model="values[field.id] as string" :readonly="!editable(field) || busy" :type="field.type === 'number' || field.type === 'rating' ? 'number' : field.type === 'date' ? 'date' : 'text'" :min="field.type === 'rating' ? 1 : undefined" :max="field.type === 'rating' ? (field.max || 5) : undefined" :step="field.type === 'number' ? 'any' : field.type === 'rating' ? '1' : undefined" :aria-required="field.required" :aria-invalid="invalidFields.includes(field.id)" :placeholder="field.placeholder" />
            </div>
          </div>
        </form>
      </div>
      <footer class="start-approval-footer">
        <div v-if="error || draftNotice" class="start-footer-message">
          <p v-if="error" class="start-submit-error" role="alert">{{ error }}</p>
          <p v-else role="status">{{ draftNotice }}</p>
        </div>
        <div class="start-footer-actions"><button type="button" class="start-save-button" :disabled="busy || uploading" @click="saveDraft"><Save :size="16" />保存草稿</button><button type="submit" form="start-approval-form" class="start-submit-button" :disabled="busy || uploading"><Send :size="16" />{{ uploading ? '文件上传中…' : '提交' }}</button></div>
      </footer>
    </section>
  </component>
  <ApprovalSubmitPreview ref="submission" :directory="directory" @submitted="onSubmitted" />
</template>
