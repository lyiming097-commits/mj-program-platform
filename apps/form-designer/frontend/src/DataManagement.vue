<script setup lang="ts">
import ResizableDetailDrawer from './ResizableDetailDrawer.vue'
import FileUploadField from './FileUploadField.vue'
import { backdropDismiss as vBackdropDismiss } from "@platform-ui/backdrop-dismiss.js"
import { computed, onMounted, ref, watch } from 'vue'
import {
  ArrowDownToLine, ArrowUpDown, Check, ChevronDown, ChevronRight, Columns3, Database,
  Download, FileInput, Filter, Maximize2, MoreHorizontal, Plus, RefreshCw, RotateCcw,
  Search, SlidersHorizontal, Trash2, Upload, X,
} from '@lucide/vue'
import { createFormRecord, deleteFormRecord, listFormRecords, restoreFormRecord, updateFormRecord } from './api'
import type { FormField, FormRecord, FormSchema, FormValues } from './types'
import AdminApplications from './AdminApplications.vue'

const props = defineProps<{ form: FormSchema; initialView?: 'applications' | 'records' }>()
const dataView = ref<'applications' | 'records'>(props.initialView ?? 'applications')
const records = ref<FormRecord[]>([])
const recycleRecords = ref<FormRecord[]>([])
const recycleMode = ref(false)
const loading = ref(false)
const searchText = ref('')
const filterOpen = ref(false)
const filterFieldId = ref('')
const filterText = ref('')
const columnMenuOpen = ref(false)
const selectedIds = ref<string[]>([])
const expandedIds = ref<string[]>([])
const sortBy = ref('createdAt')
const sortDirection = ref<'asc' | 'desc'>('desc')
const page = ref(1)
const pageSize = ref(10)
const dialogOpen = ref(false)
let draftSnapshot = ''
const editingRecordId = ref<string | null>(null)
const draft = ref({ title: '', applicant: '钟小康', values: {} as FormValues })
const error = ref('')
const notice = ref('')
const busy = ref(false)
const fileInput = ref<HTMLInputElement | null>(null)
const visibleColumnIds = ref<string[]>([])
const moreOpen = ref(false)

const columns = computed(() => [
  { id: '__title', label: '申请标题', sortable: true },
  { id: '__applicant', label: '申请人', sortable: true },
  ...props.form.fields.filter((field) => field.type !== 'description').map((field) => ({ id: field.id, label: field.label, sortable: true, field })),
])
const activeRecords = computed(() => recycleMode.value ? recycleRecords.value : records.value)
const visibleColumns = computed(() => columns.value.filter((column) => visibleColumnIds.value.includes(column.id)))
const filteredRecords = computed(() => {
  const query = searchText.value.trim().toLowerCase()
  const filterValue = filterText.value.trim().toLowerCase()
  const result = activeRecords.value.filter((record) => {
    const inSearch = !query || [record.title, record.applicant, ...Object.values(record.values)].some((value) => String(value ?? '').toLowerCase().includes(query))
    const fieldValue = filterFieldId.value ? String(record.values[filterFieldId.value] ?? '').toLowerCase() : ''
    const inFilter = !filterValue || fieldValue.includes(filterValue)
    return inSearch && inFilter
  })
  const direction = sortDirection.value === 'asc' ? 1 : -1
  return result.sort((a, b) => {
    const left = getValue(a, sortBy.value)
    const right = getValue(b, sortBy.value)
    return String(left).localeCompare(String(right), 'zh-CN', { numeric: true }) * direction
  })
})
const pageCount = computed(() => Math.max(1, Math.ceil(filteredRecords.value.length / pageSize.value)))
const pageRecords = computed(() => filteredRecords.value.slice((page.value - 1) * pageSize.value, page.value * pageSize.value))
const selectedVisible = computed(() => pageRecords.value.length > 0 && pageRecords.value.every((record) => selectedIds.value.includes(record.id)))
const selectedCount = computed(() => selectedIds.value.length)
const currentRange = computed(() => filteredRecords.value.length ? `${(page.value - 1) * pageSize.value + 1}-${Math.min(page.value * pageSize.value, filteredRecords.value.length)}` : '0')

