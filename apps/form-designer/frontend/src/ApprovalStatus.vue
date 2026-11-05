<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { ArrowLeft, ChevronLeft, ChevronRight, FileText, Plus, RefreshCw, Search } from '@lucide/vue'
import { listApprovalRecords, listWorkflows } from './api'
import { publishedWorkflowCategories } from './workflow-categories'
import type { ApprovalRecord, AuthUser, WorkflowSchema } from './types'
import './approval-status.css'

const props = defineProps<{ user: AuthUser }>()
const emit = defineEmits<{ back: []; detail: [id: string]; handle: [id: string]; configure: [] }>()
const isAdmin = computed(() => props.user.canManagePermissions === true)
const records = ref<ApprovalRecord[]>([])
const workflows = ref<WorkflowSchema[]>([])
const loading = ref(false)
const error = ref('')
type Scope = 'mine' | 'pending' | 'processed' | 'copied'
const scope = ref<Scope>('mine')
const stage = ref('all')
const filters = ref({ title: '', category: '', node: '', applicant: '', handler: '', date: '' })
const page = ref(1)
const pageSize = 20
const scopes: { key: Scope; label: string }[] = [
  { key: 'mine', label: '我发起的' }, { key: 'pending', label: '待我处理' },
  { key: 'processed', label: '我已处理' }, { key: 'copied', label: '抄送我的' },
]
const stages = [
  { key: 'all', label: '全部状态' }, { key: 'approving', label: '待审批' }, { key: 'executing', label: '执行中' },
  { key: 'pending_assignment', label: '待分配' }, { key: 'returned', label: '已退回' },
  { key: 'completed', label: '已完成' }, { key: 'rejected', label: '已拒绝' }, { key: 'recalled', label: '已撤回' },
]
function inScope(record: ApprovalRecord, key: Scope) {
  if (key === 'mine') return record.mine
  if (key === 'pending') return record.canHandle
  if (key === 'processed') return record.processed
  // No copy recipients are persisted yet. Participation never implies a copy.
  return false
}
const scoped = computed(() => records.value.filter(record => inScope(record, scope.value)))
const contains = (value: string, query: string) => value.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase())
const filtered = computed(() => scoped.value.filter(record =>
  (stage.value === 'all' || record.stage === stage.value) &&
  contains(record.title + ' ' + record.workflowName, filters.value.title) &&
  (!filters.value.category || record.category === filters.value.category) &&
  contains(record.currentNode, filters.value.node) && contains(record.applicant, filters.value.applicant) &&
  contains(record.currentHandlers.join('、'), filters.value.handler) &&
  (!filters.value.date || localDate(record.createdAt) === filters.value.date)))
const categories = computed(() => publishedWorkflowCategories(workflows.value))
const pageCount = computed(() => Math.max(1, Math.ceil(filtered.value.length / pageSize)))
const rows = computed(() => filtered.value.slice((page.value - 1) * pageSize, page.value * pageSize))
const stageName = (key: string) => stages.find(item => item.key === key)?.label ?? key
function localDate(value: string) {
  const date = new Date(value)
  return Number.isFinite(date.getTime()) ? [date.getFullYear(), String(date.getMonth() + 1).padStart(2, '0'), String(date.getDate()).padStart(2, '0')].join('-') : ''
}
function displayDate(value: string) { return new Date(value).toLocaleString('zh-CN', { hour12: false }) }
async function refresh() {
  if (loading.value) return
  loading.value = true
  error.value = ''
  try {
    const [recordResult, workflowResult] = await Promise.allSettled([listApprovalRecords('personal'), listWorkflows()])
    const messages: string[] = []
    if (recordResult.status === 'fulfilled') records.value = recordResult.value
    else messages.push('审批记录加载失败，请刷新重试')
    if (workflowResult.status === 'fulfilled') {
      workflows.value = workflowResult.value
      if (filters.value.category && !categories.value.includes(filters.value.category)) filters.value.category = ''
    } else messages.push('流程分类加载失败，暂保留原分类选项，请刷新重试')
    error.value = messages.join('；')
  } finally { loading.value = false }
}
function showError(message: string) { error.value = message }
watch([scope, stage, filters], () => { page.value = 1 }, { deep: true })
watch(pageCount, count => { if (page.value > count) page.value = count })
function resetFilters() { filters.value = { title: '', category: '', node: '', applicant: '', handler: '', date: '' }; stage.value = 'all' }

onMounted(() => { void refresh() })
defineExpose({ refresh, showError })
</script>

