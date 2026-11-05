<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import {
  Building2,
  CreditCard,
  Hash,
  Landmark,
  Loader2,
  MapPin,
  Pencil,
  Phone,
  Plus,
  RefreshCw,
  Save,
  Search,
  Trash2,
  X,
  XCircle,
} from "@lucide/vue";
import { matchesDirectorySearchKeyword, PlatformDetailDrawer } from "@platform-ui";

import { apiDelete, apiGet, apiPost, apiPut } from "@/api";
import { SETTINGS_COMPANY_ENTITIES_LEAVE_EVENT } from "@/config";
import { useSettingsFeedback } from "./useSettingsFeedback";
import SettingsUnsavedChangesDialog from "@/components/settings/SettingsUnsavedChangesDialog.vue";

const emit = defineEmits(["dirty-change", "saving-change"]);
const initialUrl = new URL(window.location.href);

const fields = [
  { key: "companyName", label: "公司名称", icon: Building2, maxLength: 255 },
  { key: "taxNumber", label: "税号", icon: Hash, maxLength: 64, monospace: true },
  { key: "bankName", label: "开户银行", icon: Landmark, maxLength: 255 },
  { key: "bankAccount", label: "账号", icon: CreditCard, maxLength: 64, monospace: true },
  { key: "address", label: "地址", icon: MapPin, maxLength: 512, multiline: true, fullWidth: true },
  { key: "phone", label: "电话", icon: Phone, maxLength: 64 },
];

const items = ref([]);
const loading = ref(false);
const loadError = ref("");
const showFeedback = useSettingsFeedback();
const keyword = ref(initialUrl.searchParams.get("q") || "");
const drawerOpen = ref(false);
const selectedItem = ref(null);
const editForm = ref(null);
const originalForm = ref(null);
const fieldErrors = ref({});
const drawerError = ref("");
const saving = ref(false);
const deleting = ref(false);
const deleteConfirmOpen = ref(false);
const discardConfirmOpen = ref(false);
const pendingDiscardAction = ref(null);

const dragState = {
  active: false,
  dragged: false,
  startX: 0,
  scrollLeft: 0,
};

const isCreating = computed(() => drawerOpen.value && !selectedItem.value);
const isEditing = computed(() => Boolean(editForm.value));
const busy = computed(() => saving.value || deleting.value);
const drawerTitle = computed(() => {
  if (isCreating.value) return "新增我司主体";
  return selectedItem.value?.companyName || "我司主体详情";
});
const formChanged = computed(() => {
  if (!editForm.value || !originalForm.value) return false;
  return fields.some(({ key }) => String(editForm.value[key] || "") !== String(originalForm.value[key] || ""));
});
const filteredItems = computed(() => items.value.filter((item) => matchesDirectorySearchKeyword(
  keyword.value,
  {
    names: item.companyName,
    ids: [item.id, item.taxNumber],
    pinyin: item.pinyin,
    pinyinInitials: item.pinyinInitials,
  },
)));

function emptyForm() {
  return Object.fromEntries(fields.map(({ key }) => [key, ""]));
}

function formFromItem(item) {
  return Object.fromEntries(fields.map(({ key }) => [key, String(item?.[key] || "")]));
}

async function loadItems() {
  if (loading.value) return;
  loading.value = true;
  loadError.value = "";
  try {
    const data = await apiGet("/api/directory/company-entities", { all: true });
    if (!Array.isArray(data.items) || data.items.length !== data.total || data.count !== data.total || !data.directoryRevision) {
      throw new Error("我司主体返回不完整，请重新加载");
    }
    items.value = data.items;
  } catch (error) {
    loadError.value = error instanceof Error ? error.message : "我司主体加载失败";
  } finally {
    loading.value = false;
  }
}

function syncKeywordToUrl() {
  const url = new URL(window.location.href);
  const normalized = keyword.value.trim();
  if (normalized) url.searchParams.set("q", normalized);
  else url.searchParams.delete("q");
  window.history.replaceState(window.history.state, "", url);
}

function openDrawerForItem(item) {
  selectedItem.value = { ...item };
  editForm.value = null;
  originalForm.value = null;
  fieldErrors.value = {};
  drawerError.value = "";
  deleteConfirmOpen.value = false;
  drawerOpen.value = true;
}

function requestDiscard(action) {
  if (busy.value) {
    drawerError.value = "操作正在提交，请等待完成后再离开";
    return false;
  }
  if (!formChanged.value) {
    action?.();
    return true;
  }
  pendingDiscardAction.value = action || null;
  discardConfirmOpen.value = true;
  return false;
}

