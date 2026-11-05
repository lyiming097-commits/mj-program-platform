<script setup>
import AppSelect from "@/shared/AppSelect.vue";
import { computed, ref, shallowRef, watch } from "vue";
import { Camera, Download, ExternalLink, FileUp, MapPin, Paperclip, Pencil, Save, Send, Trash2, X } from "lucide-vue-next";

import {
  addAttachment,
  deleteAttachment,
  fetchAllProducts,
  fetchBootstrap,
  fetchSubmission,
  patchSubmission,
  resubmitSubmission,
} from "@/features/competitiveApi";
import { useProtectedAttachments } from "@/composables/useProtectedAttachments";
import { parameterTextCount } from "@/features/competitorParameters";
import { submissionPatch } from "@/features/submissionPayload";
import { regionOptionsWithLegacy, selectedProvince } from "@/features/regionOptions";
import AppConfirmDialog from "@/shared/AppConfirmDialog.vue";
import AppDrawer from "@/shared/AppDrawer.vue";
import ParameterTextEditor from "@/shared/ParameterTextEditor.vue";
import MediaPreviewDialog from "@/shared/MediaPreviewDialog.vue";
import StatusBadge from "@/shared/StatusBadge.vue";
import SearchableSelect from "@/shared/SearchableSelect.vue";
import DesktopLocationPicker from "./DesktopLocationPicker.vue";

const props = defineProps({ id: { type: String, default: "" } });
const emit = defineEmits(["close", "changed", "notify"]);
const draft = ref(null);
const products = shallowRef([]);
const settings = shallowRef([]);
const loading = shallowRef(false);
const saving = shallowRef(false);
const editing = shallowRef(false);
const locationOpen = shallowRef(false);
const pendingConfirm = shallowRef(null);
const { mediaPreview, downloadingId, previewAttachment, downloadAttachment } = useProtectedAttachments(
  (message) => emit("notify", message),
);
const open = computed(() => Boolean(props.id));
const canEdit = computed(() => draft.value?.status !== "已过期");
const settingOptions = computed(() => {
  const result = {};
  for (const setting of settings.value) {
    if (!setting.enabled) continue;
    (result[setting.group] ||= []).push(setting);
  }
  return result;
});
const regionOptions = computed(() => regionOptionsWithLegacy(
  settingOptions.value.region, draft.value?.region, draft.value?.city,
));

function selectRegion(region) {
  Object.assign(draft.value, selectedProvince(region));
}

async function load() {
  if (!props.id) return;
  loading.value = true;
  editing.value = false;
  try {
    const [submission, bootstrap, productRows] = await Promise.all([
      fetchSubmission(props.id),
      fetchBootstrap(),
      fetchAllProducts(),
    ]);
    draft.value = submission;
    settings.value = bootstrap.settings || [];
    products.value = productRows;
  } catch (reason) {
    emit("notify", reason.message || "采集详情加载失败");
  } finally {
    loading.value = false;
  }
}

function requestClose() {
  if (editing.value) pendingConfirm.value = { type: "close" };
  else emit("close");
}

async function save({ notify = true } = {}) {
  saving.value = true;
  try {
    draft.value = await patchSubmission(props.id, submissionPatch(draft.value));
    editing.value = false;
    if (notify) emit("changed", "采集资料已保存");
    return true;
  } catch (reason) {
    emit("notify", reason.message || "保存失败");
    return false;
  } finally {
    saving.value = false;
  }
}

async function resubmit() {
  if (editing.value && !(await save({ notify: false }))) return;
  saving.value = true;
  try {
    draft.value = await resubmitSubmission(props.id);
    editing.value = false;
    emit("changed", "已重新提交审核");
  } catch (reason) {
    emit("notify", reason.message || "重新提交失败");
  } finally {
    saving.value = false;
  }
}

async function uploadFiles(fileList, category) {
  const files = Array.from(fileList || []);
  if (!files.length) return;
  saving.value = true;
  try {
    for (const file of files) {
      if (draft.value.attachments.length >= 20) {
        emit("notify", "最多上传 20 个附件");
        break;
      }
      draft.value.attachments.push(await addAttachment(props.id, file, category));
    }
    emit("changed", "附件已上传");
  } catch (reason) {
    emit("notify", reason.message || "附件上传失败");
  } finally {
    saving.value = false;
  }
}

