<script setup lang="ts">
import ResizableDetailDrawer from './ResizableDetailDrawer.vue'
import CenteredApprovalDialog from './CenteredApprovalDialog.vue'
import { LoaderCircle, Save, Search, Trash2, Users, X } from '@lucide/vue'
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { changeWorkflowCategoryStatus, getWorkflowCategorySettings, getSupervisorDirectory, saveWorkflowCategory } from './api'
import type { SupervisorDirectory, WorkflowCategoryDefinition } from './types'

const props = defineProps<{ category: string; approvalCount: number }>()
const emit = defineEmits<{ close: []; saved: [item: WorkflowCategoryDefinition]; deleted: [item: WorkflowCategoryDefinition] }>()
const loading = ref(true), busy = ref(false), ready = ref(false)
const error = ref(''), query = ref('')
const revision = ref(''), orgRevision = ref('')
const name = ref('')
const selected = ref<string[]>([])
const existingSupervisorIds = ref<string[]>([])
const saved = ref('')
const originalName = ref('')
const deleteOpen = ref(false)
const deleteError = ref('')
const directory = ref<SupervisorDirectory>({ orgRevision: 0, departments: [], employees: [] })
const signature = () => JSON.stringify([name.value, selected.value])
const dirty = computed(() => ready.value && signature() !== saved.value)
const departmentNames = computed(() => {
  const names = new Map<string, string>()
  function visit(nodes: SupervisorDirectory['departments']) {
    for (const node of nodes) { names.set(String(node.id), node.name); visit(node.children || []) }
  }
  visit(directory.value.departments)
  return names
})
function departments(person: SupervisorDirectory['employees'][number]) {
  return person.departments.map(dept => dept.departmentPathText || dept.name || departmentNames.value.get(String(dept.deptId)) || dept.deptId).join('、')
}
const candidates = computed(() => {
  const keyword = query.value.trim().toLowerCase()
  return directory.value.employees.filter(person => !keyword || [person.name, person.userId, person.pinyinInitials, departments(person), ...person.departments.flatMap(dept => [dept.deptId, dept.pinyinInitials])].filter(Boolean).join(' ').toLowerCase().includes(keyword))
})
function personName(id: string) { return directory.value.employees.find(person => person.userId === id)?.name || id }
function toggle(id: string) {
  selected.value = selected.value.includes(id) ? selected.value.filter(value => value !== id) : [...selected.value, id]
}
async function load() {
  loading.value = true; ready.value = false; error.value = ''
  try {
    const [config, people] = await Promise.all([getWorkflowCategorySettings(), getSupervisorDirectory()])
    directory.value = people; revision.value = config.revision; orgRevision.value = String(people.orgRevision)
    const item = config.items.find(item => item.key === props.category)
    originalName.value = item?.name || props.category
    name.value = originalName.value
    selected.value = item?.administratorUserIds || []
    existingSupervisorIds.value = item?.supervisorUserIds || []
    saved.value = signature(); ready.value = true
  } catch (cause) { error.value = cause instanceof Error ? cause.message : '读取失败，请重试' }
  finally { loading.value = false }
}
async function save() {
  if (!ready.value || busy.value || !dirty.value || !name.value.trim()) return
  busy.value = true; error.value = ''
  try {
    const item = await saveWorkflowCategory({ key: props.category || undefined, name: name.value.trim(), supervisorUserIds: existingSupervisorIds.value, administratorUserIds: selected.value, revision: revision.value, orgRevision: orgRevision.value })
    saved.value = signature()
    emit('saved', item)
  } catch (cause: unknown) {
    if ((cause as { status?: number }).status === 409) {
      await load()
      error.value = '组织或流程设置已变化，已重新读取，请重新确认。'
    } else error.value = cause instanceof Error ? cause.message : '保存失败，请重试'
  } finally { busy.value = false }
}
function showDelete() {
  deleteError.value = ''
  deleteOpen.value = true
}
function cancelDelete() {
  if (busy.value) return
  deleteOpen.value = false
}
async function confirmDelete() {
  if (!props.category || busy.value) return
  busy.value = true; deleteError.value = ''
  try {
    emit('deleted', await changeWorkflowCategoryStatus(props.category, 'delete', revision.value))
  } catch (cause) {
    deleteError.value = cause instanceof Error ? cause.message : '删除分组失败，请重试'
  } finally { busy.value = false }
}
function close() {
  if (deleteOpen.value || busy.value || (dirty.value && !window.confirm('流程设置尚未保存，确定放弃修改吗？'))) return
  emit('close')
}
function onKey(event: KeyboardEvent) { if (event.key === 'Escape') close() }
function beforeUnload(event: BeforeUnloadEvent) { if (dirty.value || busy.value) { event.preventDefault(); event.returnValue = '' } }
onMounted(() => {
  void load()
  document.addEventListener('keydown', onKey)
  window.addEventListener('beforeunload', beforeUnload)
})
onBeforeUnmount(() => {
  document.removeEventListener('keydown', onKey)
  window.removeEventListener('beforeunload', beforeUnload)
})
</script>

