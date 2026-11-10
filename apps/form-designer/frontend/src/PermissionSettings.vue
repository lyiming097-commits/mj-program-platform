<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { apiFetchRaw } from './session'
import type { SupervisorDirectory } from './types'
type Rule = { permission: string; scopeType: string; targetId: string; targetName: string; sortOrder?: number }
type PermissionConfiguration = { items: Rule[]; revision: string; orgRevision: string | number }
type Department = SupervisorDirectory['departments'][number]
type Employee = SupervisorDirectory['employees'][number]
const permission = 'admin'
const items = ref<Rule[]>([])
let savedItems: Rule[] = []
const departments = ref<Department[]>([])
const employees = ref<Employee[]>([])
const revision = ref('')
const orgRevision = ref('')
const query = ref('')
const loading = ref(false)
const busy = ref(false)
const dirty = ref(false)
const error = ref('')
const notice = ref('')
const scopes = [{ id: 'department', name: '部门直接成员' }, { id: 'departmentSub', name: '部门及下级' }, { id: 'employee', name: '直接授权人员' }, { id: 'excludedEmployee', name: '排除人员' }]
const personnelScopes = scopes.filter(item => item.id === 'employee' || item.id === 'excludedEmployee')
const selectedRules = computed(() => items.value.filter(item => item.permission === permission))
const flatDepartments = computed(() => {
  const rows: Array<{ id: string; ancestors: string[] }> = []
  function walk(nodes: Department[], ancestors: string[] = []) {
    for (const node of nodes) {
      rows.push({ id: node.id, ancestors })
      walk(node.children ?? [], [...ancestors, node.id])
    }
  }
  walk(departments.value)
  return rows
})
const candidates = computed(() => {
  const keyword = query.value.trim().toLowerCase()
  return employees.value.filter(item => [
    item.name, item.userId, item.pinyinInitials,
    ...item.departments.flatMap(dept => [dept.name, dept.deptId, dept.pinyinInitials, dept.departmentPathText]),
  ].join(' ').toLowerCase().includes(keyword)).map(item => ({
    id: item.userId, name: item.name,
    description: [item.userId, ...item.departments.map(dept => dept.name || dept.deptId)].join(' · '),
  }))
})
const effective = computed(() => employees.value.filter(employee => {
  const rules = selectedRules.value
  if (rules.some(rule => rule.scopeType === 'excludedEmployee' && rule.targetId === employee.userId)) return false
  return rules.some(rule => rule.scopeType === 'employee' && rule.targetId === employee.userId ||
    rule.scopeType === 'department' && employee.departments.some(dept => String(dept.deptId) === rule.targetId) ||
    rule.scopeType === 'departmentSub' && employee.departments.some(dept => { const row = flatDepartments.value.find(item => item.id === String(dept.deptId)); return row?.id === rule.targetId || row?.ancestors.includes(rule.targetId) }))
}))
function checked(id: string) { return selectedRules.value.some(item => item.scopeType === 'employee' && item.targetId === id) }
function toggle(id: string, name: string) {
  if (busy.value) return
  if (checked(id)) items.value = items.value.filter(item => !(item.permission === permission && item.scopeType === 'employee' && item.targetId === id))
  else items.value.push({ permission, scopeType: 'employee', targetId: id, targetName: name })
  dirty.value = true
}
async function json<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await apiFetchRaw(`/api/form-designer/${path}`, init)
  const data = await response.json()
  if (!response.ok) throw Object.assign(new Error(data.detail || '读取失败'), { status: response.status })
  return data as T
}
function loadRules(config: PermissionConfiguration) {
  savedItems = config.items
  items.value = savedItems.map(item => ({ ...item }))
  revision.value = config.revision
  orgRevision.value = String(config.orgRevision)
  dirty.value = false
}
async function load() {
  loading.value = true; error.value = ''
  try {
    const [rules, directory] = await Promise.all([json<PermissionConfiguration>('permissions'), json<SupervisorDirectory>('permissions/directory')])
    if (String(rules.orgRevision) !== String(directory.orgRevision)) throw new Error('组织目录已更新，请重新加载权限设置。')
    loadRules(rules)
    departments.value = directory.departments; employees.value = directory.employees
  } catch (cause) { error.value = cause instanceof Error ? cause.message : '权限设置读取失败' }
  finally { loading.value = false }
}
async function save() {
  if (busy.value || loading.value || !dirty.value) return
  busy.value = true; error.value = ''; notice.value = ''
  try {
    const data = await json<PermissionConfiguration>('permissions', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ items: items.value, revision: revision.value, orgRevision: orgRevision.value }) })
    loadRules(data)
    notice.value = '权限已保存。'
  } catch (cause: any) {
    if (cause.status === 409) { await load(); error.value = '组织或权限配置已变化，已重新加载，请重新选择并确认。' }
    else error.value = String(cause)
  } finally { busy.value = false }
}
function canLeave() {
  if (busy.value) return false
  if (!dirty.value) return true
  if (!window.confirm('权限尚未保存，确定放弃修改吗？')) return false
  items.value = savedItems.map(item => ({ ...item }))
  dirty.value = false
  return true
}
function beforeUnload(event: BeforeUnloadEvent) { if (dirty.value || busy.value) { event.preventDefault(); event.returnValue = '' } }
defineExpose({ canLeave })
onMounted(() => { load(); window.addEventListener('beforeunload', beforeUnload) })
onBeforeUnmount(() => window.removeEventListener('beforeunload', beforeUnload))
</script>
<template>
  <section class="permission-page" aria-label="权限设置">
    <header>
      <div><h2>总管理员</h2><p>选择负责审批流程和权限管理的人员。</p></div>
      <button type="button" :disabled="busy || loading || !dirty || !revision || !orgRevision" @click="save">{{ busy ? '保存中…' : '保存权限' }}</button>
    </header>
    <p v-if="error" class="permission-error" role="alert">{{ error }} <button v-if="!revision && !loading" type="button" @click="load">重新加载</button></p>
    <p v-if="notice && !dirty" class="permission-notice" role="status">{{ notice }}</p>
    <div v-if="loading">正在加载组织目录…</div>
    <fieldset v-else :disabled="busy || !revision" class="permission-columns">
      <section>
        <input v-model="query" placeholder="搜索姓名、部门、账号或拼音首字母" aria-label="搜索授权对象" />
        <div class="permission-candidates">
          <label v-for="item in candidates" :key="item.id">
            <input type="checkbox" :checked="checked(item.id)" @change="toggle(item.id, item.name)" />
            <span>{{ item.name }}<small>{{ item.description }}</small></span>
          </label>
          <p v-if="!candidates.length">未找到匹配人员。</p>
        </div>
      </section>
      <section>
        <h2>已选总管理员（{{ effective.length }}）</h2>
        <p v-if="!effective.length">尚未选择人员。</p>
        <div v-for="employee in effective" :key="employee.userId" class="permission-rule">
          <span>{{ employee.name }}<small>{{ employee.userId }}<template v-for="dept in employee.departments" :key="dept.deptId"> · {{ dept.name || dept.deptId }}</template></small></span>
          <button type="button" @click="items.push({ permission, scopeType: 'excludedEmployee', targetId: employee.userId, targetName: employee.name }); dirty = true">排除</button>
        </div>
        <details v-if="selectedRules.length" class="permission-sources">
          <summary>授权来源（{{ selectedRules.length }}）</summary>
          <div v-for="rule in selectedRules" :key="`${rule.scopeType}:${rule.targetId}`" class="permission-rule">
            <span>{{ rule.targetName }}<small>{{ scopes.find(item => item.id === rule.scopeType)?.name }} · {{ rule.targetId }}</small></span>
            <button v-if="personnelScopes.some(item => item.id === rule.scopeType)" type="button" @click="items = items.filter(item => item !== rule); dirty = true">移除</button>
          </div>
        </details>
      </section>
    </fieldset>
  </section>
