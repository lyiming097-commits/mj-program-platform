<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { ArrowDown, ArrowUp, ChevronLeft, ChevronRight } from '@lucide/vue'
import { listApprovalRecords } from './api'
import type { ApprovalRecord, ApprovalRecordScope } from './types'
import { categoryLabel } from './workflow-categories'
import './approval-status.css'

const props = defineProps<{ scope: ApprovalRecordScope }>()
const emit = defineEmits<{ detail: [id: string]; handle: [id: string] }>()
const records = ref<ApprovalRecord[]>([])
const loading = ref(false)
const error = ref('')
const scope = computed(() => props.scope)
const emptyFilters = { title: '', summary: '', applicant: '', createdDate: '', node: '', arrivalDate: '', stage: '' }
const filters = ref({ ...emptyFilters })
const hasFilters = computed(() => Object.values(filters.value).some(Boolean))
const sortBy = ref<'createdAt' | 'taskArrivedAt'>('createdAt')
const descending = ref(true)
const page = ref(1)
const pageSize = 20
const scopes = [
  { key: 'pending', label: '待我处理', description: '展示当前用户需要处理的流程表单数据的汇总。' },
  { key: 'mine', label: '我创建的', description: '查看由我创建的审批及处理进度。' },
  { key: 'processed', label: '我已处理', description: '查看我已经处理过的审批记录。' },
  { key: 'copied', label: '抄送我的', description: '查看流程中抄送给我的审批。' },
] as const
const activeScope = computed(() => scopes.find(item => item.key === scope.value) ?? scopes[0])
const stages = [
  { key: 'approving', label: '待审批' }, { key: 'executing', label: '执行中' },
  { key: 'pending_assignment', label: '待分配' }, { key: 'returned', label: '已退回' },
  { key: 'completed', label: '已完成' }, { key: 'rejected', label: '已拒绝' }, { key: 'recalled', label: '已撤回' },
]
function inScope(record: ApprovalRecord, key: ApprovalRecordScope) {
  if (key === 'mine') return record.mine
  if (key === 'pending') return record.canHandle
  if (key === 'processed') return record.processed
  return record.copied === true
}
const contains = (value: string, query: string) => value.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase())
const filtered = computed(() => records.value.filter(record =>
  inScope(record, scope.value) &&
  contains(record.title, filters.value.title) &&
  contains([record.workflowName, categoryLabel(record.category), ...record.currentHandlers].join(' '), filters.value.summary) &&
  contains(record.applicant, filters.value.applicant) &&
  contains(record.currentNode, filters.value.node) &&
  (!filters.value.createdDate || localDate(record.createdAt) === filters.value.createdDate) &&
  (!filters.value.arrivalDate || localDate(record.taskArrivedAt) === filters.value.arrivalDate) &&
  (!filters.value.stage || record.stage === filters.value.stage)).sort((left, right) => {
    const leftTime = left[sortBy.value]
    const rightTime = right[sortBy.value]
    if (!leftTime || !rightTime) return Number(Boolean(rightTime)) - Number(Boolean(leftTime))
    return (Date.parse(leftTime) - Date.parse(rightTime)) * (descending.value ? -1 : 1)
  }))
const pageCount = computed(() => Math.max(1, Math.ceil(filtered.value.length / pageSize)))
const rows = computed(() => filtered.value.slice((page.value - 1) * pageSize, page.value * pageSize))
const stageName = (key: string) => stages.find(item => item.key === key)?.label ?? key
function localDate(value?: string | null) {
  if (!value) return ''
  const date = new Date(value)
  return Number.isFinite(date.getTime()) ? [date.getFullYear(), String(date.getMonth() + 1).padStart(2, '0'), String(date.getDate()).padStart(2, '0')].join('-') : ''
}
function displayDate(value?: string | null) { return value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '—' }
function sort(column: 'createdAt' | 'taskArrivedAt') {
  descending.value = sortBy.value === column ? !descending.value : true
  sortBy.value = column
}
function sortState(column: 'createdAt' | 'taskArrivedAt') {
  return sortBy.value === column ? descending.value ? 'descending' : 'ascending' : 'none'
}
async function refresh() {
  if (loading.value) return
  loading.value = true
  error.value = ''
  try {
    records.value = await listApprovalRecords('personal')
  } catch {
    error.value = '审批记录加载失败'
  } finally { loading.value = false }
}
function showError(message: string) { error.value = message }
watch([scope, filters, sortBy, descending], () => { page.value = 1 }, { deep: true })
watch(pageCount, count => { if (page.value > count) page.value = count })
function resetFilters() { filters.value = { ...emptyFilters } }