function openRow(item) {
  if (dragState.dragged) return;
  requestDiscard(() => openDrawerForItem(item));
}

function startCreate() {
  requestDiscard(() => {
    selectedItem.value = null;
    editForm.value = emptyForm();
    originalForm.value = emptyForm();
    fieldErrors.value = {};
    drawerError.value = "";
    deleteConfirmOpen.value = false;
    drawerOpen.value = true;
  });
}

function startEdit() {
  if (!selectedItem.value || busy.value) return;
  editForm.value = formFromItem(selectedItem.value);
  originalForm.value = { ...editForm.value };
  fieldErrors.value = {};
  drawerError.value = "";
  deleteConfirmOpen.value = false;
}

function closeDrawerImmediately() {
  drawerOpen.value = false;
  selectedItem.value = null;
  editForm.value = null;
  originalForm.value = null;
  fieldErrors.value = {};
  drawerError.value = "";
  deleteConfirmOpen.value = false;
}

function requestCloseDrawer() {
  requestDiscard(closeDrawerImmediately);
}

function requestCancelEdit() {
  requestDiscard(() => {
    if (isCreating.value) {
      closeDrawerImmediately();
      return;
    }
    editForm.value = null;
    originalForm.value = null;
    fieldErrors.value = {};
    drawerError.value = "";
  });
}

function cancelDiscard() {
  discardConfirmOpen.value = false;
  pendingDiscardAction.value = null;
}

function confirmDiscard() {
  const action = pendingDiscardAction.value;
  pendingDiscardAction.value = null;
  discardConfirmOpen.value = false;
  editForm.value = null;
  originalForm.value = null;
  fieldErrors.value = {};
  action?.();
}

function validateForm() {
  const errors = {};
  fields.forEach((field) => {
    const value = String(editForm.value?.[field.key] || "").trim();
    if (!value) errors[field.key] = `请填写${field.label}`;
  });
  fieldErrors.value = errors;
  return Object.keys(errors).length === 0;
}

async function saveItem() {
  if (!editForm.value || saving.value || !validateForm()) return;
  saving.value = true;
  drawerError.value = "";
  const payload = Object.fromEntries(fields.map(({ key }) => [key, String(editForm.value[key] || "").trim()]));
  try {
    const data = isCreating.value
      ? await apiPost("/api/directory/company-entities", payload)
      : await apiPut(`/api/directory/company-entities/${selectedItem.value.id}`, { ...payload, revision: selectedItem.value.revision });
    const savedItem = data.item;
    if (!savedItem) throw new Error("我司主体保存结果无效");
    const existingIndex = items.value.findIndex((item) => item.id === savedItem.id);
    if (existingIndex >= 0) items.value.splice(existingIndex, 1, savedItem);
    else items.value = [...items.value, savedItem];
    selectedItem.value = { ...savedItem };
    editForm.value = null;
    originalForm.value = null;
    fieldErrors.value = {};
    showFeedback(`已保存我司主体“${savedItem.companyName}”`);
  } catch (error) {
    drawerError.value = error instanceof Error ? error.message : "我司主体保存失败";
  } finally {
    saving.value = false;
  }
}

async function confirmDelete() {
  if (!selectedItem.value || deleting.value) return;
  deleting.value = true;
  drawerError.value = "";
  const deletingItem = selectedItem.value;
  try {
    await apiDelete(`/api/directory/company-entities/${deletingItem.id}?revision=${deletingItem.revision}`);
    items.value = items.value.filter((item) => item.id !== deletingItem.id);
    deleteConfirmOpen.value = false;
    closeDrawerImmediately();
    showFeedback(`已删除我司主体“${deletingItem.companyName}”`);
  } catch (error) {
    deleteConfirmOpen.value = false;
    drawerError.value = error instanceof Error ? error.message : "我司主体删除失败";
  } finally {
    deleting.value = false;
  }
}

function handleRowKeydown(event, item) {
  if (!["Enter", " "].includes(event.key)) return;
  event.preventDefault();
  openRow(item);
}

function tableDragStart(event) {
  if (event.button !== 0 || event.target.closest("button, input, textarea, a")) return;
  dragState.active = true;
  dragState.dragged = false;
  dragState.startX = event.pageX;
  dragState.scrollLeft = event.currentTarget.scrollLeft;
}

