<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { Download, FileText, ImagePlus, LoaderCircle, Paperclip, Plus, RotateCcw, X } from '@lucide/vue'
import { readUploadedBlob, readUploadedFile, uploadFieldFile } from './api'
import type { FormValue, UploadedFileInfo } from './types'

const props = defineProps<{
  modelValue?: FormValue
  fieldId: string
  label: string
  image?: boolean
  workflowId?: string
  runId?: string
  taskId?: string
  recordId?: string
  readonly?: boolean
  disabled?: boolean
  previewLocal?: boolean
}>()
const emit = defineEmits<{ 'update:modelValue': [value: string[]]; busy: [value: boolean] }>()
const ids = computed(() => Array.isArray(props.modelValue) ? props.modelValue : [])
const picker = ref<HTMLInputElement | null>(null)
const files = ref<Record<string, UploadedFileInfo>>({})
const urls = ref<Record<string, string>>({})
const failed = ref<string[]>([])
const error = ref(''), progress = ref(''), working = ref(false), dragging = ref(false)
const downloadBusy = ref('')
const blocked = computed(() => props.readonly || props.disabled || working.value)
let generation = 0, disposed = false
const personalIds = new Set<string>()
const maxSize = 20 * 1024 * 1024

function formatSize(size: number) { return size < 1024 ? size + ' B' : size < 1024 * 1024 ? (size / 1024).toFixed(1) + ' KB' : (size / 1024 / 1024).toFixed(1) + ' MB' }
function revoke(id: string) { if (urls.value[id]) URL.revokeObjectURL(urls.value[id]); delete urls.value[id] }
async function infoFor(id: string) {
  if (personalIds.has(id)) return readUploadedFile(id)
  try { return await readUploadedFile(id, props.runId, props.recordId) }
  catch (cause) {
    // Re-editing mixes files from the old run with newly uploaded personal draft files.
    if (!props.workflowId || !props.runId) throw cause
    const info = await readUploadedFile(id)
    personalIds.add(id)
    return info
  }
}
async function blobFor(id: string, inline = false) {
  if (personalIds.has(id)) return readUploadedBlob(id, undefined, undefined, inline)
  try { return await readUploadedBlob(id, props.runId, props.recordId, inline) }
  catch (cause) {
    if (!props.workflowId || !props.runId) throw cause
    return readUploadedBlob(id, undefined, undefined, inline)
  }
}
async function loadFiles() {
  const current = ++generation
  failed.value = []
  const active = new Set(ids.value)
  for (const id of Object.keys(files.value)) if (!active.has(id)) { delete files.value[id]; revoke(id) }
  await Promise.all(ids.value.map(async id => {
    try {
      const info = files.value[id] ?? await infoFor(id)
      if (current !== generation || disposed) return
      files.value[id] = info
      if (info.isImage && !urls.value[id]) {
        const blob = await blobFor(id, true)
        if (current === generation && !disposed) urls.value[id] = URL.createObjectURL(blob)
      }
    } catch { if (current === generation && !disposed) failed.value.push(id) }
  }))
}
watch(() => [ids.value.join(','), props.runId, props.recordId], () => { void loadFiles() }, { immediate: true })

