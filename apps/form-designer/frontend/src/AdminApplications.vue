<script setup lang="ts">
import ResizableDetailDrawer from './ResizableDetailDrawer.vue'
import FileUploadField from './FileUploadField.vue'
import { backdropDismiss as vBackdropDismiss } from "@platform-ui/backdrop-dismiss.js"
import { computed, onMounted, ref, watch } from 'vue'
import { ChevronLeft, ChevronRight, ClipboardList, RefreshCw, Search, X } from '@lucide/vue'
import { listAllWorkflowRuns } from './api'
import type { WorkflowRunResult, WorkflowRunTask } from './types'

const applications = ref<WorkflowRunResult[]>([])
const loading = ref(false)
const error = ref('')
const search = ref('')
const workflowId = ref('')
const status = ref('')
const page = ref(1)
const pageSize = ref(10)
const selected = ref<WorkflowRunResult | null>(null)
const statuses: Record<string, string> = {
  pending: '处理中', pending_assignment: '待分配', completed: '已完成',
  rejected: '已拒绝', returned: '已退回', recalled: '已撤回',
}
const workflowOptions = computed(() => [...new Map(applications.value.map((run) => [run.workflowId, run.workflowName])).entries()])
const filtered = computed(() => {
  const query = search.value.trim().toLowerCase()
  return applications.value.filter((run) =>
    (!workflowId.value || run.workflowId === workflowId.value) &&
    (!status.value || run.status === status.value) &&
    (!query || [run.title, run.applicant, run.applicantUsername, run.workflowName, run.formSchema?.name, run.id, ...Object.values(run.values ?? {})]
      .some((value) => String(value ?? '').toLowerCase().includes(query))),
  )
})
const pageCount = computed(() => Math.max(1, Math.ceil(filtered.value.length / pageSize.value)))
const rows = computed(() => filtered.value.slice((page.value - 1) * pageSize.value, page.value * pageSize.value))
const range = computed(() => filtered.value.length ? `${(page.value - 1) * pageSize.value + 1}–${Math.min(page.value * pageSize.value, filtered.value.length)}` : '0')

async function refresh() {
  if (loading.value) return
  loading.value = true
  error.value = ''
  try {
    applications.value = await listAllWorkflowRuns()
    if (selected.value) selected.value = applications.value.find((run) => run.id === selected.value?.id) ?? null
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '读取申请记录失败'
  } finally { loading.value = false }
}
function date(value?: string) {
  if (!value) return '--'
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString('zh-CN', { hour12: false })
}
function valueText(value: unknown): string {
  if (Array.isArray(value)) return value.length ? value.join('、') : '--'
  return value === undefined || value === null || value === '' ? '--' : String(value)
}
function taskStatus(task: WorkflowRunTask) {
  return ({ pending: '处理中', waiting: '等待前序', unassigned: '待分配', completed: '已完成', rejected: '已拒绝', returned: '已退回', recalled: '已撤回', cancelled: '已取消' } as Record<string, string>)[task.status] ?? task.status
}
function handlers(task: WorkflowRunTask) {
  if (task.status === 'pending' && (task.executionMode === 'sequential' || (task.nodeType === 'approval' && (task.approvalMode ?? 'sequential') === 'sequential'))) {
    const index = task.activeAssigneeIndex ?? 0
    return `${task.assigneeNames[index] ?? task.assignees[index] ?? '未分配'}（第 ${index + 1}/${task.assignees.length} 位）`
  }
  return task.assigneeNames.join('、') || task.assignees.join('、') || '未分配'
}
function currentStep(run: WorkflowRunResult) {
  if (run.status !== 'pending' && run.status !== 'pending_assignment') return statuses[run.status] ?? run.status
  const task = run.tasks.find((item) => item.status === 'pending' || item.status === 'unassigned')
  return task ? `${task.nodeName} · ${handlers(task)}` : statuses[run.status]
}
function actionText(action: string) {
  return ({ agree: '同意', reject: '拒绝', save: '保存', transfer: '转交', countersign: '加签', return: '退回', recall: '收回', complete: '完成' } as Record<string, string>)[action] ?? action
}
watch([search, workflowId, status, pageSize], () => { page.value = 1 })
watch(pageCount, (count) => { page.value = Math.min(page.value, count) })
onMounted(() => { void refresh() })
</script>