function getValue(record: FormRecord, columnId: string): string {
  if (columnId === '__title') return record.title
  if (columnId === '__applicant') return record.applicant
  const value = record.values[columnId]
  if (Array.isArray(value)) return ['image', 'attachment'].includes(getField(columnId)?.type ?? '') ? (value.length ? `${value.length} 个文件` : '') : value.join('、')
  return value == null ? '' : String(value)
}
function getField(columnId: string): FormField | undefined { return props.form.fields.find((field) => field.id === columnId) }
function toggleSort(columnId: string) {
  if (sortBy.value === columnId) sortDirection.value = sortDirection.value === 'asc' ? 'desc' : 'asc'
  else { sortBy.value = columnId; sortDirection.value = 'asc' }
}
function toggleSelection(recordId: string) {
  selectedIds.value = selectedIds.value.includes(recordId) ? selectedIds.value.filter((id) => id !== recordId) : [...selectedIds.value, recordId]
}
function toggleVisibleSelection() {
  const visible = pageRecords.value.map((record) => record.id)
  selectedIds.value = selectedVisible.value ? selectedIds.value.filter((id) => !visible.includes(id)) : [...new Set([...selectedIds.value, ...visible])]
}
function toggleExpanded(recordId: string) {
  expandedIds.value = expandedIds.value.includes(recordId) ? expandedIds.value.filter((id) => id !== recordId) : [...expandedIds.value, recordId]
}
function toggleColumn(columnId: string) {
  visibleColumnIds.value = visibleColumnIds.value.includes(columnId) ? visibleColumnIds.value.filter((id) => id !== columnId) : [...visibleColumnIds.value, columnId]
}
async function refresh() {
  loading.value = true
  try {
    records.value = await listFormRecords(props.form.id)
    recycleRecords.value = await listFormRecords(props.form.id, true)
    error.value = ''
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '读取数据失败'
  } finally {
    loading.value = false
  }
}
function startNew() {
  editingRecordId.value = null
  draft.value = { title: '', applicant: '钟小康', values: Object.fromEntries(props.form.fields.map((field) => [field.id, field.defaultValue ?? ''])) }
  error.value = ''
  draftSnapshot = JSON.stringify(draft.value)
  dialogOpen.value = true
}
function editRecord(record: FormRecord) {
  editingRecordId.value = record.id
  draft.value = { title: record.title, applicant: record.applicant, values: { ...record.values } }
  error.value = ''
  draftSnapshot = JSON.stringify(draft.value)
  dialogOpen.value = true
}
async function saveRecord() {
  if (!draft.value.title.trim()) { error.value = '请填写申请标题'; return }
  for (const field of props.form.fields) {
    if (field.required && !String(draft.value.values[field.id] ?? '').trim()) { error.value = `请填写${field.label}`; return }
  }
  busy.value = true
  error.value = ''
  try {
    if (editingRecordId.value) {
      await updateFormRecord(props.form.id, { id: editingRecordId.value, formId: props.form.id, ...draft.value, createdAt: '', updatedAt: '' })
    } else {
      await createFormRecord(props.form.id, draft.value)
    }
    dialogOpen.value = false
    await refresh()
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '保存失败'
  } finally {
    busy.value = false
  }
}
async function removeRecord(record: FormRecord) {
  if (recycleMode.value) return
  try {
    await deleteFormRecord(props.form.id, record.id)
    selectedIds.value = selectedIds.value.filter((id) => id !== record.id)
    await refresh()
  } catch (cause) { error.value = cause instanceof Error ? cause.message : '删除失败' }
}
async function restoreRecord(record: FormRecord) {
  try { await restoreFormRecord(props.form.id, record.id); await refresh() }
  catch (cause) { error.value = cause instanceof Error ? cause.message : '恢复失败' }
}
async function removeSelected() {
  if (recycleMode.value) return
  const current = activeRecords.value.filter((record) => selectedIds.value.includes(record.id))
  for (const record of current) await deleteFormRecord(props.form.id, record.id)
  selectedIds.value = []
  await refresh()
}
function csvEscape(value: unknown) { return `"${String(value ?? '').replaceAll('"', '""')}"` }
function exportRecords() {
  const header = columns.value.map((column) => column.label)
  const lines = [header.map(csvEscape).join(','), ...filteredRecords.value.map((record) => columns.value.map((column) => csvEscape(getValue(record, column.id))).join(','))]
  const blob = new Blob([`\ufeff${lines.join('\r\n')}`], { type: 'text/csv;charset=utf-8' })
  downloadBlob(blob, `${props.form.name}-数据.csv`)
}
function exportJson() {
  const blob = new Blob([JSON.stringify(filteredRecords.value, null, 2)], { type: 'application/json' })
  downloadBlob(blob, `${props.form.name}-数据.json`)
}
function downloadBlob(blob: Blob, name: string) {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url; link.download = name; link.click()
  URL.revokeObjectURL(url)
  moreOpen.value = false
}
function importRecords(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  const reader = new FileReader()
  reader.onload = async () => {
    try {
      const data = JSON.parse(String(reader.result)) as Array<Partial<FormRecord>>
      if (!Array.isArray(data)) throw new Error('文件需为 JSON 记录数组')
      for (const row of data) {
        const title = String(row.title ?? row.values?.[props.form.fields[0]?.id] ?? '').trim()
        if (!title) continue
        await createFormRecord(props.form.id, { title, applicant: String(row.applicant ?? '钟小康'), values: Object.fromEntries(Object.entries(row.values ?? {}).map(([key, value]) => [key, String(value ?? '')])) })
      }
      await refresh()
      error.value = ''
    } catch (cause) { error.value = cause instanceof Error ? cause.message : '导入失败' }
    input.value = ''
  }
  reader.readAsText(file)
}
function applyFilter() { filterOpen.value = false; page.value = 1 }
function clearFilter() { filterFieldId.value = ''; filterText.value = ''; page.value = 1 }
function formatDate(value: string) {
  if (!value) return '--'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit' }).format(date)
}
function displayValue(record: FormRecord, columnId: string) {
  const value = getValue(record, columnId)
  if (!value) return '--'
  return value
}
function toggleRecycle() {
  recycleMode.value = !recycleMode.value
  selectedIds.value = []
  page.value = 1
}
function showToast(message: string) { notice.value = message; setTimeout(() => { if (notice.value === message) notice.value = '' }, 2400) }
function toggleFullscreen() {
  if (document.fullscreenElement) void document.exitFullscreen()
  else void document.documentElement.requestFullscreen()
}
watch(() => props.form.fields.map((field) => `${field.id}:${field.label}`).join('|'), () => {
  const available = new Set(columns.value.map((column) => column.id))
  visibleColumnIds.value = visibleColumnIds.value.filter((id) => available.has(id))
  visibleColumnIds.value.push(...columns.value.map((column) => column.id).filter((id) => !visibleColumnIds.value.includes(id)))
})
watch([searchText, filterFieldId, filterText], () => { page.value = 1 })
watch(filteredRecords, () => { if (page.value > pageCount.value) page.value = pageCount.value })
onMounted(async () => {
  visibleColumnIds.value = columns.value.map((column) => column.id)
  if (dataView.value === 'records') await refresh()
})
watch([dataView, () => props.form.id], () => {
  if (dataView.value !== 'records') return
  selectedIds.value = []
  expandedIds.value = []
  page.value = 1
  visibleColumnIds.value = columns.value.map((column) => column.id)
  void refresh()
})
function closeRecord() {
  if (busy.value) return
  if (JSON.stringify(draft.value) !== draftSnapshot && !window.confirm('记录尚未保存，确定放弃修改吗？')) return
  dialogOpen.value = false
}
</script>