function removeAttachment(file) {
  pendingConfirm.value = { type: "delete-file", file };
}

async function confirmPendingAction() {
  const action = pendingConfirm.value;
  pendingConfirm.value = null;
  if (!action) return;
  if (action.type === "close") {
    editing.value = false;
    emit("close");
    return;
  }
  try {
    await deleteAttachment(props.id, action.file.id);
    draft.value.attachments = draft.value.attachments.filter((item) => item.id !== action.file.id);
    emit("changed", "附件已删除");
  } catch (reason) {
    emit("notify", reason.message || "附件删除失败");
  }
}

function selectLocation(value) {
  Object.assign(draft.value, {
    location: value.address,
    located: true,
    latitude: value.latitude,
    longitude: value.longitude,
    locationAccuracy: value.locationAccuracy,
    locatedAt: value.locatedAt,
    locationSource: "device",
  });
  locationOpen.value = false;
}

watch(() => props.id, load, { immediate: true });
</script>

<template>
  <AppDrawer :open="open" title="采集详情" width="820px" workspace @close="requestClose">
    <template v-if="draft" #header>
      <div class="custom-heading"><div class="submission-meta"><StatusBadge :status="draft.status" /><span>提交于 {{ draft.date }}</span><span v-if="canEdit" :class="{ active: editing }">{{ editing ? '编辑中' : '只读' }}</span></div><h2>{{ draft.brand }} · {{ draft.name }}</h2><p>{{ draft.model || '型号待补充' }} · {{ draft.region }}{{ draft.city ? ` / ${draft.city}` : '' }}</p></div>
      <button type="button" class="custom-close" title="关闭" aria-label="关闭" @click="requestClose"><X :size="19" /></button>
    </template>
    <div v-if="loading" class="empty-state">正在加载...</div>
    <div v-else-if="draft" class="submission-detail">
      <div v-if="draft.reviewComment" class="review-comment"><strong>审核意见</strong><p>{{ draft.reviewComment }}</p></div>

      <section class="detail-section region-detail-section"><header><b>01</b><h3>基础资料</h3><span>竞品与项目定位</span></header><div class="section-body"><div class="field-grid"><label><span>竞品品牌</span><input v-model="draft.brand" class="control" :disabled="!editing" /></label><label><span>产品名称</span><input v-model="draft.name" class="control" :disabled="!editing" /></label><label><span>产品型号</span><input v-model="draft.model" class="control" :disabled="!editing" /></label><label><span>单价</span><input v-model="draft.price" class="control" :disabled="!editing" /></label><label><span>关联我司产品</span><AppSelect v-model="draft.productId" class="control" :disabled="!editing"><option v-for="product in products" :key="product.id" :value="product.id">{{ product.name }} · {{ product.fullName || product.model || '-' }}</option></AppSelect></label><label><span>采集地区</span><SearchableSelect :model-value="draft.region" :options="regionOptions" option-value="value" :disabled="!editing" aria-label="采集地区" search-placeholder="搜索省份" @update:model-value="selectRegion" /></label><label><span>资料有效期</span><AppSelect v-model="draft.validity" class="control" :disabled="!editing"><option v-for="option in settingOptions.validity || []" :key="option.id" :value="option.label">{{ option.label }}</option></AppSelect></label><label><span>有效期至</span><input v-model="draft.expires" type="date" class="control" :disabled="!editing" /></label><label><span>提醒责任人</span><AppSelect v-model="draft.reminderOwner" class="control" :disabled="!editing"><option v-for="option in settingOptions.reminder_owner || []" :key="option.id" :value="option.label">{{ option.label }}</option></AppSelect></label><label><span>具体地点</span><button type="button" class="location-button" :disabled="!editing" @click="locationOpen = true"><MapPin :size="15" /><span>{{ draft.location || '打开地图选择地点' }}</span></button></label></div></div></section>

      <section class="detail-section"><header><b>02</b><h3>渠道与竞争判断</h3><span>沉淀现场口径</span></header><div class="section-body"><div class="field-grid"><label><span>经销商</span><input v-model="draft.dealer" class="control" :disabled="!editing" /></label><label><span>客户</span><input v-model="draft.customer" class="control" :disabled="!editing" /></label><label class="wide"><span>备注</span><textarea v-model="draft.note" class="control" :disabled="!editing" /></label><label><span>竞品优势</span><textarea v-model="draft.advantage" class="control" :disabled="!editing" /></label><label><span>竞品劣势</span><textarea v-model="draft.weakness" class="control" :disabled="!editing" /></label><label class="wide"><span>销售应对策略</span><textarea v-model="draft.tactic" class="control" :disabled="!editing" /></label></div></div></section>

      <section class="detail-section"><header><b>03</b><h3>竞品参数</h3><span>{{ parameterTextCount(draft.competitorParameterText) }} 项参数</span></header><div class="section-body"><ParameterTextEditor v-model="draft.competitorParameterText" :readonly="!editing" :rows="8" /></div></section>

      <section class="detail-section"><header><b>04</b><h3>照片 / 文件</h3><span>{{ draft.attachments.length }} 份资料</span></header><div class="section-body"><div class="attachment-list"><div v-for="file in draft.attachments" :key="file.id" class="attachment-row"><span class="file-icon"><Paperclip :size="16" /></span><div><strong>{{ file.name }}</strong><AppSelect v-model="file.category" class="control" :disabled="!editing"><option v-for="option in settingOptions.material_category || []" :key="option.id" :value="option.label">{{ option.label }}</option></AppSelect></div><button type="button" class="icon-btn" title="查看原件" :aria-label="`查看原件：${file.name}`" aria-haspopup="dialog" @click="previewAttachment(draft.id, file)"><ExternalLink :size="14" /></button><button type="button" class="icon-btn" title="下载" :aria-label="`下载：${file.name}`" :disabled="Boolean(downloadingId)" @click="downloadAttachment(draft.id, file)"><Download :size="14" /></button><button v-if="editing" class="icon-btn danger" type="button" title="删除附件" @click="removeAttachment(file)"><Trash2 :size="14" /></button></div><p v-if="!draft.attachments.length" class="muted empty-attachment">暂无附件资料</p></div><div v-if="editing" class="upload-buttons"><label class="upload-button"><Camera :size="15" />补充照片<input type="file" accept="image/*" multiple hidden @change="uploadFiles($event.target.files, '产品图片'); $event.target.value = ''" /></label><label class="upload-button"><FileUp :size="15" />补充文件<input type="file" multiple hidden @change="uploadFiles($event.target.files, '技术参数'); $event.target.value = ''" /></label></div></div></section>
    </div>
    <template v-if="draft" #footer><span class="footer-hint">{{ !canEdit ? '已过期记录不可补充' : editing ? '编辑完成后保存，或直接重新提交审核' : '当前为只读状态，点击编辑后可修改资料' }}</span><button v-if="canEdit && !editing" type="button" class="btn" @click="editing = true"><Pencil :size="14" />编辑</button><button v-if="editing" type="button" class="btn btn-primary" :disabled="saving" @click="save()"><Save :size="14" />保存</button><button v-if="['待补充', '已采纳'].includes(draft.status)" type="button" class="btn btn-primary" :disabled="saving" @click="resubmit"><Send :size="14" />重新提交</button></template>
  </AppDrawer>
  <MediaPreviewDialog :open="Boolean(mediaPreview)" :media="mediaPreview" @close="mediaPreview = null" @notify="emit('notify', $event)" />
  <DesktopLocationPicker v-if="locationOpen" :open="locationOpen" :initial="draft || {}" @close="locationOpen = false" @select="selectLocation" />
  <AppConfirmDialog :open="Boolean(pendingConfirm)" :title="pendingConfirm?.type === 'delete-file' ? '删除附件' : '放弃未保存修改'" :description="pendingConfirm?.type === 'delete-file' ? `确定删除附件“${pendingConfirm.file.name}”吗？删除后无法恢复。` : '关闭采集详情后，本次尚未保存的修改将丢失。'" :confirm-label="pendingConfirm?.type === 'delete-file' ? '删除' : '放弃并关闭'" :danger="pendingConfirm?.type === 'delete-file'" @cancel="pendingConfirm = null" @confirm="confirmPendingAction" />
