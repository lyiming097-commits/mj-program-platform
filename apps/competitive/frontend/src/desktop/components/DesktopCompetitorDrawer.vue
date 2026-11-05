<script setup>
import { computed, ref, shallowRef, watch } from "vue";
import { Download, ExternalLink, FileText, MapPin, Pencil, Save, Trash2, X } from "lucide-vue-next";

import {
  attachmentUrl,
  deleteCompetitor,
  fetchCompetitorDetail,
  productImageUrl,
  updateCompetitor,
} from "@/features/competitiveApi";
import { useProtectedAttachments } from "@/composables/useProtectedAttachments";
import {
  competitorDraft,
  competitorPayloadKey,
  competitorUpdatePayload,
} from "@/features/competitorPayload";
import { productArchiveFields } from "@/features/productArchiveFields";
import AppConfirmDialog from "@/shared/AppConfirmDialog.vue";
import AppDrawer from "@/shared/AppDrawer.vue";
import CompetitorEditForm from "@/shared/CompetitorEditForm.vue";
import CompetitorVersionSelect from "@/shared/CompetitorVersionSelect.vue";
import MediaPreviewDialog from "@/shared/MediaPreviewDialog.vue";
import ProductParameterTabs from "@/shared/ProductParameterTabs.vue";
import StatusBadge from "@/shared/StatusBadge.vue";
import DesktopLocationPreview from "./DesktopLocationPreview.vue";

const props = defineProps({ id: { type: String, default: "" }, access: { type: Object, required: true } });
const emit = defineEmits(["close", "deleted", "notify", "updated"]);
const detail = shallowRef(null);
const draft = ref(null);
const loading = shallowRef(false);
const versionLoading = shallowRef(false);
const saving = shallowRef(false);
const deleting = shallowRef(false);
const deleteOpen = shallowRef(false);
const editing = shallowRef(false);
const pendingDiscard = shallowRef(null);
const { mediaPreview, downloadingId, downloadAttachment } = useProtectedAttachments(
  (message) => emit("notify", message),
);
const error = shallowRef("");
const tab = shallowRef("company");
const originalPayloadKey = shallowRef("");
const tabs = [
  ["company", "竞品资料"],
  ["regions", "地区资料"],
  ["media", "富媒体资料"],
  ["history", "版本记录"],
];
const open = computed(() => Boolean(props.id));
const dirty = computed(() => Boolean(
  editing.value
  && draft.value
  && competitorPayloadKey(draft.value) !== originalPayloadKey.value,
));
const archiveFields = computed(() => productArchiveFields(detail.value?.product));
const companyFields = computed(() => detail.value ? archiveFields.value : []);
const latestSource = computed(() => detail.value?.regionSources?.[0] || null);

function hasCoordinates(item) {
  return item?.latitude != null
    && item?.longitude != null
    && Number.isFinite(Number(item.latitude))
    && Number.isFinite(Number(item.longitude));
}

function coordinateText(item) {
  if (!hasCoordinates(item)) return "";
  return `经度 ${Number(item.longitude).toFixed(6)} · 纬度 ${Number(item.latitude).toFixed(6)}`;
}

function accuracyText(item) {
  if (item?.locationAccuracy == null) return "地图选点";
  const accuracy = Number(item?.locationAccuracy);
  return Number.isFinite(accuracy) ? `定位精度约 ${Math.round(accuracy)} 米` : "地图选点";
}

function previewProductImage() {
  mediaPreview.value = {
    id: `product-${detail.value.product.id}`,
    name: `${detail.value.product.name} · 产品档案主图`,
    type: "image/jpeg",
    previewUrl: productImageUrl(detail.value.product.id, "preview"),
  };
}

function previewAttachment(item) {
  mediaPreview.value = {
    id: item.id,
    name: item.name,
    type: item.type,
    previewUrl: attachmentUrl(item.submissionId, item.id),
  };
}