async function choose(list: FileList | File[] | null) {
  if (blocked.value || !list?.length) return
  error.value = ''
  const selected = Array.from(list)
  if (ids.value.length + selected.length > 10) { error.value = '每个字段最多上传 10 个文件'; return }
  if (selected.some(file => !file.size || file.size > maxSize)) { error.value = '不能上传空文件，单个文件不能超过 20 MB'; return }
  if (props.image && selected.some(file => !['image/png', 'image/jpeg', 'image/gif', 'image/webp'].includes(file.type))) {
    error.value = '请选择 PNG、JPG、GIF 或 WebP 图片'; return
  }
  working.value = true
  emit('busy', true)
  const nextIds = [...ids.value]
  try {
    for (let index = 0; index < selected.length; index++) {
      const file = selected[index]!
      progress.value = `正在上传 ${index + 1}/${selected.length}：${file.name}`
      const info = props.previewLocal
        ? { id: crypto.randomUUID().replaceAll('-', ''), name: file.name, size: file.size, contentType: file.type, isImage: ['image/png', 'image/jpeg', 'image/gif', 'image/webp'].includes(file.type) }
        : await uploadFieldFile(file, props.workflowId ?? '', props.fieldId, props.taskId ? props.runId : undefined, props.taskId)
      if (disposed) return
      files.value[info.id] = info
      personalIds.add(info.id)
      if (props.previewLocal) urls.value[info.id] = URL.createObjectURL(file)
      nextIds.push(info.id)
    }
  } catch (cause) { error.value = cause instanceof Error ? cause.message : '上传失败，请重新选择文件' }
  finally {
    if (!disposed) emit('update:modelValue', nextIds)
    working.value = false
    progress.value = ''
    emit('busy', false)
    if (picker.value) picker.value.value = ''
  }
}
function picked(event: Event) { void choose((event.target as HTMLInputElement).files) }
function drop(event: DragEvent) { dragging.value = false; void choose(event.dataTransfer?.files ?? null) }
function remove(id: string) { if (!blocked.value) emit('update:modelValue', ids.value.filter(value => value !== id)) }
async function download(id: string) {
  if (downloadBusy.value) return
  downloadBusy.value = id
  error.value = ''
  try {
    const local = props.previewLocal ? urls.value[id] : undefined
    const url = local ?? URL.createObjectURL(await blobFor(id))
    if (disposed) { if (!local) URL.revokeObjectURL(url); return }
    const link = document.createElement('a')
    link.href = url; link.download = files.value[id]?.name ?? '附件'
    document.body.append(link); link.click(); link.remove()
    if (!local) window.setTimeout(() => URL.revokeObjectURL(url), 1000)
  } catch (cause) { error.value = cause instanceof Error ? cause.message : '下载失败，请重试' }
  finally { downloadBusy.value = '' }
}
onBeforeUnmount(() => { disposed = true; generation++; Object.keys(urls.value).forEach(revoke); emit('busy', false) })
</script>

<template>
  <div class="file-upload-field" :class="{ 'file-upload-readonly': readonly }" :aria-busy="working" @dragover.prevent="!blocked && (dragging = true)" @dragleave.prevent="dragging = false" @drop.prevent="drop">
    <input v-if="!readonly" :id="`application-${fieldId}`" ref="picker" class="file-upload-input" type="file" multiple :accept="image ? 'image/png,image/jpeg,image/gif,image/webp' : undefined" :disabled="blocked" :aria-label="label + '选择文件'" @change="picked" />
    <button v-if="!readonly && ids.length < 10" type="button" :class="['file-upload-picker', { dragging }]" :disabled="blocked" @click="picker?.click()">
      <LoaderCircle v-if="working" :size="19" class="file-upload-spinner" /><ImagePlus v-else-if="image" :size="19" /><Paperclip v-else :size="19" />
      <span>{{ working ? '上传中…' : image ? '选择或拖拽图片' : '选择或拖拽附件' }}<small>{{ image ? 'PNG / JPG / GIF / WebP' : '支持多个文件' }} · 单个 ≤ 20 MB · 最多 10 个</small></span><Plus v-if="!working" :size="16" />
    </button>
    <p v-if="previewLocal && !readonly" class="file-upload-hint">当前为本机预览，文件不会提交；发布流程后可正式上传。</p>
    <ul v-if="ids.length" class="file-upload-list">
      <li v-for="id in ids" :key="id" class="file-upload-item">
        <a v-if="files[id]?.isImage && urls[id]" class="file-upload-thumbnail" :href="urls[id]" target="_blank" rel="noopener" :aria-label="'预览' + files[id]?.name"><img :src="urls[id]" :alt="files[id]?.name" /></a>
        <span v-else class="file-upload-file-icon"><FileText :size="21" /></span>
        <span class="file-upload-copy"><b :title="files[id]?.name">{{ files[id]?.name ?? (failed.includes(id) ? '文件读取失败' : '正在读取文件…') }}</b><small>{{ files[id] ? formatSize(files[id]!.size) : '' }}<template v-if="files[id]?.isImage && urls[id]"> · 点击图片可预览</template></small></span>
        <button v-if="failed.includes(id)" type="button" class="file-upload-action" :aria-label="'重试读取文件'" @click="loadFiles"><RotateCcw :size="15" /></button>
        <button v-if="files[id]" type="button" class="file-upload-action" :disabled="Boolean(downloadBusy)" :aria-label="'下载' + files[id]?.name" @click="download(id)"><Download :size="16" /></button>
        <button v-if="!readonly" type="button" class="file-upload-action file-upload-remove" :disabled="blocked" :aria-label="'移除' + (files[id]?.name ?? '文件')" @click="remove(id)"><X :size="16" /></button>
      </li>
    </ul>
    <p v-else-if="readonly" class="file-upload-hint">暂无{{ image ? '图片' : '附件' }}</p>
    <p v-if="progress" class="file-upload-hint" role="status">{{ progress }}</p>
    <p v-if="error" class="file-upload-error" role="alert">{{ error }}</p>
  </div>