<template>
  <main class="approval-status-page">
    <header class="approval-status-heading">
      <div><button class="approval-status-back" @click="emit('back')"><ArrowLeft :size="15" />返回审批首页</button><h1>流程状态</h1><p>查看与我有关的审批进度与处理记录</p></div>
      <div class="approval-status-actions"><button class="status-button" :disabled="loading" @click="refresh"><RefreshCw :size="15" />刷新</button><button v-if="isAdmin" class="status-button primary" @click="emit('configure')"><Plus :size="16" />新建审批</button></div>
    </header>
    <div v-if="error" class="approval-status-error" role="alert">{{ error }}</div>
    <nav class="approval-scope-tabs" aria-label="流程范围">
      <button v-for="item in scopes" :key="item.key" :class="{ active: scope === item.key }" :aria-pressed="scope === item.key" @click="scope = item.key">{{ item.label }}<span>{{ records.filter(record => inScope(record, item.key)).length }}</span></button>
    </nav>
    <nav class="approval-stage-tabs" aria-label="流程状态筛选">
      <button v-for="item in stages" :key="item.key" :class="{ active: stage === item.key }" :aria-pressed="stage === item.key" @click="stage = item.key">{{ item.label }}<span>{{ item.key === 'all' ? scoped.length : scoped.filter(record => record.stage === item.key).length }}</span></button>
    </nav>
    <section class="approval-status-table-panel" aria-label="审批流程记录" :aria-busy="loading">
      <div class="approval-status-table-tools"><span><FileText :size="15" />{{ loading ? '正在读取流程…' : filtered.length + ' 条审批记录' }}</span><button class="status-clear" @click="resetFilters">清空筛选</button></div>
      <div class="approval-status-table-scroll">
        <table class="approval-status-table">
          <thead>
            <tr><th scope="col">序号</th><th scope="col">标题</th><th scope="col">分类</th><th scope="col">流程状态</th><th scope="col">当前节点</th><th scope="col">发起人</th><th scope="col">当前处理人</th><th scope="col">发起时间</th><th scope="col">操作</th></tr>
            <tr class="approval-status-filters"><td></td><td><div class="status-search"><Search :size="14" /><input v-model="filters.title" aria-label="筛选标题" placeholder="标题或流程名称" /></div></td><td><select v-model="filters.category" aria-label="筛选分类" :disabled="loading"><option value="">全部分类</option><option v-for="item in categories" :key="item" :value="item">{{ item }}</option></select></td><td><select v-model="stage" aria-label="筛选流程状态"><option v-for="item in stages" :key="item.key" :value="item.key">{{ item.label }}</option></select></td><td><input v-model="filters.node" aria-label="筛选当前节点" /></td><td><input v-model="filters.applicant" aria-label="筛选发起人" /></td><td><input v-model="filters.handler" aria-label="筛选当前处理人" /></td><td><input v-model="filters.date" aria-label="筛选发起日期" type="date" /></td><td></td></tr>
          </thead>
          <tbody>
            <tr v-for="(record, index) in rows" :key="record.id" :data-record-id="record.id"><td>{{ (page - 1) * pageSize + index + 1 }}</td><td><button class="status-record-title" @click="emit('detail', record.id)">{{ record.title }}</button><small>{{ record.workflowName }}</small></td><td>{{ record.category }}</td><td><span :class="['status-stage-badge', record.stage]">{{ stageName(record.stage) }}</span></td><td>{{ record.currentNode || '—' }}</td><td>{{ record.applicant }}</td><td>{{ record.currentHandlers.join('、') || '—' }}</td><td>{{ displayDate(record.createdAt) }}</td><td><div class="status-row-actions"><button @click="emit('detail', record.id)">查看</button><button v-if="record.canHandle" @click="emit('handle', record.id)">去处理</button></div></td></tr>
            <tr v-if="!rows.length"><td colspan="9" class="approval-status-empty">{{ loading ? '正在加载审批记录…' : scope === 'copied' ? '暂无抄送给我的审批' : '暂无符合条件的审批记录' }}</td></tr>
          </tbody>
        </table>
      </div>
      <footer class="approval-status-pagination"><span>共 {{ filtered.length }} 条 · 每页 {{ pageSize }} 条</span><div><button aria-label="上一页" :disabled="page <= 1" @click="page--"><ChevronLeft :size="14" />上一页</button><span>{{ page }} / {{ pageCount }}</span><button aria-label="下一页" :disabled="page >= pageCount" @click="page++">下一页<ChevronRight :size="14" /></button></div></footer>
    </section>
  </main>
</template>
