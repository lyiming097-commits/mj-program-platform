<script setup lang="ts">
import { ChevronDown, PencilLine, Save, Search } from '@lucide/vue'
import { computed, nextTick, onMounted, ref, useId } from 'vue'
import { getPersonnelImpact, savePersonnelAssignment } from './api'
import PersonnelFlowNodes from './PersonnelFlowNodes.vue'
import type { PersonnelFlow, PersonnelImpact, WorkflowNode, WorkflowSchema } from './types'

const emit = defineEmits<{ changed: [workflow: WorkflowSchema] }>()
const people = ref<PersonnelImpact['people']>([])
const result = ref<PersonnelImpact | null>(null)
const personId = ref('')
const openFlows = ref<string[]>([])
const editing = ref<{
  flow: PersonnelFlow
  node: WorkflowNode
  branchPath: string[]
  source: string
  target: string
} | null>(null)
const replaced = ref(new Map<string, Map<string, Set<string>>>())
const loading = ref(false), saving = ref(false)
const error = ref(''), saveError = ref(''), notice = ref('')
const pickerId = useId()
const directory = computed(() => new Map(people.value.map(person => [person.id, person])))
const searchedId = computed(() => result.value?.person?.id)
const replacements = computed(() => people.value.filter(person =>
  person.active && !editing.value?.node.assignees?.includes(person.id),
))

function personName(id: string) {
  const person = searchedId.value === id ? result.value?.person : undefined
  const name = person?.name && person.name !== id ? person.name : directory.value.get(id)?.name
  return name && name !== id ? name : '未登记姓名'
}

function workflowRows(nodes: WorkflowNode[], branchPath: string[] = []): Array<{ node: WorkflowNode; branchPath: string[] }> {
  return nodes.flatMap(node => [
    { node, branchPath },
    ...(node.branches ?? []).flatMap(branch => workflowRows(branch.nodes ?? [], [...branchPath, branch.name])),
  ])
}

const flows = computed(() => (result.value?.flows ?? []).map(flow => {
  const rows = workflowRows(flow.nodes)
  return { flow, rows, hits: rows.filter(({ node }) => node.assignees?.includes(searchedId.value ?? '')).length }
}))
const sourceMarked = computed(() => {
  const change = editing.value
  return change && (change.source === searchedId.value || replaced.value.get(change.flow.id)?.get(change.node.id)?.has(change.source))
})

function updateExpanded(flowId: string, event: Event) {
  const open = (event.target as HTMLDetailsElement).open
  if (open !== openFlows.value.includes(flowId)) {
    openFlows.value = open ? [...openFlows.value, flowId] : openFlows.value.filter(id => id !== flowId)
  }
}

function canLeave() {
  if (saving.value) return false
  if (editing.value?.target && !window.confirm('人员修改尚未保存，确定放弃吗？')) return false
  editing.value = null
  return true
}

async function loadPeople() {
  loading.value = true
  error.value = ''
  try {
    people.value = (await getPersonnelImpact()).people
    personId.value = people.value.find(person => !person.active)?.id || ''
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '人员目录加载失败'
  } finally { loading.value = false }
}

function changePerson(event: Event) {
  const select = event.target as HTMLSelectElement
  if (!canLeave()) { select.value = personId.value; return }
  personId.value = select.value
  result.value = null
  error.value = ''
}

async function search() {
  if (!personId.value || loading.value || !canLeave()) return
  loading.value = true
  error.value = ''
  saveError.value = ''
  notice.value = ''
  result.value = null
  replaced.value.clear()
  try {
    const impact = await getPersonnelImpact(personId.value)
    result.value = impact
    const flow = impact.flows[0]
    openFlows.value = flow ? [flow.id] : []
    const row = flows.value[0]?.rows.find(({ node }) => node.assignees?.includes(personId.value))
    if (flow && row) editing.value = { flow, ...row, source: personId.value, target: '' }
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '人员排查失败'
  } finally { loading.value = false }
}

async function editPerson(flow: PersonnelFlow, node: WorkflowNode, source: string, branchPath: string[]) {
  if (editing.value?.flow.id === flow.id && editing.value.node.id === node.id && editing.value.source === source) return
  if (!canLeave()) return
  editing.value = { flow, node, branchPath, source, target: '' }
  saveError.value = ''
  notice.value = ''
  await nextTick()
  const picker = document.getElementById(pickerId)
  if (picker && picker.getBoundingClientRect().bottom > window.innerHeight) picker.focus()
}