</template>

<style scoped>
.custom-heading { min-width: 0; flex: 1; }.custom-heading h2,.custom-heading p { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }.custom-heading h2 { margin: 8px 0 0; color: #132b50; font-size: 18px; }.custom-heading p { margin: 5px 0 0; color: #667a98; font-size: 11px; }.custom-close { display: grid; width: 38px; height: 38px; flex: 0 0 auto; place-items: center; border: 1px solid #dbe5f0; border-radius: 7px; background: #fff; color: #63748d; }.custom-close:hover { background: #f2f6fb; }.submission-detail { display: grid; gap: 14px; }.submission-meta { display: flex; align-items: center; gap: 9px; color: #7b8da6; font-size: 10px; }.submission-meta span.active { color: #155eef; font-weight: 700; }.review-comment { border: 1px solid #fde68a; border-radius: 7px; background: #fffbeb; padding: 10px 12px; }.review-comment strong { color: #92400e; font-size: 11px; }.review-comment p { margin: 5px 0 0; color: #78350f; font-size: 12px; line-height: 1.5; }
.detail-section { overflow: hidden; border: 1px solid #dfe7f1; border-radius: 8px; background: #fff; }.detail-section > header { display: flex; min-height: 46px; align-items: center; gap: 11px; border-bottom: 1px solid #edf1f6; padding: 0 16px; }.detail-section > header b { color: #155eef; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 10px; }.detail-section > header h3 { margin: 0; color: #17345e; font-size: 13px; }.detail-section > header span { margin-left: auto; color: #8493a8; font-size: 10px; }.section-body { padding: 16px; }.detail-section label { display: block; }.detail-section label > span { display: block; margin-bottom: 6px; color: #63758f; font-size: 10px; font-weight: 700; }.field-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 13px 14px; }.wide { grid-column: 1 / -1; }.control { background: #f9fbfe; }.control:disabled { border-color: transparent; background: transparent; color: #334155; opacity: 1; }.location-button { display: flex; width: 100%; min-height: 36px; align-items: center; gap: 7px; border: 1px solid #d9e1ea; border-radius: 6px; background: #f9fbfe; padding: 0 11px; color: #475569; text-align: left; }.location-button:disabled { border-color: transparent; background: transparent; }.location-button span { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.region-detail-section { position: relative; z-index: 1; overflow: visible; }
.parameter-table { overflow: hidden; border: 1px solid #dfe7f1; border-radius: 7px; }.parameter-head, .parameter-row { display: grid; grid-template-columns: minmax(110px, .8fr) minmax(0, 1.2fr) 34px; gap: 8px; align-items: center; padding: 8px 10px; }.parameter-head { border-bottom: 1px solid #e8eef5; background: #f7f9fc; color: #71839d; font-size: 10px; font-weight: 700; }.parameter-row + .parameter-row { border-top: 1px solid #edf1f6; }.parameter-row .control { min-width: 0; }.remove-button { display: grid; width: 32px; height: 32px; place-items: center; border: 0; border-radius: 6px; background: transparent; color: #8796aa; }.remove-button:hover { background: #fff1f2; color: #dc2626; }.add-button { display: inline-flex; height: 34px; align-items: center; gap: 6px; margin-top: 10px; border: 1px solid #cad9ea; border-radius: 6px; background: #fff; padding: 0 11px; color: #155eef; font-size: 11px; font-weight: 700; }.empty-row { margin: 0; padding: 24px; text-align: center; }
.attachment-list { display: grid; gap: 8px; }.attachment-row { display: grid; grid-template-columns: 36px minmax(0,1fr) 34px 34px auto; gap: 8px; align-items: center; border: 1px solid #e4ebf3; border-radius: 7px; background: #fbfdff; padding: 9px 10px; }.file-icon { display: grid; width: 34px; height: 34px; place-items: center; border-radius: 6px; background: #edf4ff; color: #155eef; }.attachment-row > div { min-width: 0; }.attachment-row strong { display: block; overflow: hidden; margin-bottom: 5px; color: #203a5f; font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }.attachment-row .control { min-height: 30px; height: 30px; padding-block: 3px; font-size: 10px; }.upload-buttons { display: flex; gap: 8px; margin-top: 10px; }.upload-button { display: inline-flex; height: 36px; align-items: center; gap: 6px; border: 1px dashed #9dbdff; border-radius: 6px; background: #f7faff; padding: 0 12px; color: #155eef; cursor: pointer; font-size: 11px; font-weight: 700; }.empty-attachment { margin: 0; border: 1px dashed #d5e1ef; border-radius: 7px; padding: 24px; text-align: center; }.danger { color: #dc2626; }.muted { color: #94a3b8; font-size: 11px; }.footer-hint { min-width: 0; flex: 1; color: #8191a7; font-size: 10px; }
</style>