function tableDragMove(event) {
  if (!dragState.active) return;
  const walk = (event.pageX - dragState.startX) * 1.2;
  if (Math.abs(walk) > 5) dragState.dragged = true;
  if (!dragState.dragged) return;
  event.preventDefault();
  event.currentTarget.scrollLeft = dragState.scrollLeft - walk;
}

function tableDragEnd() {
  dragState.active = false;
  if (dragState.dragged) window.setTimeout(() => { dragState.dragged = false; }, 80);
}

function handleTableKeydown(event) {
  if (event.target !== event.currentTarget || !["ArrowLeft", "ArrowRight"].includes(event.key)) return;
  event.preventDefault();
  event.currentTarget.scrollBy({ left: event.key === "ArrowRight" ? 180 : -180, behavior: "smooth" });
}

function handleBeforeUnload(event) {
  if (!formChanged.value && !busy.value) return;
  event.preventDefault();
  event.returnValue = "";
}

function handleExternalLeave(event) {
  const continueAction = event?.detail?.continue;
  if (busy.value) {
    drawerError.value = "操作正在提交，请等待完成后再离开";
    event.preventDefault();
    return;
  }
  if (!formChanged.value) {
    closeDrawerImmediately();
    return;
  }
  event.preventDefault();
  pendingDiscardAction.value = typeof continueAction === "function" ? continueAction : null;
  discardConfirmOpen.value = true;
}

watch(formChanged, (value) => emit("dirty-change", value), { immediate: true });
watch(busy, (value) => emit("saving-change", value), { immediate: true });
watch(keyword, syncKeywordToUrl);

onMounted(() => {
  window.addEventListener("beforeunload", handleBeforeUnload);
  window.addEventListener(SETTINGS_COMPANY_ENTITIES_LEAVE_EVENT, handleExternalLeave);
  loadItems();
});

onBeforeUnmount(() => {
  window.removeEventListener("beforeunload", handleBeforeUnload);
  window.removeEventListener(SETTINGS_COMPANY_ENTITIES_LEAVE_EVENT, handleExternalLeave);
  emit("dirty-change", false);
  emit("saving-change", false);
});
</script>