<template>
  <section class="admin-applications" aria-label="全部申请记录">
    <header class="applications-heading"><div><h2>全部申请记录</h2><p>查看所有人员提交的申请及审批、执行进度</p></div><button class="applications-button" :disabled="loading" @click="refresh"><RefreshCw :size="14" />{{ loading ? '加载中…' : '刷新' }}</button></header>
    <div class="applications-filters">
      <label class="applications-search"><Search :size="15" /><input v-model="search" aria-label="搜索申请记录" placeholder="搜索申请人、标题或申请内容" /></label>
      <select v-model="workflowId" aria-label="按流程筛选"><option value="">全部流程</option><option v-for="[id, name] in workflowOptions" :key="id" :value="id">{{ name }}</option></select>
      <select v-model="status" aria-label="按状态筛选"><option value="">全部状态</option><option v-for="(name, key) in statuses" :key="key" :value="key">{{ name }}</option></select>
    </div>
    <p v-if="error" class="applications-error" role="alert">{{ error }}</p>
    <div class="applications-table-wrap">
      <table class="applications-table">
        <thead><tr><th>申请标题</th><th>所属流程</th><th>关联表单</th><th>申请人</th><th>状态</th><th>当前进度</th><th>提交时间</th><th>操作</th></tr></thead>
        <tbody>
          <tr v-for="run in rows" :key="run.id">
            <td><button class="applications-link" @click="selected = run">{{ run.title }}</button></td>
            <td>{{ run.workflowName }}<small>第 {{ run.workflowVersion }} 版</small></td>
            <td>{{ run.formSchema?.name || run.formId }}</td><td>{{ run.applicant }}</td>
            <td><span :class="['applications-status', run.status]">{{ statuses[run.status] || run.status }}</span></td>
            <td class="applications-progress">{{ currentStep(run) }}</td><td class="applications-date">{{ date(run.createdAt) }}</td>
            <td><button class="applications-link" @click="selected = run">查看详情</button></td>
          </tr>
          <tr v-if="!rows.length"><td colspan="8" class="applications-empty"><ClipboardList :size="26" /><span>{{ loading ? '正在读取申请记录…' : error ? '记录加载失败，请重试' : applications.length ? '没有符合条件的申请记录' : '暂无申请记录，提交申请后会显示在这里' }}</span></td></tr>
        </tbody>
      </table>
    </div>
    <footer class="applications-pagination"><span>共 {{ filtered.length }} 条申请记录</span><div><label>每页 <select v-model.number="pageSize"><option :value="10">10</option><option :value="20">20</option><option :value="50">50</option></select></label><span>{{ range }} / {{ filtered.length }}</span><button class="applications-button" aria-label="上一页" :disabled="page <= 1" @click="page--"><ChevronLeft :size="15" /></button><button class="applications-button" aria-label="下一页" :disabled="page >= pageCount" @click="page++"><ChevronRight :size="15" /></button></div></footer>

    <ResizableDetailDrawer v-if="selected" :open="Boolean(selected)" :suspended="false" @close="selected = null">
      <section class="applications-dialog" role="dialog" aria-modal="true" aria-labelledby="admin-application-title" tabindex="-1">
        <header><div><h2 id="admin-application-title">{{ selected.title }}</h2><p>{{ selected.workflowName }} · 第 {{ selected.workflowVersion }} 版</p></div><button class="applications-button" aria-label="关闭详情" @click="selected = null"><X :size="18" /></button></header>
        <div class="applications-dialog-body">
          <div class="application-meta"><span>申请人<b>{{ selected.applicant }}</b></span><span>状态<b>{{ statuses[selected.status] || selected.status }}</b></span><span>提交时间<b>{{ date(selected.createdAt) }}</b></span></div>
          <div class="application-current-step">当前进度：{{ currentStep(selected) }}</div>
          <h3>申请内容 · {{ selected.formSchema?.name || selected.formId }}</h3>
          <div v-if="selected.formSchema?.fields.length" class="application-field-grid">
            <div v-for="field in selected.formSchema.fields" :key="field.id" :class="['application-field', field.width]"><label>{{ field.label }}</label><FileUploadField v-if="field.type === 'image' || field.type === 'attachment'" :model-value="selected.values?.[field.id]" :field-id="field.id" :label="field.label" :image="field.type === 'image'" :run-id="selected.id" readonly /><p v-else>{{ valueText(selected.values?.[field.id] ?? field.defaultValue) }}</p></div>
          </div>
          <div v-else-if="Object.keys(selected.values ?? {}).length" class="application-field-grid"><div v-for="(value, key) in selected.values" :key="key" class="application-field"><label>{{ key }}</label><p>{{ valueText(value) }}</p></div></div>
          <p v-else class="applications-muted">没有申请内容</p>
          <template v-if="selected.matchedBranches.length"><h3>条件分支</h3><p v-for="branch in selected.matchedBranches" :key="branch.nodeId">{{ branch.conditionName }} → {{ branch.branchName }}</p></template>
          <h3>流程记录</h3>
          <ol v-if="selected.tasks.length" class="application-task-list">
            <li v-for="task in selected.tasks" :key="task.id">
              <div class="application-task-heading"><b>{{ task.nodeName }}</b><span :class="['applications-status', task.status]">{{ taskStatus(task) }}</span></div>
              <p class="applications-muted">{{ task.nodeType === 'approval' ? '审批人' : '执行人' }}：{{ handlers(task) }}<template v-if="task.branchPath.length"> · {{ task.branchPath.join(' / ') }}</template></p>
              <div v-for="(decision, index) in task.decisions" :key="index" class="application-decision"><span><b>{{ decision.displayName }}</b> · {{ actionText(decision.action) }}<template v-if="decision.action === 'reject' && decision.rejectBehavior"> · {{ decision.rejectBehavior === 'return' ? '退回发起人' : '结束流程' }}</template><time>{{ date(decision.createdAt) }}</time></span><p v-if="decision.comment">{{ decision.comment }}</p></div>
            </li>
          </ol><p v-else class="applications-muted">此申请没有审批或执行节点</p>
          <p class="applications-record-id">申请编号：{{ selected.id }}</p>
        </div>
        <footer><button class="applications-button" @click="selected = null">关闭</button></footer>
      </section>
    </ResizableDetailDrawer>
  </section>