async function savePerson() {
  const change = editing.value
  if (!change?.target || saving.value) return
  saving.value = true
  saveError.value = ''
  notice.value = ''
  try {
    const { workflow, flow } = await savePersonnelAssignment({
      workflowId: change.flow.id, nodeId: change.node.id, updatedAt: change.flow.updatedAt,
      source: change.source, target: change.target, assignees: change.node.assignees ?? [],
    })
    if (result.value) result.value.flows = result.value.flows.map(item => item.id === flow.id ? flow : item)
    const flowMarks = replaced.value.get(flow.id) ?? new Map<string, Set<string>>()
    const marks = flowMarks.get(change.node.id) ?? new Set<string>()
    marks.delete(change.source)
    marks.add(change.target)
    flowMarks.set(change.node.id, marks)
    replaced.value.set(flow.id, flowMarks)

    const row = workflowRows(flow.nodes).find(({ node }) => node.id === change.node.id)
    editing.value = row ? { flow, ...row, source: change.target, target: '' } : null
    notice.value = '已保存'
    emit('changed', workflow)
  } catch (cause) {
    saveError.value = cause instanceof Error ? cause.message : '人员修改保存失败'
  } finally { saving.value = false }
}

function zoomCanvas(event: WheelEvent) {
  const canvas = event.currentTarget as HTMLElement
  const diagram = canvas.firstElementChild as HTMLElement | null
  if (!diagram || !event.deltaY || Math.abs(event.deltaX) > Math.abs(event.deltaY)) return
  const unit = event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? canvas.clientHeight : 1
  const delta = Math.max(-120, Math.min(120, event.deltaY * unit))
  const previous = Number(diagram.style.getPropertyValue('--personnel-zoom')) || 1
  const next = Math.max(.6, Math.min(1.4, previous * Math.exp(-delta / 480)))
  if (next === previous) return
  event.preventDefault()
  const before = diagram.getBoundingClientRect()
  diagram.style.setProperty('--personnel-zoom', String(next))
  const after = diagram.getBoundingClientRect()
  const ratio = next / previous
  canvas.scrollLeft += after.left + (event.clientX - before.left) * ratio - event.clientX
  canvas.scrollTop += after.top + (event.clientY - before.top) * ratio - event.clientY
}

defineExpose({ canLeave })
onMounted(loadPeople)
</script>

<template>
  <section class="oa-personnel-panel personnel-page" aria-label="人员排查">
    <header class="personnel-heading">
      <h2>人员排查</h2>
      <p>查看人员在各审批流程中的引用。</p>
    </header>
    <form class="oa-personnel-search" @submit.prevent="search">
      <label class="oa-settings-field">
        查找人员
        <select aria-label="查找人员" :value="personId" :disabled="loading || saving" @change="changePerson">
          <option value="" disabled>请选择人员</option>
          <option v-for="person in people" :key="person.id" :value="person.id">
            {{ person.name }}（{{ person.active ? person.id : '不在在职目录 · ' + person.id }}）
          </option>
        </select>
      </label>
      <button type="submit" class="aw-primary" :disabled="!personId || loading || saving"><Search :size="15" />查找引用</button>
    </form>
    <p v-if="loading" class="oa-personnel-message" role="status">正在加载人员引用…</p>
    <p v-if="error" class="aw-error oa-personnel-message" role="alert">{{ error }} <button v-if="!people.length && !loading" type="button" @click="loadPeople">重试</button></p>

    <div v-if="flows.length" class="personnel-flows">
      <details v-for="{ flow, rows, hits } in flows" :key="flow.id" :open="openFlows.includes(flow.id)" @toggle="updateExpanded(flow.id, $event)">
        <summary>
          <strong>{{ flow.name }}</strong>
          <span>{{ flow.category }} · {{ flow.publishedVersion ? '已发布 v' + flow.publishedVersion : '未发布' }}</span>
          <span :class="hits ? 'personnel-marked' : 'personnel-resolved'">{{ hits ? hits + ' 处命中' : '命中已处理' }}</span>
          <ChevronDown :size="15" class="personnel-chevron" />
        </summary>

        <div v-if="openFlows.includes(flow.id)" class="personnel-layout">
          <div class="personnel-canvas" role="region" :aria-label="flow.name + '流程图，使用滚轮缩放'" tabindex="0" @wheel="zoomCanvas">
            <div class="personnel-diagram">
              <PersonnelFlowNodes
                :nodes="flow.nodes" :searched-id="searchedId" :replaced="replaced.get(flow.id)"
                :selected="editing?.flow.id === flow.id ? editing : null" :person-name="personName" :disabled="saving || loading"
                @select="(node, id) => editPerson(flow, node, id, rows.find(row => row.node === node)?.branchPath ?? [])"
              />
            </div>
          </div>
          <aside class="personnel-editor" aria-label="修改人员">
            <header><PencilLine :size="16" /><h3>修改人员</h3></header>
            <form v-if="editing?.flow.id === flow.id" @submit.prevent="savePerson">
              <div class="personnel-edit-node">
                <strong>{{ editing.node.name }}</strong>
                <small>{{ editing.branchPath.join(' / ') || '主流程' }}</small>
              </div>
              <dl class="personnel-current">
                <dt>当前人员</dt>
                <dd :class="{ 'personnel-marked': sourceMarked }">{{ personName(editing.source) }}</dd>
              </dl>
              <label class="oa-settings-field" :for="pickerId">
                替换为
                <select :id="pickerId" v-model="editing.target" :class="{ 'personnel-marked': editing.target }" :disabled="saving" @change="saveError = ''; notice = ''">
                  <option value="">选择人员</option>
                  <option v-for="person in replacements" :key="person.id" :value="person.id">{{ personName(person.id) }}</option>
                </select>
              </label>
              <small v-if="editing.target && editing.node.assigneeMode === 'direct_manager'">保存后该节点会改用指定人员。</small>
              <p v-if="saveError" class="aw-error personnel-edit-message" role="alert">{{ saveError }}</p>
              <p v-if="notice" class="personnel-saved personnel-edit-message" role="status">{{ notice }}</p>
              <footer>
                <button type="submit" class="aw-primary" :disabled="saving || !editing.target">
                  <Save :size="15" />{{ saving ? '保存中…' : '保存' }}
                </button>
              </footer>
            </form>
            <p v-else class="personnel-editor-empty">点击流程图中的姓名修改人员</p>
          </aside>
        </div>
      </details>
    </div>
    <p v-else-if="!loading && !error" class="oa-empty oa-personnel-message">{{ result ? '没有匹配的流程引用' : '选择人员后查找引用' }}</p>
  </section>
