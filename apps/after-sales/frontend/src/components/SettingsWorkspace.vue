<script setup>
import { computed, onMounted, reactive, ref, watch } from "vue";
import {
  ClipboardCheck,
  Gift,
  LoaderCircle,
  Plus,
  Save,
  ShieldCheck,
  Trash2,
} from "@lucide/vue";
import AdminPermissionSettings from "@/components/AdminPermissionSettings.vue";
import GlobalNotice from "@/components/GlobalNotice.vue";
import RewardCatalogSettings from "@/components/RewardCatalogSettings.vue";
import { serviceApi } from "@/serviceApi";
import {
  DEFAULT_PROVIDER_TAGS,
  notifyProviderTagsUpdated,
  readProviderTags,
  SETTINGS_STORAGE_KEY,
} from "@/data/providerTagLibrary";

const props = defineProps({
  initialTab: { type: String, default: "tags" },
});
const emit = defineEmits(["dirty-change", "confirm-open-change", "saved", "tab-request"]);
const tabs = [
  { id: "tags", label: "安装人员标签库", icon: ClipboardCheck },
  { id: "prizes", label: "实物奖励", icon: Gift },
  { id: "admin", label: "人员权限", icon: ShieldCheck },
];
const tabIds = new Set(tabs.map((tab) => tab.id));
const activeTab = ref(tabIds.has(props.initialTab) ? props.initialTab : "tags");
const success = ref("");
const error = ref("");
const adminDirty = ref(false);
const prizeDirty = ref(false);
const localSnapshot = ref("");
const tagSaving = ref(false);

const settings = reactive({
  tags: readProviderTags(),
});

function serializeSettings() {
  return JSON.stringify(settings);
}

localSnapshot.value = serializeSettings();

const localDirty = computed(() => serializeSettings() !== localSnapshot.value);
const dirty = computed(() => localDirty.value || adminDirty.value || prizeDirty.value);

function showSuccess(message) {
  success.value = message;
  window.setTimeout(() => { if (success.value === message) success.value = ""; }, 2600);
}

function selectTab(tabId) {
  if (tabIds.has(tabId) && tabId !== activeTab.value) emit("tab-request", tabId);
}

function addTag() { settings.tags.push(""); }

function removeTag(index) {
  if (settings.tags.length <= 1) return;
  settings.tags.splice(index, 1);
}

function normalizeBeforeSave() {
  const tags = settings.tags.map((item) => String(item || "").trim()).filter(Boolean);
  settings.tags = tags.length ? tags : [...DEFAULT_PROVIDER_TAGS];
}

async function loadProviderTags() {
  try {
    const response = await serviceApi.providerTagCatalog();
    const tags = Array.isArray(response?.items) ? response.items : [];
    if (tags.length) settings.tags = tags.map((item) => String(item).trim()).filter(Boolean);
    localSnapshot.value = serializeSettings();
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : "安装人员标签加载失败";
  }
}

async function saveDraft(message = "安装人员标签库已保存") {
  if (tagSaving.value) return;
  normalizeBeforeSave();
  tagSaving.value = true;
  error.value = "";
  try {
    const response = await serviceApi.updateProviderTagCatalog({ names: settings.tags });
    const tags = Array.isArray(response?.items) ? response.items : settings.tags;
    settings.tags = tags.map((item) => String(item).trim()).filter(Boolean);
    try { window.localStorage.setItem(SETTINGS_STORAGE_KEY, serializeSettings()); } catch (_reason) { /* server remains source of truth */ }
    localSnapshot.value = serializeSettings();
    notifyProviderTagsUpdated(settings.tags);
    showSuccess(message);
    emit("saved", { settings: JSON.parse(localSnapshot.value), tags: settings.tags });
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : "安装人员标签保存失败";
  } finally {
    tagSaving.value = false;
  }
}

function handleAdminDirty(value) {
  adminDirty.value = Boolean(value);
  emit("dirty-change", dirty.value);
}

function handleAdminConfirmOpen(value) { emit("confirm-open-change", Boolean(value)); }
function handleAdminSaved(payload) { emit("saved", payload); }

watch(dirty, (value) => emit("dirty-change", value), { immediate: true });
watch(() => props.initialTab, (value) => {
  const nextTab = tabIds.has(value) ? value : "tags";
  if (activeTab.value === nextTab) return;
  if (activeTab.value === "tags" && localDirty.value) {
    settings.tags = JSON.parse(localSnapshot.value).tags;
  }
  if (activeTab.value === "admin") adminDirty.value = false;
  activeTab.value = nextTab;
});

onMounted(() => { void loadProviderTags(); });
</script>