</template>

<style scoped>
.admin-applications{display:flex;flex:1;min-height:0;flex-direction:column;background:#fff;color:#354b60}
.applications-heading{display:flex;justify-content:space-between;align-items:center;padding:20px 22px 14px}.applications-heading h2,.applications-dialog h2{margin:0;font-size:16px}.applications-heading p,.applications-dialog header p{margin:7px 0 0;color:#8996a5;font-size:12px}
.applications-button{display:inline-flex;align-items:center;justify-content:center;gap:7px;min-height:30px;padding:5px 10px;border:1px solid #dfe6ed;border-radius:5px;background:#fff;color:#526b80;font-size:12px;cursor:pointer}.applications-button:hover:not(:disabled){background:#f4f9ff;border-color:#a8ccec}button:disabled{opacity:.5;cursor:default}
.applications-filters{display:flex;flex-wrap:wrap;gap:10px;padding:0 22px 16px}.applications-search{display:flex;align-items:center;gap:8px;width:290px;padding:0 10px;border:1px solid #dfe6ed;border-radius:5px;color:#8996a5}.applications-search input{min-width:0;width:100%;height:32px;border:0;outline:0;background:transparent;font-size:12px}.applications-filters select,.applications-pagination select{height:34px;max-width:240px;padding:0 10px;border:1px solid #dfe6ed;border-radius:5px;background:#fff;color:#526b80;font-size:12px}.applications-error{margin:0 22px 14px;color:#c14040;font-size:12px}
.applications-table-wrap{flex:1;min-height:0;overflow:auto;border-top:1px solid #e7edf2}.applications-table{width:100%;border-collapse:collapse;font-size:12px;text-align:left}.applications-table th{position:sticky;top:0;z-index:1;background:#f7f9fb;color:#7a8b9c;font-weight:500;white-space:nowrap}.applications-table td,.applications-table th{padding:15px 16px;border-bottom:1px solid #edf1f5}.applications-table tr:hover td{background:#fbfdff}.applications-table td small{display:block;margin-top:5px;color:#98a6b4;font-size:10px}.applications-link{padding:0;border:0;background:transparent;color:#1681dc;cursor:pointer;text-align:left;font-size:12px}.applications-progress{min-width:170px;max-width:290px;line-height:1.7}.applications-date{white-space:nowrap;color:#8996a5}.applications-status{display:inline-block;white-space:nowrap;padding:4px 8px;border-radius:4px;background:#f1f4f7;color:#7c8c9b;font-size:11px}.applications-status.pending{background:#edf6ff;color:#2082d6}.applications-status.completed{background:#eaf8f0;color:#27975f}.applications-status.rejected,.applications-status.returned{background:#fff0ee;color:#cb6758}.applications-status.pending_assignment{background:#fff7e4;color:#a98130}
.applications-table .applications-empty{height:210px;text-align:center;color:#98a6b4}.applications-empty svg{display:block;margin:0 auto 14px}.applications-pagination{display:flex;justify-content:space-between;align-items:center;gap:12px;padding:14px 22px;color:#8d9baa;font-size:12px}.applications-pagination>div{display:flex;align-items:center;gap:12px}.applications-pagination select{height:29px}
.applications-overlay{position:fixed;inset:0;z-index:150;display:flex;justify-content:center;align-items:center;padding:24px;background:#20364b66}.applications-dialog{display:flex;flex-direction:column;width:760px;max-width:100%;max-height:90vh;border-radius:10px;background:#fff;box-shadow:0 15px 60px #162d4926;font-size:12px}.applications-dialog>header{display:flex;align-items:center;justify-content:space-between;padding:20px 24px;border-bottom:1px solid #e7edf2}.applications-dialog-body{overflow:auto;padding:20px 24px}.applications-dialog>footer{display:flex;justify-content:flex-end;padding:14px 24px;border-top:1px solid #e7edf2}.application-meta{display:flex;flex-wrap:wrap;gap:22px}.application-meta span{display:flex;flex-direction:column;gap:6px;color:#8d9baa}.application-meta b{color:#41586e;font-weight:500}.application-current-step{margin:18px 0;padding:12px;background:#f1f7fe;border-radius:5px;color:#397aae}.applications-dialog h3{margin:24px 0 14px;font-size:13px;color:#41586e}.application-field-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}.application-field.full{grid-column:1/-1}.application-field label{color:#8d9baa}.application-field p{margin:7px 0;line-height:1.7;white-space:pre-wrap;overflow-wrap:anywhere}.applications-muted{color:#8d9baa;line-height:1.7}.application-task-list{list-style:none;padding:0;margin:0}.application-task-list>li{padding:14px;border:1px solid #e7edf2;border-radius:6px;margin-bottom:10px}.application-task-heading{display:flex;justify-content:space-between;align-items:center;gap:10px}.application-task-heading b{font-weight:550}.application-decision{margin-top:9px;padding:10px;background:#f8fafc;border-radius:4px}.application-decision>span{display:flex;flex-wrap:wrap;align-items:center;gap:5px}.application-decision time{margin-left:auto;color:#98a6b4;font-size:10px}.application-decision p{margin:8px 0 0;white-space:pre-wrap;line-height:1.7}.applications-record-id{margin-top:24px;color:#a0acb8;font-size:10px;overflow-wrap:anywhere}
@media(max-width:700px){.applications-heading,.applications-dialog>header{padding:16px}.applications-filters{padding:0 16px 14px}.applications-search{width:100%}.applications-overlay{padding:12px}.applications-dialog-body{padding:16px}.applications-pagination{padding:12px;flex-wrap:wrap}.application-field-grid{grid-template-columns:1fr}.application-field.full{grid-column:auto}}
</style>
