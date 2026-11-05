<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { apiFetchRaw } from './session'
type Rule = { permission: string; scopeType: string; targetId: string; targetName: string; sortOrder?: number }
type Department = { id: string; name: string; children: Department[] }
type Employee = { userId: string; name: string; departments: Array<{ deptId: string }> }
const permission = ref('user')
const items = ref<Rule[]>([])
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
const groups = [{ id: 'user', name: '应用使用者' }, { id: 'designer', name: '表单流程设计员' }, { id: 'admin', name: '应用管理员' }]
const scopes = [{ id: 'department', name: '部门直接成员' }, { id: 'departmentSub', name: '部门及下级' }, { id: 'employee', name: '直接授权人员' }, { id: 'excludedEmployee', name: '排除人员' }]
const scope = ref('departmentSub')
const selectedRules = computed(() => items.value.filter(item => item.permission === permission.value))
const flatDepartments = computed(() => {
  const rows: Array<Department & { depth: number; path: string; ancestors: string[] }> = []
  function walk(nodes: Department[], depth = 0, path = '', ancestors: string[] = []) {
    nodes.forEach(node => { rows.push({ ...node, depth, path: path ? `${path} / ${node.name}` : node.name, ancestors }); walk(node.children || [], depth + 1, path ? `${path} / ${node.name}` : node.name, [...ancestors, node.id]) })
  }
  walk(departments.value)
  return rows
})
const candidates = computed(() => scope.value.startsWith('department')
  ? flatDepartments.value.filter(item => !query.value || item.path.includes(query.value)).map(item => ({ id: item.id, name: item.name, description: item.path, depth: item.depth }))
  : employees.value.filter(item => !query.value || `${item.name} ${item.userId}`.includes(query.value)).map(item => ({ id: item.userId, name: item.name, description: item.userId, depth: 0 })))
const effective = computed(() => employees.value.filter(employee => {
  const rules = selectedRules.value
  if (rules.some(rule => rule.scopeType === 'excludedEmployee' && rule.targetId === employee.userId)) return false
  return rules.some(rule => rule.scopeType === 'employee' && rule.targetId === employee.userId ||
    rule.scopeType === 'department' && employee.departments.some(dept => String(dept.deptId) === rule.targetId) ||
    rule.scopeType === 'departmentSub' && employee.departments.some(dept => { const row = flatDepartments.value.find(item => item.id === String(dept.deptId)); return row?.id === rule.targetId || row?.ancestors.includes(rule.targetId) }))
}))
function checked(id: string) { return items.value.some(item => item.permission === permission.value && item.scopeType === scope.value && item.targetId === id) }
function toggle(id: string, name: string) {
  if (checked(id)) items.value = items.value.filter(item => !(item.permission === permission.value && item.scopeType === scope.value && item.targetId === id))
  else items.value.push({ permission: permission.value, scopeType: scope.value, targetId: id, targetName: name })
  dirty.value = true
}
async function json(path: string, init?: RequestInit) {
  const response = await apiFetchRaw(`/api/form-designer/${path}`, init)
  const data = await response.json()
  if (!response.ok) throw Object.assign(new Error(data.detail || '读取失败'), { status: response.status })
  return data
}
async function load() {
  loading.value = true; error.value = ''
  try {
    const [rules, directory] = await Promise.all([json('permissions'), json('permissions/directory')])
    items.value = rules.items; revision.value = rules.revision; orgRevision.value = String(directory.orgRevision)
    departments.value = directory.departments; employees.value = directory.employees
    dirty.value = false
  } catch (cause) { error.value = String(cause) }
  finally { loading.value = false }
}
async function save() {
  busy.value = true; error.value = ''; notice.value = ''
  try {
    const data = await json('permissions', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ items: items.value, revision: revision.value, orgRevision: orgRevision.value }) })
    items.value = data.items; revision.value = data.revision; orgRevision.value = String(data.orgRevision); dirty.value = false; notice.value = '权限已保存，后续业务请求按新权限校验。'
  } catch (cause: any) {
    if (cause.status === 409) { await load(); error.value = '组织或权限配置已变化，已重新加载，请重新选择并确认。' }
    else error.value = String(cause)
  } finally { busy.value = false }
}
function canLeave() { return !busy.value && (!dirty.value || window.confirm('权限尚未保存，确定放弃修改吗？')) }
function beforeUnload(event: BeforeUnloadEvent) { if (dirty.value || busy.value) { event.preventDefault(); event.returnValue = '' } }
defineExpose({ canLeave })
onMounted(() => { load(); window.addEventListener('beforeunload', beforeUnload) })
onBeforeUnmount(() => window.removeEventListener('beforeunload', beforeUnload))
</script>
<template>
  <main class="permission-page">
    <header><div><h1>应用权限</h1><p>组织人员来自统一身份中心；此处仅配置表单设计应用的业务权限。</p></div><button :disabled="busy || loading || !dirty || !revision || !orgRevision" @click="save">{{ busy ? '保存中…' : '保存权限' }}</button></header>
    <p v-if="error" class="permission-error" role="alert">{{ error }}</p><p v-if="notice" class="permission-notice" role="status">{{ notice }}</p>
    <nav><button v-for="group in groups" :key="group.id" :class="{ active: permission === group.id }" @click="permission = group.id">{{ group.name }}</button></nav>
    <div v-if="loading">正在加载组织目录…</div>
    <div v-else class="permission-columns">
      <section><h2>授权来源</h2><label>范围 <select v-model="scope"><option v-for="item in scopes" :key="item.id" :value="item.id">{{ item.name }}</option></select></label><input v-model="query" placeholder="搜索部门、姓名或 userId" aria-label="搜索授权对象" />
        <div class="permission-candidates"><label v-for="item in candidates" :key="item.id" :style="{ paddingLeft: `${12 + item.depth * 18}px` }"><input type="checkbox" :checked="checked(item.id)" @change="toggle(item.id, item.name)" /><span>{{ item.depth ? '└ ' : '' }}{{ item.name }}<small>{{ item.description }}</small></span></label></div>
      </section>
      <section><h2>已配置规则（{{ selectedRules.length }}）</h2><div v-for="rule in selectedRules" :key="`${rule.scopeType}:${rule.targetId}`" class="permission-rule"><span>{{ rule.targetName }}<small>{{ scopes.find(item => item.id === rule.scopeType)?.name }} · {{ rule.targetId }}</small></span><button @click="items = items.filter(item => item !== rule); dirty = true">移除</button></div><p v-if="!selectedRules.length">尚未配置此权限。</p>
        <h2>实际生效成员（{{ effective.length }}）</h2><div v-for="employee in effective" :key="employee.userId" class="permission-rule"><span>{{ employee.name }}<small>{{ employee.userId }}</small></span><button @click="items.push({ permission, scopeType: 'excludedEmployee', targetId: employee.userId, targetName: employee.name }); dirty = true">排除</button></div>
      </section>
    </div>
  </main>
