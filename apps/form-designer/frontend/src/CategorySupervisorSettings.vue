<script setup lang="ts">
import { PlatformDetailDrawer } from '@platform-ui'
import { ArrowDown, ArrowUp, Check, LoaderCircle, Save, Search, Users, X } from '@lucide/vue'
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { getCategorySupervisors, getSupervisorDirectory, saveCategorySupervisors } from './api'
import type { SupervisorDirectory } from './types'

const props = defineProps<{ category: string }>()
const emit = defineEmits<{ close: [] }>()
const loading = ref(true), busy = ref(false), ready = ref(false)
const error = ref(''), notice = ref(''), query = ref('')
const revision = ref(''), orgRevision = ref('')
const selected = ref<string[]>([]), saved = ref<string[]>([])
const directory = ref<SupervisorDirectory>({ orgRevision: 0, departments: [], employees: [] })
const dirty = computed(() => JSON.stringify(selected.value) !== JSON.stringify(saved.value))
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
  notice.value = ''
  selected.value = selected.value.includes(id) ? selected.value.filter(value => value !== id) : [...selected.value, id]
}
function move(index: number, offset: number) {
  const next = [...selected.value], target = index + offset
  if (target < 0 || target >= next.length) return
  const original = next[index]
  next[index] = next[target]; next[target] = original
  selected.value = next; notice.value = ''
}
async function load() {
  loading.value = true; ready.value = false; error.value = ''
  try {
    const [config, people] = await Promise.all([getCategorySupervisors(), getSupervisorDirectory()])
    directory.value = people; revision.value = config.revision; orgRevision.value = String(people.orgRevision)
    selected.value = [...(config.items.find(item => item.category === props.category)?.supervisorUserIds || [])]
    saved.value = [...selected.value]; ready.value = true
  } catch (cause) { error.value = cause instanceof Error ? cause.message : '读取失败，请重试' }
  finally { loading.value = false }
}
async function save() {
  if (!ready.value || busy.value || !dirty.value) return
  busy.value = true; error.value = ''; notice.value = ''
  try {
    const config = await saveCategorySupervisors({ category: props.category, supervisorUserIds: selected.value, revision: revision.value, orgRevision: orgRevision.value })
    revision.value = config.revision; saved.value = [...selected.value]; notice.value = '分类主管已保存，新发起的申请按此设置分配审批人。'
  } catch (cause: unknown) {
    if ((cause as { status?: number }).status === 409) {
      await load()
      error.value = '组织或分类主管配置已变化，已重新读取，请重新选择并确认。'
    } else error.value = cause instanceof Error ? cause.message : '保存失败，请重试'
  } finally { busy.value = false }
}
function close() {
  if (busy.value || (dirty.value && !window.confirm('分类主管尚未保存，确定放弃修改吗？'))) return
  emit('close')
}
function onKey(event: KeyboardEvent) { if (event.key === 'Escape') close() }
function beforeUnload(event: BeforeUnloadEvent) { if (dirty.value || busy.value) { event.preventDefault(); event.returnValue = '' } }
onMounted(() => { void load(); document.addEventListener('keydown', onKey); window.addEventListener('beforeunload', beforeUnload) })
onBeforeUnmount(() => { document.removeEventListener('keydown', onKey); window.removeEventListener('beforeunload', beforeUnload) })
</script>