async function load() {
  if (!props.id) { detail.value = null; return; }
  loading.value = true;
  error.value = "";
  tab.value = "company";
  editing.value = false;
  draft.value = null;
  pendingDiscard.value = null;
  try { detail.value = await fetchCompetitorDetail(props.id); }
  catch (reason) { error.value = reason.message || "竞品详情加载失败"; }
  finally { loading.value = false; }
}

async function switchVersion(versionId) {
  if (!versionId || versionId === detail.value?.selectedVersion?.id) return;
  versionLoading.value = true;
  try {
    detail.value = await fetchCompetitorDetail(props.id, versionId);
  } catch (reason) {
    emit("notify", reason.message || "竞品版本加载失败");
  } finally {
    versionLoading.value = false;
  }
}

function startEditing() {
  draft.value = competitorDraft(detail.value);
  originalPayloadKey.value = competitorPayloadKey(draft.value);
  tab.value = "company";
  editing.value = true;
}

function stopEditing() {
  editing.value = false;
  draft.value = null;
  originalPayloadKey.value = "";
}

function requestCancel() {
  if (dirty.value) pendingDiscard.value = { type: "cancel" };
  else stopEditing();
}

function requestClose() {
  if (dirty.value) pendingDiscard.value = { type: "close" };
  else emit("close");
}

function selectTab(nextTab) {
  if (nextTab === tab.value) return;
  if (dirty.value) {
    pendingDiscard.value = { type: "tab", tab: nextTab };
    return;
  }
  if (editing.value) stopEditing();
  tab.value = nextTab;
}

function confirmDiscard() {
  const action = pendingDiscard.value;
  pendingDiscard.value = null;
  stopEditing();
  if (action?.type === "close") emit("close");
  if (action?.type === "tab") tab.value = action.tab;
}

async function save() {
  if (!draft.value || !dirty.value) return;
  saving.value = true;
  try {
    const result = await updateCompetitor(props.id, competitorUpdatePayload(draft.value));
    detail.value = await fetchCompetitorDetail(
      props.id,
      result.release?.id || detail.value?.selectedVersion?.id || "",
    );
    stopEditing();
    emit("updated", result.competitor);
    emit("notify", "正式竞品已保存");
  } catch (reason) {
    emit("notify", reason.message || "正式竞品保存失败");
  } finally {
    saving.value = false;
  }
}

async function remove() {
  deleting.value = true;
  try {
    await deleteCompetitor(props.id);
    deleteOpen.value = false;
    emit("deleted", props.id);
    emit("notify", "竞品已删除");
    emit("close");
  } catch (reason) { emit("notify", reason.message || "删除失败"); }
  finally { deleting.value = false; }
}

watch(() => props.id, load, { immediate: true });
</script>