</template>

<style scoped>
.file-upload-field{min-width:0;width:100%;font-size:12px}.file-upload-input{position:absolute!important;clip-path:inset(50%);width:1px!important;height:1px!important;overflow:hidden;padding:0!important;border:0!important}.file-upload-picker{display:flex;align-items:center;gap:10px;width:100%;min-height:66px;padding:12px 14px;text-align:left;border:1px dashed #bcd4ef;border-radius:7px;background:#f7faff;color:#2686e5;cursor:pointer}.file-upload-picker:hover,.file-upload-picker.dragging{border-color:#1688f4;background:#edf6ff}.file-upload-picker>span{display:flex;flex:1;flex-direction:column;gap:5px;font-size:13px}.file-upload-picker small,.file-upload-copy small{font-size:11px;color:#8999aa}.file-upload-picker:focus-visible,.file-upload-action:focus-visible,.file-upload-thumbnail:focus-visible{outline:2px solid #1688f4;outline-offset:2px}.file-upload-picker:disabled,.file-upload-action:disabled{opacity:.6;cursor:default}.file-upload-list{list-style:none;display:flex;flex-direction:column;gap:8px;margin:10px 0 0;padding:0}.file-upload-item{display:flex;align-items:center;gap:10px;min-width:0;padding:9px 10px;border:1px solid #e0e9f3;border-radius:6px;background:#fff}.file-upload-thumbnail,.file-upload-file-icon{display:flex;align-items:center;justify-content:center;flex:none;width:46px;height:46px;border-radius:5px;overflow:hidden;background:#eef6ff;color:#398bdc}.file-upload-thumbnail img{max-width:100%;max-height:100%;object-fit:contain}.file-upload-copy{display:flex;flex:1;min-width:0;flex-direction:column;gap:5px}.file-upload-copy b{font-weight:500;color:#33516b;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.file-upload-action{display:flex;flex:none;align-items:center;justify-content:center;width:28px;height:28px;padding:0;border:0;border-radius:4px;background:transparent;color:#4987c8;cursor:pointer}.file-upload-action:hover{background:#edf6ff}.file-upload-remove{color:#99a6b4}.file-upload-remove:hover{background:#fff1ef;color:#de6659}.file-upload-hint{margin:8px 0;color:#8999aa;font-size:11px;line-height:1.6}.file-upload-error{margin:8px 0;color:#d65b53;font-size:12px;line-height:1.6;overflow-wrap:anywhere}.file-upload-spinner{animation:upload-spin 1s linear infinite}@keyframes upload-spin{to{transform:rotate(360deg)}}
</style>