<template>
  <section
    id="auth-company-entities-panel"
    class="flex h-full min-h-0 flex-col overflow-hidden rounded-lg border border-slate-200 bg-white shadow-sm"
    role="tabpanel"
    aria-labelledby="auth-company-entities-tab"
  >
    <header class="flex min-h-14 shrink-0 items-center justify-between gap-3 border-b border-slate-200 px-4">
      <div class="min-w-0">
        <h1 id="company-entities-title" class="text-base font-semibold text-slate-900">我司主体资料</h1>
        <p class="mt-0.5 text-xs text-slate-500">
          {{ keyword.trim() ? `显示 ${filteredItems.length} 个，共 ${items.length} 个我司主体` : `共 ${items.length} 个我司主体` }}
        </p>
      </div>
      <div class="flex min-w-0 shrink-0 items-center gap-2">
        <div class="relative w-[280px] min-w-0" role="search">
          <label for="company-entity-search" class="sr-only">搜索我司主体名称、拼音、税号或ID</label>
          <Search class="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" aria-hidden="true" />
          <input
            id="company-entity-search"
            v-model="keyword"
            type="search"
            class="h-8 w-full rounded-md border border-slate-200 bg-white pl-9 pr-8 text-sm text-slate-800 outline-none placeholder:text-slate-400 focus:border-blue-400 focus:ring-2 focus:ring-blue-100"
            placeholder="名称、拼音、税号或ID"
            autocomplete="off"
          />
          <button
            v-if="keyword"
            type="button"
            class="absolute right-1 top-1/2 inline-flex h-6 w-6 -translate-y-1/2 items-center justify-center rounded text-slate-400 hover:bg-slate-100 hover:text-slate-700"
            aria-label="清除我司主体搜索"
            @click.prevent="keyword = ''"
          >
            <X class="h-3.5 w-3.5" aria-hidden="true" />
          </button>
        </div>
        <button
          type="button"
          class="inline-flex h-8 w-8 items-center justify-center rounded-md border border-slate-200 bg-white text-slate-500 hover:bg-slate-50 hover:text-slate-800 disabled:cursor-not-allowed disabled:opacity-50"
          :disabled="loading"
          aria-label="刷新我司主体"
          title="刷新我司主体"
          @click="loadItems"
        >
          <RefreshCw class="h-4 w-4" :class="loading ? 'animate-spin' : ''" aria-hidden="true" />
        </button>
        <button
          type="button"
          class="inline-flex h-8 items-center gap-1.5 rounded-md bg-blue-600 px-3 text-sm font-medium text-white hover:bg-blue-700"
          data-ai-action="auth.company-entity.create"
          @click="startCreate"
        >
          <Plus class="h-4 w-4" aria-hidden="true" />新增
        </button>
      </div>
    </header>

    <div v-if="loadError && items.length" class="flex items-center justify-between gap-3 border-b border-red-100 bg-red-50 px-4 py-2 text-sm text-red-700" role="alert">
      <span>{{ loadError }}</span>
      <button type="button" class="shrink-0 font-medium text-blue-700 hover:text-blue-800" @click="loadItems">重新加载</button>
    </div>

    <div v-if="loading && !items.length" class="flex min-h-0 flex-1 items-center justify-center gap-2 text-sm text-slate-500" role="status">
      <Loader2 class="h-4 w-4 animate-spin" aria-hidden="true" />正在加载我司主体...
    </div>
    <div v-else-if="loadError && !items.length" class="flex min-h-0 flex-1 flex-col items-center justify-center gap-3 p-6 text-sm text-red-600" role="alert">
      <span>{{ loadError }}</span>
      <button type="button" class="h-8 rounded-md bg-blue-600 px-3 font-medium text-white hover:bg-blue-700" @click="loadItems">重新加载</button>
    </div>
    <div
      v-else
      class="company-entity-table-scroll min-h-0 flex-1 cursor-grab overflow-auto active:cursor-grabbing"
      tabindex="0"
      role="region"
      aria-label="我司主体表格，可使用方向键横向浏览"
      @keydown="handleTableKeydown"
      @mousedown="tableDragStart"
      @mousemove="tableDragMove"
      @mouseup="tableDragEnd"
      @mouseleave="tableDragEnd"
    >
      <table class="company-entity-table w-full select-none border-separate border-spacing-0 text-sm">
        <caption class="sr-only">我司主体资料</caption>
        <colgroup><col /><col /><col /><col /><col /><col /></colgroup>
        <thead class="sticky top-0 z-10 bg-slate-50 text-slate-700">
          <tr>
            <th scope="col" class="border-b border-r border-slate-200 px-3 py-3 text-center font-semibold">公司名称</th>
            <th scope="col" class="border-b border-r border-slate-200 px-3 py-3 text-center font-semibold">税号</th>
            <th scope="col" class="border-b border-r border-slate-200 px-3 py-3 text-center font-semibold">开户银行</th>
            <th scope="col" class="border-b border-r border-slate-200 px-3 py-3 text-center font-semibold">账号</th>
            <th scope="col" class="border-b border-r border-slate-200 px-3 py-3 text-center font-semibold">地址</th>
            <th scope="col" class="border-b border-slate-200 px-3 py-3 text-center font-semibold">电话</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="item in filteredItems"
            :key="item.id"
            class="cursor-pointer odd:bg-white even:bg-slate-50/50 hover:bg-blue-50/60 focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-blue-500"
            tabindex="0"
            :aria-label="`查看我司主体：${item.companyName}`"
            @click="openRow(item)"
            @keydown="handleRowKeydown($event, item)"
          >
            <td class="border-b border-r border-slate-100 px-3 py-3 text-slate-800" :title="item.companyName">{{ item.companyName }}</td>
            <td class="border-b border-r border-slate-100 px-3 py-3 font-mono text-slate-700" :title="item.taxNumber">{{ item.taxNumber }}</td>
            <td class="border-b border-r border-slate-100 px-3 py-3 text-slate-700" :title="item.bankName">{{ item.bankName }}</td>
            <td class="border-b border-r border-slate-100 px-3 py-3 font-mono text-slate-700">{{ item.bankAccount }}</td>
            <td class="border-b border-r border-slate-100 px-3 py-3 leading-5 text-slate-700" :title="item.address">{{ item.address }}</td>
            <td class="border-b border-slate-100 px-3 py-3 text-center text-slate-700">{{ item.phone }}</td>
          </tr>
          <tr v-if="!filteredItems.length">
            <td colspan="6" class="px-4 py-16 text-center text-sm text-slate-400">
              {{ items.length && keyword.trim() ? "没有匹配的我司主体" : "暂无我司主体" }}
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>

  <PlatformDetailDrawer
    :open="drawerOpen"
    :suspended="discardConfirmOpen || deleteConfirmOpen || busy"
    labelled-by="auth-company-entity-drawer-title"
    @close="requestCloseDrawer"
  >
    <header class="z-10 flex shrink-0 items-start justify-between gap-4 border-b border-slate-100 bg-white px-6 py-5 shadow-[0_4px_20px_-8px_rgba(0,0,0,0.05)]">
      <div class="flex min-w-0 items-center gap-3">
        <div class="flex h-10 w-10 shrink-0 items-center justify-center rounded-full border border-blue-100/50 bg-blue-50 shadow-sm" aria-hidden="true">
          <Building2 class="h-5 w-5 text-blue-600" />
        </div>
        <div class="min-w-0">
          <h2 id="auth-company-entity-drawer-title" class="line-clamp-1 text-[16px] font-bold leading-tight text-slate-900" :title="drawerTitle">{{ drawerTitle }}</h2>
          <div class="mt-1 flex flex-wrap items-center gap-1.5">
            <span class="rounded-md border border-slate-200 bg-slate-50 px-2 py-0.5 text-[11px] font-semibold text-slate-500">
              {{ isCreating ? "待保存" : `主体 #${selectedItem?.id}` }}
            </span>
            <span v-if="isCreating" class="rounded-md border border-emerald-100 bg-emerald-50 px-2 py-0.5 text-[11px] font-bold text-emerald-600">新增</span>
            <span v-else-if="isEditing" class="rounded-md border border-blue-100 bg-blue-50 px-2 py-0.5 text-[11px] font-bold text-blue-600">编辑中</span>
          </div>
        </div>
      </div>
      <button type="button" class="-mr-2 rounded-full p-2 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-700 disabled:opacity-50" :disabled="busy" aria-label="关闭我司主体详情" @click="requestCloseDrawer">
        <X class="h-5 w-5" aria-hidden="true" />
      </button>
    </header>

    <div class="min-h-0 flex-1 space-y-5 overflow-y-auto bg-slate-50 p-6 [scrollbar-width:none]" :inert="busy ? true : undefined">
      <section class="rounded-[8px] border border-slate-200 bg-white p-5 shadow-sm" data-ai-section="auth.company-entity.details" aria-labelledby="auth-company-entity-details-title">
        <div class="mb-5 flex items-center gap-2">
          <div class="h-3.5 w-1 rounded-sm bg-blue-600" aria-hidden="true" />
          <h3 id="auth-company-entity-details-title" class="text-[13px] font-semibold text-slate-900">主体资料</h3>
        </div>
        <form class="grid grid-cols-1 gap-x-8 gap-y-3 sm:grid-cols-2" @submit.prevent="saveItem">
          <div
            v-for="field in fields"
            :key="field.key"
            class="border-b border-slate-100 py-2"
            :class="field.fullWidth ? 'sm:col-span-2' : ''"
            :data-ai-field="`auth.company-entity.${field.key}`"
          >
            <div class="mb-1 flex items-center gap-2 text-slate-400">
              <component :is="field.icon" class="h-3.5 w-3.5" aria-hidden="true" />
              <label v-if="isEditing" :for="`company-entity-${field.key}`" class="text-xs">
                {{ field.label }}<span class="ml-0.5 text-red-500" aria-hidden="true">*</span>
              </label>
              <p v-else class="text-xs">{{ field.label }}</p>
            </div>
            <template v-if="isEditing">
              <textarea
                v-if="field.multiline"
                :id="`company-entity-${field.key}`"
                v-model.trim="editForm[field.key]"
                rows="3"
                required
                :maxlength="field.maxLength"
                class="w-full resize-none rounded-md border bg-white px-2.5 py-2 text-sm font-medium leading-5 text-slate-800 outline-none focus:ring-2"
                :class="fieldErrors[field.key] ? 'border-red-400 focus:border-red-500 focus:ring-red-100' : 'border-slate-200 focus:border-blue-400 focus:ring-blue-100'"
                :aria-invalid="Boolean(fieldErrors[field.key])"
                :aria-describedby="fieldErrors[field.key] ? `company-entity-${field.key}-error` : undefined"
                @input="fieldErrors[field.key] = ''"
              />
              <input
                v-else
                :id="`company-entity-${field.key}`"
                v-model.trim="editForm[field.key]"
                required
                :maxlength="field.maxLength"
                class="h-8 w-full rounded-md border bg-white px-2.5 text-sm font-semibold text-slate-800 outline-none focus:ring-2"
                :class="[
                  field.monospace ? 'font-mono' : '',
                  fieldErrors[field.key] ? 'border-red-400 focus:border-red-500 focus:ring-red-100' : 'border-slate-200 focus:border-blue-400 focus:ring-blue-100',
                ]"
                :aria-invalid="Boolean(fieldErrors[field.key])"
                :aria-describedby="fieldErrors[field.key] ? `company-entity-${field.key}-error` : undefined"
                @input="fieldErrors[field.key] = ''"
              />
              <p v-if="fieldErrors[field.key]" :id="`company-entity-${field.key}-error`" class="mt-1 text-xs font-medium text-red-600" role="alert">{{ fieldErrors[field.key] }}</p>
            </template>
            <p
              v-else
              class="min-w-0 whitespace-pre-wrap break-words text-[15px] font-semibold leading-6 text-slate-800"
              :class="field.monospace ? 'font-mono tabular-nums' : ''"
            >{{ selectedItem?.[field.key] || "-" }}</p>
          </div>
        </form>
      </section>
    </div>

    <div v-if="drawerError" class="shrink-0 border-t border-red-100 bg-red-50 px-5 py-2 text-center text-xs font-medium text-red-600" role="alert">{{ drawerError }}</div>
    <footer class="flex shrink-0 flex-wrap items-center justify-center gap-3 border-t border-slate-100 bg-white px-6 py-4">
      <template v-if="isEditing">
        <button type="button" class="inline-flex h-8 items-center gap-1.5 rounded-lg bg-blue-600 px-8 text-[13px] font-bold text-white shadow-sm transition-colors hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-slate-300 disabled:shadow-none" :disabled="saving" data-ai-action="auth.company-entity.save" @click="saveItem">
          <Loader2 v-if="saving" class="h-4 w-4 animate-spin" aria-hidden="true" />
          <Save v-else class="h-4 w-4" aria-hidden="true" />
          {{ saving ? "保存中..." : "保存" }}
        </button>
        <button type="button" class="inline-flex h-8 items-center gap-1.5 rounded-lg bg-slate-100 px-7 text-[13px] font-bold text-slate-600 transition-colors hover:bg-slate-200 disabled:cursor-not-allowed disabled:opacity-50" :disabled="saving" @click="requestCancelEdit">
          <XCircle class="h-4 w-4" aria-hidden="true" />取消
        </button>
      </template>
      <template v-else-if="selectedItem">
        <button type="button" class="inline-flex h-8 items-center gap-1.5 rounded-lg border border-red-100 bg-white px-5 text-[13px] font-bold text-red-500 transition-colors hover:bg-red-50" @click="deleteConfirmOpen = true">
          <Trash2 class="h-3.5 w-3.5" aria-hidden="true" />删除
        </button>
        <button type="button" class="inline-flex h-8 items-center gap-1.5 rounded-lg bg-blue-600 px-7 text-[13px] font-bold text-white shadow-sm transition-colors hover:bg-blue-700" @click="startEdit">
          <Pencil class="h-3.5 w-3.5" aria-hidden="true" />编辑
        </button>
      </template>
    </footer>
  </PlatformDetailDrawer>

  <SettingsUnsavedChangesDialog
    :open="discardConfirmOpen"
    message="当前我司主体的修改尚未保存，离开后本次修改不会保留。"
    @cancel="cancelDiscard"
    @confirm="confirmDiscard"
  />
  <SettingsUnsavedChangesDialog
    :open="deleteConfirmOpen"
    title="是否删除我司主体"
    :message="`删除“${selectedItem?.companyName || '该我司主体'}”后，平台基础目录将不再提供这条主体资料。`"
    cancel-text="取消"
    cancel-tone="secondary"
    confirm-text="确认删除"
    :busy="deleting"
    @cancel="deleteConfirmOpen = false"
    @confirm="confirmDelete"
  />
</template>

<style scoped>
.company-entity-table-scroll {
  scrollbar-width: none;
}

.company-entity-table {
  min-width: 1410px;
}

.company-entity-table col:nth-child(1) { width: 240px; }
.company-entity-table col:nth-child(2) { width: 190px; }
.company-entity-table col:nth-child(3) { width: 270px; }
.company-entity-table col:nth-child(4) { width: 180px; }
.company-entity-table col:nth-child(5) { width: 380px; }
.company-entity-table col:nth-child(6) { width: 150px; }
</style>