<template>
  <ResizableDetailDrawer :open="true" :suspended="busy" @close="close">
    <section class="employee-dialog category-supervisor-dialog" role="dialog" aria-modal="true" :aria-label="category ? '流程设置' : '新建分组'" @click.stop>
      <header><span class="employee-dialog-heading"><b><Users :size="18" />{{ category ? '流程设置' : '新建分组' }}</b></span><button class="employee-close" aria-label="关闭流程设置" :disabled="busy" @click="close"><X :size="18" /></button></header>
      <div class="employee-dialog-body">
        <p v-if="!category" class="cs-description">创建分组后，可在该分组下新建流程。</p>
        <p v-if="error" class="cs-error" role="alert">{{ error }}</p>
        <p v-if="loading" role="status">正在读取流程设置与人员目录…</p>
        <button v-else-if="!ready" class="aw-button" @click="load">重新加载</button>
        <template v-else>
          <label class="oa-settings-field">流程名称<input v-model="name" maxlength="40" placeholder="请输入流程名称" :disabled="busy" /></label>
          <h3>管理员（{{ selected.length }}）</h3>
          <p class="cs-description">管理员可以管理本分类下的审批。</p>
          <ol v-if="selected.length" class="cs-selected">
            <li v-for="id in selected" :key="id"><span class="cs-person">{{ personName(id) }}<small>{{ id }}</small></span><button class="cs-icon" :aria-label="'移除管理员' + personName(id)" :disabled="busy" @click="toggle(id)"><X :size="15" /></button></li>
          </ol>
          <p v-else class="cs-empty">尚未设置管理员</p>
          <label class="cs-search"><Search :size="16" /><input v-model="query" aria-label="搜索管理员" placeholder="搜索姓名、userId、部门或拼音首字母" :disabled="busy" /></label>
          <div class="cs-candidates" aria-label="管理员候选人员">
            <label v-for="person in candidates" :key="person.userId"><input type="checkbox" :aria-label="'选择管理员' + person.name + ' ' + person.userId" :checked="selected.includes(person.userId)" :disabled="busy || (!selected.includes(person.userId) && selected.length >= 50)" @change="toggle(person.userId)" /><span class="cs-person">{{ person.name }}<small>{{ person.userId }} · {{ departments(person) || '未分配部门' }}</small></span></label>
            <p v-if="!candidates.length" class="cs-empty">没有匹配的人员</p>
          </div>
        </template>
      </div>
      <footer><button v-if="category && ready" class="aw-button aw-danger cs-delete-button" type="button" :disabled="busy" @click="showDelete"><Trash2 :size="15" />删除分组</button><button class="aw-button" :disabled="busy" @click="close">取消</button><button class="aw-primary" :disabled="busy || loading || !ready || !dirty || !name.trim()" @click="save"><LoaderCircle v-if="busy" :size="15" class="cs-spin" /><Save v-else :size="15" />{{ busy ? '保存中…' : category ? '保存流程设置' : '创建分组' }}</button></footer>
    </section>
  </ResizableDetailDrawer>
  <CenteredApprovalDialog v-if="deleteOpen" label="删除分组" :suspended="busy" @close="cancelDelete">
    <section class="employee-dialog category-supervisor-dialog">
      <header><span class="employee-dialog-heading"><b><Trash2 :size="18" />删除分组</b></span></header>
      <div class="employee-dialog-body">
        <p>将「{{ originalName }}」移入回收站？</p>
        <p v-if="approvalCount" class="cs-description">该分组下的 {{ approvalCount }} 项流程将一起隐藏，恢复分组后重新显示。</p>
        <p v-if="deleteError" class="cs-error" role="alert">{{ deleteError }}</p>
      </div>
      <footer>
        <button class="aw-button" type="button" autofocus :disabled="busy" @click="cancelDelete">取消</button>
        <button class="aw-button aw-danger-solid" type="button" :disabled="busy" @click="confirmDelete">{{ busy ? '处理中…' : '移入回收站' }}</button>
      </footer>
    </section>
  </CenteredApprovalDialog>