</template>
<style scoped>
.permission-page{padding:32px;background:#f8fafc;min-height:calc(100vh - 56px);color:#334155;font:14px system-ui}.permission-page header{display:flex;align-items:center;justify-content:space-between;gap:24px}.permission-page h1{margin:0;font-size:24px}.permission-page h2{font-size:16px;margin:0 0 18px}.permission-page p{color:#64748b;line-height:1.7}.permission-page button{border:1px solid #cbd5e1;background:white;padding:9px 14px;border-radius:6px;color:#475569;cursor:pointer}.permission-page button:disabled{opacity:.5;cursor:default}.permission-page header>button{background:#2563eb;color:white;border:0}.permission-page nav{display:flex;gap:12px;margin:24px 0}.permission-page nav .active{background:#eff6ff;border-color:#2563eb;color:#2563eb}.permission-columns{display:grid;grid-template-columns:1fr 1fr;gap:24px}.permission-columns>section{background:white;border:1px solid #e2e8f0;border-radius:8px;padding:24px}.permission-page select,.permission-page section>input{box-sizing:border-box;padding:10px;border:1px solid #cbd5e1;border-radius:5px;background:white;margin-bottom:16px}.permission-page section>input{display:block;width:100%}.permission-candidates{max-height:500px;overflow:auto}.permission-candidates>label{display:flex;align-items:center;gap:12px;padding:12px;border-bottom:1px solid #f1f5f9}.permission-page small{display:block;margin-top:4px;color:#94a3b8}.permission-rule{display:flex;justify-content:space-between;align-items:center;margin:12px 0;padding-bottom:12px;border-bottom:1px solid #f1f5f9}.permission-error{color:#b91c1c!important}.permission-notice{color:#15803d!important}@media(max-width:900px){.permission-columns{grid-template-columns:1fr}.permission-page{padding:16px}}
</style>