<template>
  <div class="as-page as-settings-page">
    <GlobalNotice v-model:error="error" v-model:success="success" />

    <nav class="as-settings-tabs as-mall-tabbar" role="tablist" aria-label="设置页签"><button v-for="tab in tabs" :key="tab.id" type="button" role="tab" :aria-selected="activeTab === tab.id" :class="{ active: activeTab === tab.id }" @click="selectTab(tab.id)"><component :is="tab.icon" />{{ tab.label }}</button></nav>

    <section v-show="activeTab === 'tags'" class="as-settings-panel"><div class="as-settings-panel-head"><div><h2>安装人员标签库</h2><p>保存后同步到服务团队筛选和微信小程序的服务档案能力选择。</p></div></div><div class="as-settings-section"><div class="as-settings-subhead"><h3>能力标签</h3><span>{{ settings.tags.length }} 个</span></div><div class="as-settings-tag-editor"><div v-for="(_tag, index) in settings.tags" :key="index" class="as-settings-tag-row"><input v-model="settings.tags[index]" :aria-label="`安装人员标签 ${index + 1}`" placeholder="输入能力标签"><button type="button" class="as-icon-button" title="删除标签" aria-label="删除标签" :disabled="settings.tags.length <= 1 || tagSaving" @click="removeTag(index)"><Trash2 /></button></div></div><div class="as-settings-actions as-settings-actions--left"><button type="button" class="as-button as-button--secondary" :disabled="tagSaving" @click="addTag"><Plus />新增标签</button></div></div><div class="as-settings-actions"><button type="button" class="as-button as-button--primary" :disabled="tagSaving" @click="saveDraft('安装人员标签库已保存')"><LoaderCircle v-if="tagSaving" class="as-spin" /><Save v-else />{{ tagSaving ? '保存中...' : '保存标签库' }}</button></div></section>

    <RewardCatalogSettings :active="activeTab === 'prizes'" v-show="activeTab === 'prizes'" @dirty-change="prizeDirty = Boolean($event)" />
    <section v-if="activeTab === 'admin'" class="as-settings-admin-tab"><AdminPermissionSettings @dirty-change="handleAdminDirty" @confirm-open-change="handleAdminConfirmOpen" @saved="handleAdminSaved" /></section>
  </div>
</template>

<style scoped>
.as-settings-page { display: flex; max-width: 1680px; min-height: calc(100vh - 110px); flex-direction: column; padding-top: 0; padding-bottom: 0; }
.as-settings-tabs { display: flex; flex: 0 0 auto; flex-wrap: nowrap; gap: 8px; overflow-x: auto; margin: 14px 0 14px; border-bottom: 1px solid #dfe6ee; background: #fff; padding: 8px 12px; scrollbar-width: thin; }
.as-settings-tabs button { display: inline-flex; height: 32px; flex: 0 0 auto; align-items: center; gap: 6px; border: 0; border-radius: 6px; background: #f1f5f9; padding: 0 12px; color: #475569; font-size: 14px; font-weight: 500; white-space: nowrap; transition: background-color .16s ease, color .16s ease; }
.as-settings-tabs button:hover { background: #e2e8f0; color: #334155; }
.as-settings-tabs button.active { background: #0f172a; color: #fff; }
.as-settings-tabs button svg { width: 15px; height: 15px; }
.as-settings-panel { display: grid; gap: 14px; border: 1px solid var(--as-border); border-radius: 8px; background: #fff; padding: 16px; }
.as-settings-panel-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; border-bottom: 1px solid #edf0f2; padding-bottom: 13px; }
.as-settings-panel-head h2 { margin: 0; color: #182230; font-size: 16px; }
.as-settings-panel-head p { max-width: 760px; margin: 4px 0 0; color: var(--as-muted); font-size: 11px; line-height: 17px; }
.as-settings-section { border: 1px solid #e1e7ef; border-radius: 7px; background: #fbfdff; padding: 13px; }
.as-settings-section h3, .as-settings-subhead h3 { margin: 0; color: #344054; font-size: 12px; }
.as-settings-subhead { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-bottom: 10px; }
.as-settings-subhead > span { color: var(--as-muted); font-size: 10px; font-weight: 750; }
.as-settings-subhead > span.invalid { color: var(--as-danger); }
.as-settings-check-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; margin-top: 10px; }
.as-settings-check-grid--two { grid-template-columns: repeat(2, minmax(0, 1fr)); margin-bottom: 11px; }
.as-settings-check-grid label { display: flex; min-height: 38px; align-items: center; gap: 7px; border: 1px solid #d9e1eb; border-radius: 6px; background: #fff; padding: 7px 9px; color: #526273; font-size: 10px; font-weight: 700; }
.as-settings-check-grid label.active { border-color: #8cb0ed; background: #eef5ff; color: #155eef; }
.as-settings-check-grid input { width: 14px; height: 14px; accent-color: var(--as-primary); }
.as-settings-toggle { display: flex; align-items: flex-start; gap: 8px; border-top: 1px solid #edf0f2; margin-top: 9px; padding-top: 9px; }
.as-settings-toggle input { width: 15px; height: 15px; margin-top: 1px; accent-color: var(--as-primary); }
.as-settings-toggle strong, .as-settings-toggle small { display: block; }
.as-settings-toggle strong { color: #344054; font-size: 10px; }
.as-settings-toggle small { margin-top: 2px; color: var(--as-muted); font-size: 9px; line-height: 14px; }
.as-settings-field { margin-top: 2px; }
.as-settings-note { margin: 10px 0 0; color: var(--as-muted); font-size: 10px; line-height: 16px; }
.as-settings-actions { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 8px; }
.as-settings-actions--left { justify-content: flex-start; margin-top: 12px; }
.as-settings-actions .as-button { min-height: 33px; font-size: 10px; }
.as-settings-tag-editor { display: grid; gap: 8px; }
.as-settings-tag-row { display: grid; grid-template-columns: minmax(0, 1fr) 36px; gap: 8px; }
.as-settings-tag-row input { width: 100%; min-width: 0; height: 36px; border: 1px solid #cfd7e2; border-radius: 6px; padding: 0 9px; color: var(--as-text); font-size: 10px; }
.as-settings-tag-row .as-icon-button { color: var(--as-danger); }
.as-settings-sms-layout { display: grid; grid-template-columns: minmax(0, 1.1fr) minmax(260px, .9fr); gap: 14px; }
.as-settings-admin-tab { min-width: 0; }
@media (max-width: 640px) { .as-settings-check-grid, .as-settings-check-grid--two { grid-template-columns: minmax(0, 1fr); } .as-settings-tabs { margin-right: -4px; margin-left: -4px; padding-right: 8px; padding-left: 8px; } }
</style>