<template>
  <PlatformDetailDrawer :open="true" :suspended="busy" @close="close">
    <section class="employee-dialog category-supervisor-dialog" role="dialog" aria-modal="true" aria-label="设置分类主管" @click.stop>
      <header><span class="employee-dialog-heading"><b><Users :size="18" />设置分类主管</b><small>{{ category }}</small></span><button class="employee-close" aria-label="关闭分类主管设置" :disabled="busy" @click="close"><X :size="18" /></button></header>
      <div class="employee-dialog-body">
        <p class="cs-description">审批节点选择“直属主管”后，由本分类的主管审批。多人时按所列顺序依次处理，设置变更只影响新申请。</p>
        <p v-if="error" class="cs-error" role="alert">{{ error }}</p><p v-if="notice" class="cs-notice" role="status"><Check :size="15" />{{ notice }}</p>
        <p v-if="loading" role="status">正在读取分类主管与人员目录…</p>
        <button v-else-if="!ready" class="aw-button" @click="load">重新加载</button>
        <template v-else>
          <h3>已选主管（{{ selected.length }}）</h3>
          <ol v-if="selected.length" class="cs-selected">
            <li v-for="(id, index) in selected" :key="id"><span class="cs-order">{{ index + 1 }}</span><span class="cs-person">{{ personName(id) }}<small>{{ id }}</small></span><button class="cs-icon" :aria-label="'上移主管' + personName(id)" :disabled="busy || index === 0" @click="move(index, -1)"><ArrowUp :size="15" /></button><button class="cs-icon" :aria-label="'下移主管' + personName(id)" :disabled="busy || index === selected.length - 1" @click="move(index, 1)"><ArrowDown :size="15" /></button><button class="cs-icon" :aria-label="'移除主管' + personName(id)" :disabled="busy" @click="toggle(id)"><X :size="15" /></button></li>
          </ol>
          <p v-else class="cs-empty">尚未设置；使用“直属主管”的审批需要先设置本分类主管。</p>
          <label class="cs-search"><Search :size="16" /><input v-model="query" aria-label="搜索分类主管人员" placeholder="搜索姓名、userId、部门或拼音首字母" :disabled="busy" /></label>
          <div class="cs-candidates" aria-label="分类主管候选人员">
            <label v-for="person in candidates" :key="person.userId"><input type="checkbox" :aria-label="'选择主管' + person.name + ' ' + person.userId" :checked="selected.includes(person.userId)" :disabled="busy || (!selected.includes(person.userId) && selected.length >= 50)" @change="toggle(person.userId)" /><span class="cs-person">{{ person.name }}<small>{{ person.userId }} · {{ departments(person) || '未分配部门' }}</small></span></label>
            <p v-if="!candidates.length" class="cs-empty">没有匹配的人员</p>
          </div>
        </template>
      </div>
      <footer><button class="aw-button" :disabled="busy" @click="close">取消</button><button class="aw-primary" :disabled="busy || loading || !ready || !dirty" @click="save"><LoaderCircle v-if="busy" :size="15" class="cs-spin" /><Save v-else :size="15" />{{ busy ? '保存中…' : '保存主管' }}</button></footer>
    </section>
  </PlatformDetailDrawer>
</template>

<style scoped>
.category-supervisor-dialog{width:100%;max-width:100%;color:#334155;font-size:14px}.employee-dialog-heading b{display:flex;align-items:center;gap:7px}.cs-description,.cs-empty{font-size:13px;line-height:1.8;color:#64748b}.cs-description{margin-top:0}.cs-error{padding:10px;border:1px solid #fecaca;border-radius:6px;background:#fff5f5;color:#b91c1c;line-height:1.7}.cs-notice{display:flex;align-items:flex-start;gap:6px;color:#047857;line-height:1.7}.category-supervisor-dialog h3{font-size:13px;margin:16px 0 10px}.cs-selected{list-style:none;margin:0 0 16px;padding:0;display:grid;gap:6px}.cs-selected li{display:flex;align-items:center;gap:8px;padding:8px;background:#f8fafc;border:1px solid #e2e8f0;border-radius:6px}.cs-order{width:23px;flex:none;color:#2563eb;text-align:center}.cs-person{flex:1;min-width:0;overflow-wrap:anywhere}.cs-person small{display:block;margin-top:3px;color:#94a3b8;font-size:11px;line-height:1.5}.cs-icon{display:grid;place-items:center;width:30px;height:30px;flex:none;padding:0;border:0;border-radius:5px;background:transparent;color:#64748b;cursor:pointer}.cs-icon:hover:not(:disabled){color:#2563eb;background:#eff6ff}.cs-search{display:flex;align-items:center;gap:8px;border:1px solid #cbd5e1;border-radius:6px;height:36px;padding:0 10px;margin:12px 0;color:#94a3b8}.cs-search input{flex:1;min-width:0;border:0;outline:0;background:transparent;font:inherit;color:#334155}.cs-candidates{border:1px solid #e2e8f0;border-radius:6px;max-height:340px;overflow:auto}.cs-candidates>label{display:flex;gap:10px;align-items:center;min-height:58px;padding:8px 12px;cursor:pointer;border-bottom:1px solid #f1f5f9}.cs-candidates>label:last-child{border-bottom:0}.cs-candidates>label:hover{background:#f8fafc}.cs-candidates input{accent-color:#1677ff}.cs-candidates>.cs-empty{padding:0 12px}.category-supervisor-dialog button:disabled{opacity:.45;cursor:default}.category-supervisor-dialog button:focus-visible,.cs-search:focus-within{outline:2px solid #93c5fd;outline-offset:2px}.cs-spin{animation:cs-spin 1s linear infinite}@keyframes cs-spin{to{transform:rotate(360deg)}}@media(max-width:600px){.cs-search{font-size:12px}.cs-selected li{gap:5px;padding:7px 4px}.cs-icon{width:28px}.cs-candidates{max-height:280px}}
</style>