</template>
<style scoped>
.permission-page { padding: 20px; border: 1px solid #e2e8f0; border-radius: 8px; background: #fff; color: #334155; font-size: 14px; }
.permission-page > header { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 12px; }
.permission-page h2 { margin: 0 0 16px; font-size: 15px; }
.permission-page > header h2 { margin: 0; font-size: 18px; }
.permission-page p { color: #64748b; line-height: 1.6; }
.permission-page > header p { margin: 5px 0 0; }
.permission-page button { padding: 7px 12px; border: 1px solid #cbd5e1; border-radius: 6px; background: #fff; color: #475569; cursor: pointer; }
.permission-page button:disabled { opacity: .5; cursor: default; }
.permission-page > header > button { border-color: #2563eb; background: #2563eb; color: #fff; }
.permission-columns { display: grid; min-width: 0; margin: 16px 0 0; padding: 0; border: 0; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }
.permission-columns > section { min-width: 0; padding: 16px; border: 1px solid #e2e8f0; border-radius: 8px; }
.permission-page section > input { max-width: 100%; margin-bottom: 12px; padding: 8px; border: 1px solid #cbd5e1; border-radius: 5px; background: #fff; }
.permission-page section > input { display: block; width: 100%; }
.permission-candidates { max-height: 460px; overflow: auto; }
.permission-candidates > label { display: flex; align-items: center; gap: 10px; padding: 10px 6px; border-bottom: 1px solid #f1f5f9; }
.permission-page small { display: block; margin-top: 3px; color: #677b92; }
.permission-rule { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin: 10px 0; padding-bottom: 10px; border-bottom: 1px solid #f1f5f9; }
.permission-rule button { flex: none; }
.permission-sources { margin-top: 14px; }
.permission-sources summary { color: #64748b; cursor: pointer; }
.permission-rule span, .permission-candidates span { min-width: 0; overflow-wrap: anywhere; }
.permission-page .permission-error { color: #b91c1c; }
.permission-page .permission-notice { color: #15803d; }
@media (max-width: 900px) { .permission-columns { grid-template-columns: minmax(0, 1fr); } .permission-page { padding: 14px; } }
</style>