<template>
  <AppDrawer
    :open="open"
    :title="detail ? `${detail.competitor.brand} ${detail.competitor.name}` : '竞品详情'"
    :subtitle="detail ? `对应我司产品：${detail.product.name} · 更新时间 ${detail.competitor.updated} · 有效期 ${detail.competitor.expires}` : ''"
    width="1000px"
    workspace
    @close="requestClose"
  >
    <template v-if="detail && !editing" #actions>
      <button v-if="access.canReview" type="button" class="header-edit" @click="startEditing"><Pencil :size="15" />编辑竞品</button>
      <button v-if="access.canManage" type="button" class="header-delete" @click="deleteOpen = true"><Trash2 :size="15" />删除竞品</button>
    </template>
    <div v-if="loading" class="empty-state">正在加载竞品详情...</div>
    <div v-else-if="error" class="empty-state">{{ error }}</div>
    <div v-else-if="detail" class="detail-shell">
      <nav class="detail-tabs" aria-label="竞品资料分类"><button v-for="item in tabs" :key="item[0]" type="button" :class="{ active: tab === item[0] }" @click="selectTab(item[0])">{{ item[1] }}</button></nav>

      <div v-if="tab === 'company'" class="tab-content company-tab">
        <template v-if="editing && draft">
          <section class="edit-context"><div><span>关联我司产品</span><strong>{{ detail.product.name }}</strong></div><p>修改会直接更新正式竞品，并自动写入版本记录。</p></section>
          <form id="desktop-formal-competitor-edit" @submit.prevent="save"><CompetitorEditForm v-model="draft" :parameter-source="detail.parameterSource" /></form>
        </template>
        <template v-else>
        <div class="company-grid">
          <section class="detail-section comparison-section product-comparison">
            <header><h3>我司产品</h3></header>
            <dl class="info-grid"><template v-for="field in companyFields" :key="field[0]"><div v-if="field[2] !== 'parameter'"><dt>{{ field[0] }}</dt><dd>{{ field[1] || '-' }}</dd></div></template></dl>
            <div class="parameter-table product-parameter-table">
              <div class="section-bar"><h4>我司产品参数</h4><span>三类参数</span></div>
              <ProductParameterTabs :product="detail.product" />
            </div>
          </section>
          <section class="detail-section comparison-section competitor-comparison">
            <header><h3>竞品</h3><CompetitorVersionSelect :model-value="detail.selectedVersion?.id || ''" :versions="detail.versions || []" :loading="versionLoading" @update:model-value="switchVersion" /></header>
            <dl class="info-grid"><div><dt>品牌</dt><dd>{{ detail.competitor.brand || '-' }}</dd></div><div><dt>产品名称</dt><dd>{{ detail.competitor.name || '-' }}</dd></div><div><dt>型号</dt><dd>{{ detail.competitor.model || '-' }}</dd></div><div><dt>单价</dt><dd>{{ detail.competitor.price || '-' }}</dd></div><div><dt>经销商</dt><dd>{{ detail.competitor.dealer || '-' }}</dd></div><div><dt>客户</dt><dd>{{ latestSource?.customer || '-' }}</dd></div><div><dt>备注</dt><dd>{{ latestSource?.note || '-' }}</dd></div><div><dt>地区</dt><dd>{{ detail.competitor.regions.join('、') || '-' }}</dd></div><div><dt>有效期</dt><dd :class="{ expired: detail.competitor.status === '已过期' }">{{ detail.competitor.expires }}</dd></div></dl>
            <div class="parameter-table"><div class="section-bar"><h4>竞品参数</h4><span>{{ detail.parameters.length ? `${detail.parameters.length} 项参数` : '暂无竞品参数' }}</span></div><div v-if="detail.parameters.length" class="competitor-parameter-list"><article v-for="(item,index) in detail.parameters" :key="item.id"><b class="parameter-index">{{ index+1 }}</b><span class="parameter-value">{{ item.text }}</span><span class="current-status">当前生效</span></article></div><div v-else class="empty-state compact">暂无竞品参数</div></div>
          </section>
        </div>
        <section class="detail-section analysis-section"><header><h3>竞争分析</h3><span>有效期至 {{ detail.competitor.expires }}</span></header><div class="analysis-grid"><article><b>竞品优势</b><p>{{ detail.advantage || '-' }}</p></article><article><b>竞品劣势</b><p>{{ detail.weakness || '-' }}</p></article><article class="wide"><b>销售应对策略</b><p>{{ detail.tactic || '-' }}</p></article></div></section>
        </template>
      </div>

      <div v-else-if="tab === 'regions'" class="tab-content">
        <section class="detail-section">
          <header><h3>地区业务员资料</h3><span>{{ Math.max(detail.competitor.sources, detail.regionSources.length) }} 条来源</span></header>
          <div v-if="detail.regionSources.length" class="source-list">
            <article v-for="item in detail.regionSources" :key="item.id" class="source-card">
              <div class="source-map">
                <DesktopLocationPreview v-if="hasCoordinates(item)" :latitude="Number(item.latitude)" :longitude="Number(item.longitude)" />
                <div v-else class="source-map-empty"><MapPin :size="24" /><span>该来源未记录地图坐标</span></div>
              </div>
              <div class="source-content">
                <header><div><strong>{{ item.region }}{{ item.city }}</strong><span>采集人：{{ item.owner }}</span></div><StatusBadge :status="item.status" /></header>
                <div class="source-location"><MapPin :size="17" /><div><b>具体地点</b><p>{{ item.location || '未记录具体地点' }}</p><small v-if="hasCoordinates(item)">{{ coordinateText(item) }} · {{ accuracyText(item) }}</small><small v-else-if="item.location">仅记录地址，没有可展示的地图坐标</small></div></div>
                <dl><div><dt>价格</dt><dd>{{ item.price || '-' }}</dd></div><div><dt>经销商</dt><dd>{{ item.dealer || '-' }}</dd></div><div><dt>客户</dt><dd>{{ item.customer || '-' }}</dd></div><div><dt>采集时间</dt><dd>{{ item.date }}</dd></div><div class="wide"><dt>备注</dt><dd>{{ item.note || '-' }}</dd></div></dl>
              </div>
            </article>
          </div>
          <div v-else class="empty-state">暂无地区来源</div>
        </section>
      </div>

      <div v-else-if="tab === 'media'" class="tab-content"><section class="detail-section"><header><h3>资料包</h3><span>产品档案 + {{ detail.competitor.sources }} 条业务资料</span></header><div class="media-grid"><button v-if="detail.product.hasImage" type="button" class="media-item product-media-item" aria-haspopup="dialog" @click="previewProductImage"><img :src="productImageUrl(detail.product.id)" :alt="detail.product.name" /><div><b>产品档案主图</b><p>{{ detail.product.name }}</p></div></button><article v-for="item in detail.media" :key="item.id" class="media-item"><button type="button" class="media-primary" aria-haspopup="dialog" :aria-label="`预览 ${item.name}`" @click="previewAttachment(item)"><img v-if="item.type?.startsWith('image/')" :src="attachmentUrl(item.submissionId, item.id)" :alt="item.name" /><span v-else class="file-icon"><FileText :size="19" /></span><span class="media-copy"><b>{{ item.category }}</b><span>{{ item.name }}</span><small>{{ Math.max(1, Math.round(item.size / 1024)) }} KB</small></span></button><span class="media-actions"><button type="button" title="查看原件" aria-label="查看原件" aria-haspopup="dialog" @click="previewAttachment(item)"><ExternalLink :size="15" /></button><button type="button" title="下载" :aria-label="`下载：${item.name}`" :disabled="Boolean(downloadingId)" @click="downloadAttachment(item.submissionId, item)"><Download :size="15" /></button></span></article><div v-if="!detail.product.hasImage && !detail.media.length" class="empty-state media-empty">暂无富媒体资料</div></div></section></div>

      <div v-else class="tab-content"><section class="detail-section"><header><h3>版本记录</h3><span>{{ detail.history?.length || 0 }} 条操作记录</span></header><div class="history-list"><article v-for="(item, index) in detail.history || []" :key="item.id"><span class="timeline-dot" /><span v-if="index < detail.history.length - 1" class="timeline-line" /><div><div class="version-head"><b>{{ item.version }}</b><time>{{ item.date }}</time><em>{{ item.action }}</em></div><p>{{ item.note }}</p><small>{{ item.action === '人工编辑' ? `修改人：${item.changedBy} · 正式档案修改` : item.sourceSubmissionId ? `审核人：${item.changedBy} · 关联采集资料已归档` : '历史导入记录' }}</small></div></article><div v-if="!detail.history?.length" class="empty-state">暂无版本记录</div></div></section></div>
    </div>
    <template v-if="detail && editing" #footer><span class="footer-hint">保存后立即更新正式竞品和版本记录</span><button type="button" class="btn" :disabled="saving" @click="requestCancel"><X :size="14" />取消</button><button type="submit" form="desktop-formal-competitor-edit" class="btn btn-primary" :disabled="saving || !dirty"><Save :size="14" />{{ saving ? '保存中...' : '保存修改' }}</button></template>
  </AppDrawer>
  <AppConfirmDialog :open="deleteOpen" title="删除竞品？" description="删除后该竞品、关联采集和审核记录会立即隐藏，30 天后自动物理清理。" confirm-label="删除竞品" cancel-label="取消" danger @cancel="!deleting && (deleteOpen = false)" @confirm="remove" />
  <AppConfirmDialog :open="Boolean(pendingDiscard)" title="是否放弃修改" description="当前正式竞品有尚未保存的修改。" confirm-label="确认放弃" cancel-label="继续编辑" danger @cancel="pendingDiscard = null" @confirm="confirmDiscard" />
  <MediaPreviewDialog :open="Boolean(mediaPreview)" :media="mediaPreview" @close="mediaPreview = null" @notify="emit('notify', $event)" />