<template>
  <div class="data-management-page">
    <nav class="data-management-tabs" aria-label="数据管理视图">
      <button :class="{ active: dataView === 'applications' }" @click="dataView = 'applications'">全部申请记录</button>
      <button :class="{ active: dataView === 'records' }" @click="dataView = 'records'">当前表单数据 · {{ form.name }}</button>
    </nav>
    <AdminApplications v-if="dataView === 'applications'" />
    <div v-else class="records-page">
    <Transition name="records-notice"><div v-if="notice" class="records-notice"><Check :size="15" />{{ notice }}</div></Transition>
    <div class="records-toolbar">
      <div class="records-primary-actions">
        <button v-if="!recycleMode" class="records-add-button" @click="startNew"><Plus :size="15" />新增</button>
        <label v-if="!recycleMode" class="records-tool-button import-tool"><Upload :size="14" />导入<input ref="fileInput" type="file" accept="application/json,.json" @change="importRecords" /></label>
        <button v-if="!recycleMode" class="records-tool-button" @click="exportRecords"><ArrowDownToLine :size="14" />导出</button>
        <button :class="['records-tool-button', { active: recycleMode }]" @click="toggleRecycle"><Database v-if="!recycleMode" :size="14" /><RotateCcw v-else :size="14" />{{ recycleMode ? '返回数据' : `回收站${recycleRecords.length ? ` (${recycleRecords.length})` : ''}` }}</button>
        <div class="toolbar-popover-anchor"><button class="records-tool-button" @click="moreOpen = !moreOpen"><MoreHorizontal :size="15" />更多</button><div v-if="moreOpen" class="records-popover more-popover"><button @click="exportJson"><Download :size="14" />导出 JSON</button><button v-if="selectedCount && !recycleMode" @click="removeSelected"><Trash2 :size="14" />删除所选（{{ selectedCount }}）</button></div></div>
      </div>
      <div class="records-secondary-actions">
        <button class="records-tool-button analysis-button" @click="showToast('分析视图正在准备中')"><SlidersHorizontal :size="14" />分析 <span>Beta</span></button>
        <label class="records-search"><Search :size="14" /><input v-model="searchText" placeholder="搜索" /><kbd>/</kbd></label>
        <div class="toolbar-popover-anchor"><button :class="['records-tool-button', { active: filterFieldId && filterText }]" @click="filterOpen = !filterOpen"><Filter :size="14" />筛选</button><div v-if="filterOpen" class="records-popover filter-popover"><strong>筛选记录</strong><select v-model="filterFieldId"><option value="">选择字段</option><option v-for="field in form.fields" :key="field.id" :value="field.id">{{ field.label }}</option></select><input v-model="filterText" placeholder="包含文字" @keydown.enter="applyFilter" /><div class="popover-actions"><button @click="clearFilter">清除</button><button class="popover-apply" @click="applyFilter">应用</button></div></div></div>
        <div class="toolbar-popover-anchor"><button class="records-tool-button" @click="columnMenuOpen = !columnMenuOpen"><Columns3 :size="14" />显示列</button><div v-if="columnMenuOpen" class="records-popover column-popover"><strong>显示列</strong><label v-for="column in columns" :key="column.id"><input type="checkbox" :checked="visibleColumnIds.includes(column.id)" :disabled="column.id === '__title'" @change="toggleColumn(column.id)" />{{ column.label }}</label></div></div>
        <button class="records-tool-button sort-button" @click="toggleSort(sortBy)"><ArrowUpDown :size="14" />排序</button>
        <button class="records-icon-button" title="刷新" aria-label="刷新" :disabled="loading" @click="refresh"><RefreshCw :size="15" /></button>
        <button class="records-icon-button" title="全屏" aria-label="全屏" @click="toggleFullscreen"><Maximize2 :size="15" /></button>
      </div>
    </div>
    <div v-if="recycleMode" class="recycle-banner"><RotateCcw :size="14" />回收站中的记录可恢复。</div>
    <div v-if="error" class="records-message"><span>{{ error }}</span><button @click="error = ''" aria-label="关闭提示"><X :size="14" /></button></div>
    <div class="records-table-wrap">
      <table class="records-table">
        <thead><tr>
          <th class="check-col"><input type="checkbox" aria-label="选择当前页" :checked="selectedVisible" @change="toggleVisibleSelection" /></th>
          <th class="expand-col"></th>
          <th v-for="column in visibleColumns" :key="column.id"><button class="table-sort" @click="toggleSort(column.id)">{{ column.label }}<ArrowUpDown v-if="column.sortable" :size="12" :class="{ sorted: sortBy === column.id }" /></button></th>
          <th class="actions-col">操作</th>
        </tr></thead>
        <tbody>
          <template v-for="record in pageRecords" :key="record.id">
            <tr :class="{ selected: selectedIds.includes(record.id) }">
              <td class="check-col"><input type="checkbox" :aria-label="`选择${record.title}`" :checked="selectedIds.includes(record.id)" @change="toggleSelection(record.id)" /></td>
              <td class="expand-col"><button class="expand-row-button" :aria-label="expandedIds.includes(record.id) ? '收起详情' : '展开详情'" @click="toggleExpanded(record.id)"><ChevronRight :size="15" :class="{ rotated: expandedIds.includes(record.id) }" /></button></td>
              <td v-for="column in visibleColumns" :key="column.id" class="data-cell" :title="displayValue(record, column.id)"><button v-if="column.id === '__title'" class="record-title-link" @click="editRecord(record)">{{ displayValue(record, column.id) }}</button><span v-else-if="column.id === '__applicant'" class="applicant-cell"><i>{{ record.applicant.slice(0, 1) }}</i>{{ record.applicant }}</span><span v-else-if="getField(column.id)?.type === 'date'" class="muted-cell">{{ displayValue(record, column.id) }}</span><button v-else-if="getField(column.id)?.type === 'attachment' || getField(column.id)?.type === 'image'" class="record-title-link attachment-cell" aria-label="查看文件" @click="editRecord(record)"><FileInput :size="13" />{{ displayValue(record, column.id) }}</button><span v-else-if="getField(column.id)?.type === 'select' || getField(column.id)?.type === 'radio'" class="value-tag">{{ displayValue(record, column.id) }}</span><span v-else :class="{ 'muted-cell': displayValue(record, column.id) === '--' }">{{ displayValue(record, column.id) }}</span></td>
              <td class="row-actions"><template v-if="recycleMode"><button @click="restoreRecord(record)">恢复</button></template><template v-else><button @click="editRecord(record)">详情</button><button class="danger-link" @click="removeRecord(record)">删除</button><button class="row-more" :aria-label="`更多${record.title}操作`" @click="toggleExpanded(record.id)">更多 <ChevronDown :size="13" /></button></template></td>
            </tr>
            <tr v-if="expandedIds.includes(record.id)" class="expanded-row"><td :colspan="visibleColumns.length + 3"><div><span>记录编号 {{ record.id.slice(0, 12) }}</span><span>提交时间 {{ formatDate(record.createdAt) }}</span><span>申请人 {{ record.applicant }}</span><button v-if="!recycleMode" @click="editRecord(record)">编辑记录</button></div></td></tr>
          </template>
          <tr v-if="!pageRecords.length"><td :colspan="visibleColumns.length + 3" class="empty-records"><Database :size="24" /><strong>{{ loading ? '加载中…' : recycleMode ? '回收站为空' : searchText || filterText ? '没有符合条件的记录' : '还没有提交记录' }}</strong><span v-if="!recycleMode && !searchText && !filterText">新增一条记录，或从表单开始收集数据。</span><button v-if="!recycleMode && !searchText && !filterText" class="records-add-button" @click="startNew"><Plus :size="14" />新增记录</button></td></tr>
        </tbody>
      </table>
    </div>
    <footer class="records-footer"><span>共 {{ filteredRecords.length }} 条记录</span><span v-if="selectedCount" class="selection-count">已选 {{ selectedCount }} 条 <button @click="selectedIds = []">清除</button></span><div class="pagination"><span>每页</span><select v-model.number="pageSize" @change="page = 1"><option :value="10">10</option><option :value="20">20</option><option :value="50">50</option></select><span>{{ currentRange }} / {{ filteredRecords.length }}</span><button aria-label="上一页" :disabled="page <= 1" @click="page--"><ChevronRight :size="14" class="previous-icon" /></button><button aria-label="下一页" :disabled="page >= pageCount" @click="page++"><ChevronRight :size="14" /></button></div></footer>

    <ResizableDetailDrawer v-if="dialogOpen" :open="Boolean(dialogOpen)" :suspended="busy" @close="closeRecord">
      <section class="record-dialog" role="dialog" aria-modal="true" :aria-label="editingRecordId ? '记录详情' : '新增记录'">
        <header><div><strong>{{ editingRecordId ? '记录详情' : '新增记录' }}</strong><span>{{ form.name }}</span></div><button class="records-icon-button" aria-label="关闭" @click="closeRecord"><X :size="18" /></button></header>
        <div class="record-dialog-content">
          <div class="record-dialog-field"><label>申请标题 <i>*</i></label><input v-model="draft.title" class="setting-input" placeholder="填写记录标题" /></div>
          <div class="record-dialog-field"><label>申请人</label><select v-model="draft.applicant" class="setting-input"><option v-for="person in ['钟小康', '张三', '李四', '王经理', '陈主管']" :key="person">{{ person }}</option></select></div>
          <div v-for="field in form.fields" :key="field.id" class="record-dialog-field"><label>{{ field.label }} <i v-if="field.required">*</i></label><div v-if="field.type === 'description'" class="record-readonly">{{ field.defaultValue || '--' }}</div><FileUploadField v-else-if="field.type === 'image' || field.type === 'attachment'" :model-value="draft.values[field.id]" :field-id="field.id" :label="field.label" :image="field.type === 'image'" :record-id="editingRecordId ?? undefined" readonly /><textarea v-else-if="field.type === 'textarea'" v-model="draft.values[field.id] as string" class="setting-input record-textarea" :placeholder="field.placeholder" rows="3"></textarea><select v-else-if="field.type === 'select' || field.type === 'radio'" v-model="draft.values[field.id]" class="setting-input"><option value="">{{ field.placeholder || '请选择' }}</option><option v-for="option in field.options" :key="option">{{ option }}</option></select><input v-else v-model="draft.values[field.id] as string" class="setting-input" :type="field.type === 'number' ? 'number' : field.type === 'date' ? 'date' : 'text'" :placeholder="field.placeholder" /></div>
          <p v-if="error" class="record-dialog-error">{{ error }}</p>
        </div>
        <footer><button class="records-tool-button" @click="closeRecord">取消</button><button class="records-add-button" :disabled="busy" @click="saveRecord"><Check :size="14" />{{ busy ? '保存中' : '保存' }}</button></footer>
      </section>
    </ResizableDetailDrawer>
  </div>
  </div>
</template>

<style scoped>
.data-management-page{height:100%;min-height:0;display:flex;flex-direction:column}
.data-management-tabs{display:flex;gap:24px;flex:none;padding:0 22px;background:#fff;border-bottom:1px solid #e7edf2}
.data-management-tabs button{padding:15px 0;border:0;border-bottom:2px solid transparent;background:none;color:#718296;font-size:12px}
.data-management-tabs button.active{border-bottom-color:#1688f4;color:#1688f4;font-weight:600}
.data-management-page>.records-page{flex:1;min-height:0}
</style>