</template>

<style scoped>
.personnel-page { background: #fff; color: #334155; }
.personnel-heading { padding: 16px 16px 0; }
.personnel-heading h2 { margin: 0; font-size: 18px; }
.personnel-heading p { margin: 5px 0 0; color: #63758e; font-size: 13px; }
.oa-personnel-search { flex-wrap: wrap; }
.personnel-flows { display: grid; gap: 10px; padding: 0 16px 16px; }
.personnel-flows details { container-type: inline-size; border: 1px solid #dfe7f1; border-radius: 8px; }
.personnel-flows summary { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; padding: 10px 12px; background: #f4f7fb; border-radius: 7px; cursor: pointer; list-style: none; }
.personnel-flows summary::-webkit-details-marker { display: none; }
.personnel-flows summary > span { color: #63758e; font-size: 12px; }
.personnel-chevron { margin-left: auto; }
details[open] .personnel-chevron { transform: rotate(180deg); }
.personnel-flows summary .personnel-resolved, .personnel-saved { color: #166645; }
.personnel-layout { display: grid; grid-template-columns: minmax(0, 1fr) 220px; }
.personnel-canvas {
  --personnel-wire: #acbed2;
  min-height: 270px;
  max-height: min(68vh, 640px);
  padding: 16px;
  overflow: auto;
  background-color: #f7f9fc;
  background-image: radial-gradient(circle, #d7e1ec .8px, transparent .9px);
  background-size: 9px 9px;
}
.personnel-diagram { width: max-content; min-width: 176px; margin-inline: auto; zoom: var(--personnel-zoom, 1); }
.personnel-editor { min-width: 0; display: flex; flex-direction: column; border-inline-start: 1px solid #dfe7f1; }
.personnel-editor > header { display: flex; align-items: center; gap: 7px; padding: 13px 14px; border-bottom: 1px solid #dfe7f1; }
.personnel-editor > header svg { color: #176ac4; }
.personnel-editor h3 { margin: 0; font-size: 14px; }
.personnel-editor form { display: flex; flex-direction: column; flex: 1; gap: 10px; padding: 13px 14px; }
.personnel-edit-node { padding-bottom: 10px; border-bottom: 1px solid #dfe7f1; overflow-wrap: anywhere; }
.personnel-edit-node small, .personnel-current dt, .personnel-editor form > small { display: block; color: #5f728b; font-size: 12px; }
.personnel-current { margin: 0; }
.personnel-current dd { display: inline-block; margin: 4px 0 0; overflow-wrap: anywhere; }
.personnel-marked, .personnel-flows summary .personnel-marked {
  padding: 2px 5px;
  border-radius: 4px;
  background: #fff0f1;
  color: #b4232e;
}
.personnel-editor .oa-settings-field { margin: 0; }
.personnel-editor select.personnel-marked { background: #fff0f1; color: #b4232e; }
.personnel-editor-empty, .personnel-edit-message { margin: 0; font-size: 13px; }
.personnel-editor-empty { padding: 13px 14px; color: #5f728b; }
.personnel-editor footer { display: flex; justify-content: flex-end; margin-top: auto; padding-top: 10px; border-top: 1px solid #dfe7f1; }
@container (max-width: 590px) {
  .personnel-layout { grid-template-columns: minmax(0, 1fr); }
  .personnel-editor { border-inline-start: 0; border-top: 1px solid #dfe7f1; }
}
</style>