</template>

<style scoped>
.cs-delete-button{margin-right:auto}
.category-supervisor-dialog{width:100%;max-width:100%;color:#334155;font-size:14px}.employee-dialog-heading b{display:flex;align-items:center;gap:7px}.cs-description,.cs-empty{font-size:13px;line-height:1.8;color:#64748b}.cs-description{margin-top:0}.cs-error{padding:10px;border:1px solid #fecaca;border-radius:6px;background:#fff5f5;color:#b91c1c;line-height:1.7}.cs-notice{display:flex;align-items:flex-start;gap:6px;color:#047857;line-height:1.7}.category-supervisor-dialog h3{font-size:13px;margin:16px 0 10px}.cs-selected{list-style:none;margin:0 0 16px;padding:0;display:grid;gap:6px}.cs-selected li{display:flex;align-items:center;gap:8px;padding:8px;background:#f8fafc;border:1px solid #e2e8f0;border-radius:6px}.cs-order{width:23px;flex:none;color:#2563eb;text-align:center}.cs-person{flex:1;min-width:0;overflow-wrap:anywhere}.cs-person small{display:block;margin-top:3px;color:#94a3b8;font-size:11px;line-height:1.5}.cs-icon{display:grid;place-items:center;width:30px;height:30px;flex:none;padding:0;border:0;border-radius:5px;background:transparent;color:#64748b;cursor:pointer}.cs-icon:hover:not(:disabled){color:#2563eb;background:#eff6ff}.cs-search{display:flex;align-items:center;gap:8px;border:1px solid #cbd5e1;border-radius:6px;height:36px;padding:0 10px;margin:12px 0;color:#94a3b8}.cs-search input{flex:1;min-width:0;border:0;outline:0;background:transparent;font:inherit;color:#334155}.cs-candidates{border:1px solid #e2e8f0;border-radius:6px;max-height:340px;overflow:auto}.cs-candidates>label{display:flex;gap:10px;align-items:center;min-height:58px;padding:8px 12px;cursor:pointer;border-bottom:1px solid #f1f5f9}.cs-candidates>label:last-child{border-bottom:0}.cs-candidates>label:hover{background:#f8fafc}.cs-candidates input{accent-color:#1677ff}.cs-candidates>.cs-empty{padding:0 12px}.category-supervisor-dialog button:disabled{opacity:.45;cursor:default}.category-supervisor-dialog button:focus-visible,.cs-search:focus-within{outline:2px solid #93c5fd;outline-offset:2px}.cs-spin{animation:cs-spin 1s linear infinite}@keyframes cs-spin{to{transform:rotate(360deg)}}@media(max-width:600px){.cs-search{font-size:12px}.cs-selected li{gap:5px;padding:7px 4px}.cs-icon{width:28px}.cs-candidates{max-height:280px}}
</style>