onMounted(() => { void refresh() })
defineExpose({ refresh, showError })
</script>

<template>
  <main class="approval-status-page">
    <section class="approval-status-table-panel" aria-label="审批流程记录" :aria-busy="loading">
      <header class="approval-status-heading">
        <h1>{{ activeScope.label }}</h1>
        <p>{{ activeScope.description }}</p>
      </header>
      <div v-if="error" class="approval-status-error" role="alert">{{ error }} <button type="button" class="status-tool" @click="refresh">重试</button></div>
      <div class="approval-status-table-scroll" tabindex="0" role="region" aria-label="审批记录表格">
        <table class="approval-status-table">
          <thead>
            <tr>
              <th scope="col">标题</th>
              <th scope="col">审批流程</th>
              <th scope="col">发起人</th>
              <th scope="col" :aria-sort="sortState('createdAt')"><button type="button" class="status-sort" @click="sort('createdAt')">发起时间 <component :is="sortState('createdAt') === 'ascending' ? ArrowUp : ArrowDown" :size="13" /></button></th>
              <th scope="col">当前节点</th>
              <th scope="col" :aria-sort="sortState('taskArrivedAt')"><button type="button" class="status-sort" @click="sort('taskArrivedAt')">任务到达时间 <component :is="sortState('taskArrivedAt') === 'ascending' ? ArrowUp : ArrowDown" :size="13" /></button></th>
              <th scope="col">状态</th>
              <th scope="col">操作</th>
            </tr>
            <tr class="approval-status-filters">
              <td><input v-model="filters.title" type="search" aria-label="筛选标题" placeholder="筛选标题" /></td>
              <td><input v-model="filters.summary" type="search" aria-label="筛选审批流程" placeholder="筛选审批流程" /></td>
              <td><input v-model="filters.applicant" type="search" aria-label="筛选发起人" placeholder="筛选发起人" /></td>
              <td><input v-model="filters.createdDate" type="date" aria-label="筛选发起日期" /></td>
              <td><input v-model="filters.node" type="search" aria-label="筛选当前节点" placeholder="筛选当前节点" /></td>
              <td><input v-model="filters.arrivalDate" type="date" aria-label="筛选任务到达日期" /></td>
              <td><select v-model="filters.stage" aria-label="筛选状态"><option value="">全部</option><option v-for="item in stages" :key="item.key" :value="item.key">{{ item.label }}</option></select></td>
              <td><button type="button" class="status-tool" :disabled="!hasFilters" @click="resetFilters">清空筛选</button></td>
            </tr>
          </thead>
          <tbody>
            <tr v-for="record in rows" :key="record.id" :data-record-id="record.id">
              <td><button type="button" class="status-record-title" @click="emit('detail', record.id)">{{ record.title }}</button></td>
              <td>{{ record.workflowName }}<small>{{ categoryLabel(record.category) }}<template v-if="record.currentHandlers.length"> · {{ record.currentHandlers.join('、') }}</template></small></td>
              <td>{{ record.applicant }}</td>
              <td>{{ displayDate(record.createdAt) }}</td>
              <td>{{ record.currentNode || '—' }}</td>
              <td>{{ displayDate(record.taskArrivedAt) }}</td>
              <td><span :class="['status-stage-badge', record.stage]">{{ stageName(record.stage) }}</span></td>
              <td><div class="status-row-actions"><button type="button" @click="emit('detail', record.id)">查看</button><button v-if="record.canHandle" type="button" @click="emit('handle', record.id)">去处理</button></div></td>
            </tr>
            <tr v-if="!rows.length"><td colspan="8" class="approval-status-empty">{{ loading ? '正在加载审批记录…' : hasFilters ? '没有符合筛选条件的记录' : '没有数据' }}</td></tr>
          </tbody>
        </table>
      </div>
      <footer v-if="filtered.length" class="approval-status-pagination"><span>共 {{ filtered.length }} 条 · 每页 {{ pageSize }} 条</span><div><button type="button" aria-label="上一页" :disabled="page <= 1" @click="page--"><ChevronLeft :size="14" />上一页</button><span>{{ page }} / {{ pageCount }}</span><button type="button" aria-label="下一页" :disabled="page >= pageCount" @click="page++">下一页<ChevronRight :size="14" /></button></div></footer>
    </section>
  </main>
</template>