</template>

<style scoped>
.competitor-parameter-list{display:grid;gap:6px;padding:8px}.competitor-parameter-list article{display:grid;grid-template-columns:24px minmax(0,1fr) auto;align-items:start;gap:8px;border:1px solid #e8edf4;border-radius:6px;background:#f7f9fc;padding:7px}.competitor-parameter-list .parameter-index{display:grid;width:22px;height:22px;place-items:center;border-radius:50%;background:#e3edf9;color:#245a9e;font-size:9px;line-height:1}.competitor-parameter-list .parameter-value{min-width:0;color:#2f4665!important;font-size:10px;font-weight:500;line-height:1.55!important;white-space:pre-wrap;overflow-wrap:anywhere}.competitor-parameter-list .current-status{align-self:start;margin-top:1px;white-space:nowrap}.edit-context{display:flex;min-height:56px;align-items:center;justify-content:space-between;gap:16px;border:1px solid #bfdbfe;border-radius:8px;background:#eff6ff;padding:10px 14px}.edit-context div{display:flex;align-items:center;gap:10px}.edit-context span,.edit-context p{color:#64748b;font-size:10px}.edit-context strong{color:#1d4ed8;font-size:12px}.edit-context p{margin:0}.header-edit{display:inline-flex;height:36px;align-items:center;gap:6px;border:1px solid #bfdbfe;border-radius:7px;background:#eff6ff;padding:0 11px;color:#1d4ed8;font-size:11px;font-weight:700}.header-edit:hover{background:#dbeafe}.footer-hint{margin-right:auto;color:#64748b;font-size:11px}
.source-list{display:grid;gap:12px;padding:16px}.source-card{display:grid;min-height:250px;grid-template-columns:minmax(280px,34%) minmax(0,1fr);overflow:hidden;border:1px solid #dfe6ee;border-radius:8px;background:#fff}.source-map{min-height:250px;border-right:1px solid #dfe6ee;background:#eef3f8}.source-map :deep(.location-preview){height:100%;border-bottom:0}.source-map-empty{display:grid;height:100%;min-height:250px;place-content:center;gap:8px;color:#94a3b8;text-align:center}.source-map-empty svg{margin:auto;color:#7f94ae}.source-map-empty span{font-size:11px}.source-content{min-width:0;padding:14px}.source-content>header{display:flex;align-items:flex-start;justify-content:space-between;gap:12px;border-bottom:1px solid #edf1f5;padding-bottom:11px}.source-content>header strong,.source-content>header span{display:block}.source-content>header strong{color:#17345e;font-size:13px}.source-content>header span{margin-top:4px;color:#64748b;font-size:10px}.source-location{display:grid;grid-template-columns:28px minmax(0,1fr);gap:8px;border-bottom:1px solid #edf1f5;padding:12px 0;color:#2563eb}.source-location>svg{margin-top:2px}.source-location b,.source-location p,.source-location small{display:block}.source-location b{color:#64748b;font-size:10px}.source-location p{margin:4px 0 0;color:#17345e;font-size:12px;line-height:1.55;overflow-wrap:anywhere}.source-location small{margin-top:4px;color:#8493a8;font-size:9px}.source-content dl{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px 16px;margin:12px 0 0}.source-content dl .wide{grid-column:1/-1}.source-content dt{color:#94a3b8;font-size:9px}.source-content dd{margin:4px 0 0;color:#334155;font-size:11px;line-height:1.5;white-space:pre-wrap;overflow-wrap:anywhere}
.detail-shell { min-height: 520px; }.detail-tabs { position: sticky; z-index: 2; top: -20px; display: flex; gap: 5px; overflow-x: auto; border-bottom: 1px solid #dfe6ee; background: #eef3f8; margin: -20px -20px 14px; padding: 10px 20px; }.detail-tabs button { height: 34px; flex: 0 0 auto; border: 0; border-radius: 6px; background: transparent; padding: 0 13px; color: #64748b; font-size: 11px; font-weight: 700; }.detail-tabs button.active { background: #fff; color: #1d4ed8; box-shadow: 0 1px 3px rgba(15,23,42,.1); }.tab-content { display: grid; gap: 12px; }.company-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}.detail-section{overflow:hidden;border:1px solid #dfe6ee;border-radius:7px;background:#fff}.detail-section>header{display:flex;min-height:48px;align-items:center;justify-content:space-between;gap:10px;border-bottom:1px solid #dfe6ee;background:#fff;padding:0 14px}.detail-section h3{margin:0;font-size:12px}.detail-section>header>span{color:#64748b;font-size:9px}.info-grid{margin:0;padding:14px}.info-grid>div{display:grid;grid-template-columns:108px minmax(0,1fr);border:1px solid #edf1f5;border-bottom:0}.info-grid>div:first-child{border-radius:6px 6px 0 0}.info-grid>div:last-child{border-bottom:1px solid #edf1f5;border-radius:0 0 6px 6px}.info-grid dt,.info-grid dd{min-height:36px;padding:9px 10px}.info-grid dt{background:#f8fafc;color:#64748b;font-size:9px}.info-grid dd{overflow-wrap:anywhere;margin:0;color:#334155;font-size:10px;line-height:1.5;text-align:right;white-space:pre-wrap}.expired{color:#dc2626!important;font-weight:700}.parameter-table{margin:0 14px 14px;overflow:hidden;border:1px solid #dfe6ee;border-radius:6px}.section-bar{display:flex;min-height:36px;align-items:center;justify-content:space-between;border-bottom:1px solid #dfe6ee;background:#f8fafc;padding:0 10px}.section-bar h4{margin:0;font-size:10px}.section-bar span{color:#64748b;font-size:8px}.parameter-table table{width:100%;border-collapse:collapse;font-size:9px}.parameter-table th,.parameter-table td{border-bottom:1px solid #edf1f5;padding:7px;text-align:left}.current-status{border-radius:4px;background:#ecfdf5;padding:3px 5px;color:#047857;font-size:8px}.compact{min-height:80px}.analysis-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px;padding:12px}.analysis-grid article{border:1px solid #edf1f5;border-radius:6px;background:#f8fafc;padding:10px}.analysis-grid .wide{grid-column:1/-1}.analysis-grid b{font-size:10px}.analysis-grid p{margin:5px 0 0;color:#475569;font-size:11px;line-height:1.55;white-space:pre-wrap}.region-table{min-width:920px}.media-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:9px;padding:12px}.media-item{display:flex;min-width:0;min-height:100px;align-items:center;gap:9px;border:1px solid #dfe6ee;border-radius:6px;background:#fbfdff;padding:9px;color:inherit;text-align:left;text-decoration:none}.media-item>img{width:78px;height:72px;flex:0 0 auto;border:1px solid #dfe6ee;border-radius:5px;object-fit:cover}.file-icon{display:grid;width:42px;height:42px;flex:0 0 auto;place-items:center;border-radius:6px;background:#eff6ff;color:#2563eb}.media-item>div{min-width:0;flex:1}.media-item b,.media-item p,.media-item small{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.media-item b{font-size:10px}.media-item p{margin:4px 0;color:#64748b;font-size:9px}.media-item small{color:#2563eb;font-size:8px}.media-actions{display:flex;flex-direction:column;gap:5px}.media-actions a{display:grid;width:27px;height:27px;place-items:center;border:1px solid #dfe6ee;border-radius:5px;background:#fff;color:#475569}.media-empty{grid-column:1/-1}.history-list{padding:14px}.history-list article{position:relative;display:grid;grid-template-columns:18px 1fr;gap:8px;padding-bottom:18px}.timeline-dot{position:relative;z-index:1;width:11px;height:11px;margin-top:4px;border:3px solid #dbeafe;border-radius:50%;background:#2563eb}.timeline-line{position:absolute;top:13px;bottom:-4px;left:5px;width:1px;background:#dbe5f0}.version-head{display:flex;align-items:center;gap:7px}.version-head b{font-size:10px}.version-head time{color:#64748b;font-size:9px}.version-head em{border-radius:9px;background:#ecfdf5;padding:2px 6px;color:#047857;font-size:8px;font-style:normal}.history-list article p{margin:7px 0 4px;border-radius:5px;background:#f8fafc;padding:8px;color:#475569;font-size:10px;line-height:1.5}.history-list article small{color:#94a3b8;font-size:8px}.header-delete{display:inline-flex;height:36px;align-items:center;gap:6px;border:1px solid #fecdd3;border-radius:7px;background:#fff;padding:0 11px;color:#e11d48;font-size:11px;font-weight:700}.header-delete:hover{background:#fff1f2}
.detail-shell{height:100%;min-height:0;overflow-y:auto}
.detail-tabs{top:0;gap:4px;margin:-16px -16px 12px;background:#eef3f8;padding:12px 16px}
.detail-tabs button{height:36px;border-radius:8px;background:transparent;padding:0 16px;color:#62738a;font-size:12px;font-weight:500;transition:background .2s ease,color .2s ease,box-shadow .2s ease}
.detail-tabs button:hover{background:rgba(255,255,255,.6);color:#17345e}
.detail-tabs button.active{background:#fff;color:#132b50;font-weight:700;box-shadow:0 1px 3px rgba(15,23,42,.12)}
.detail-section{border-radius:8px}
.detail-section>header{min-height:48px;background:#fbfdff;padding:0 16px}
.detail-section h3{color:#132b50;font-size:13px;font-weight:700}
.detail-section>header>span{font-size:10.5px}
.info-grid{padding:16px}
.info-grid>div{grid-template-columns:108px minmax(0,1fr)}
.info-grid dt,.info-grid dd{min-height:40px;padding:10px 12px}
.info-grid dt{background:#f7f9fc;font-size:11px}
.info-grid dd{color:#17345e;font-size:12px;font-weight:500;line-height:20px}
.parameter-table{margin:0 16px 16px;border-radius:8px}
.section-bar{min-height:40px;padding:0 12px}
.section-bar h4{color:#4e6687;font-size:11px;font-weight:600}
.section-bar span{font-size:10.5px}
.parameter-table table{font-size:11px}
.parameter-table thead{background:#f7f9fc;color:#4e6687}
.parameter-table th,.parameter-table td{padding:12px;color:#26466f;line-height:20px}
.parameter-table th{font-weight:600}
.current-status{padding:4px 7px;font-size:9.5px}
.compact{min-height:104px;font-size:12px}
.analysis-grid{gap:12px;padding:16px}
.analysis-grid article{border-radius:8px;padding:16px}
.analysis-grid b{color:#64748b;font-size:11px}
.analysis-grid p{margin-top:8px;color:#17345e;font-size:12px;line-height:24px}
.region-table{min-width:920px;font-size:11px}
.region-table th,.region-table td{padding:12px;line-height:20px}
.media-grid{gap:12px;padding:16px}
.media-item{min-height:112px;gap:12px;border-radius:8px;padding:12px}
.media-item:hover{border-color:#93c5fd;background:#eff6ff4d}
.media-item>img{width:96px;height:80px;border-radius:8px}
.file-icon{width:44px;height:44px;border-radius:8px}
.media-item b{font-size:12px}
.media-item p{margin:4px 0;font-size:10.5px;line-height:20px}
.media-item small{margin-top:8px;font-size:10px}
.media-actions button{width:32px;height:32px;border-radius:6px}
.history-list{padding:20px}
.history-list article{grid-template-columns:20px 1fr;gap:12px;padding-bottom:24px}
.timeline-dot{width:12px;height:12px;margin-top:6px}
.timeline-line{top:12px;bottom:0;left:5px}
.version-head{gap:8px}
.version-head b{color:#17345e;font-size:12px}
.version-head time{font-size:10.5px}
.version-head em{border-radius:10px;padding:2px 8px;font-size:9.5px}
.history-list article p{margin:8px 0 6px;border-radius:8px;padding:12px;font-size:11px;line-height:20px}
.history-list article small{font-size:10px}
.tab-content>.detail-section>.table-wrap{overflow-x:auto}
.tab-content>.detail-section>.empty-state,.media-empty{min-height:180px;font-size:12px}
.company-grid{grid-template-rows:auto auto auto;column-gap:12px;row-gap:0}.company-grid>.comparison-section{display:grid;grid-row:1/span 3;grid-template-rows:subgrid}.product-comparison{grid-column:1}.competitor-comparison{grid-column:2}.product-parameter-table>:deep(.product-parameter-tabs){padding:10px}.product-parameter-table>:deep(.parameter-tab-panel){padding-top:10px}
.parameter-table table{table-layout:fixed}.parameter-index-column{width:68px}.parameter-status-column{width:92px}.parameter-table th{white-space:nowrap}.parameter-table tbody tr:nth-child(even){background:#fbfdff}.parameter-table tbody tr:hover{background:#f4f8fd}.parameter-table td{vertical-align:top}.parameter-index{text-align:center!important}.parameter-index b{display:inline-grid;width:24px;height:24px;place-items:center;border-radius:50%;background:#e6eef9;color:#245a9e;font-size:10px}.parameter-value{color:#385373!important;line-height:24px!important;white-space:pre-wrap;overflow-wrap:anywhere}.parameter-status{text-align:center!important;white-space:nowrap}.current-status{display:inline-flex;align-items:center;justify-content:center;white-space:nowrap}
.product-media-item{width:100%;cursor:pointer;font:inherit}.media-primary{display:flex;min-width:0;flex:1;align-items:center;gap:9px;border:0;background:transparent;padding:0;color:inherit;text-align:left;cursor:pointer;font:inherit}.media-primary>img{width:96px;height:80px;flex:0 0 auto;border:1px solid #dfe6ee;border-radius:8px;object-fit:cover}.media-copy{min-width:0;flex:1}.media-copy>span{display:block;overflow:hidden;margin:4px 0;color:#64748b;font-size:10.5px;line-height:20px;text-overflow:ellipsis;white-space:nowrap}.media-actions button{display:grid;width:32px;height:32px;place-items:center;border:1px solid #dfe6ee;border-radius:6px;background:#fff;color:#475569}.media-primary:focus-visible,.product-media-item:focus-visible,.media-actions button:focus-visible{outline:2px solid #3b82f6;outline-offset:2px}
</style>
