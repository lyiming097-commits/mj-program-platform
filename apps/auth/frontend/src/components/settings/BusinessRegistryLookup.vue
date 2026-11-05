<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, useId, watch } from "vue";
import { Check, LoaderCircle, Search, X } from "@lucide/vue";
import { companyKey } from "./business-registry-company";

// The host owns API requests, persistence and the selected company snapshot.
const props = defineProps({
  modelValue: { type: String, default: "" },
  selectedCompany: { type: Object, default: null },
  selectedCompanies: { type: Array, default: () => [] },
  multiple: Boolean,
  label: { type: String, default: "单选企业" },
  autofocus: { type: Boolean, default: true },
  error: { type: String, default: "" },
  result: { type: Object, default: null },
  busy: Boolean,
  hasMore: Boolean,
  loadingMore: Boolean,
  morePending: Boolean,
  moreError: { type: String, default: "" },
  endMessage: { type: String, default: "已全部加载" },
  configured: { type: Boolean, default: null },
  describedBy: { type: String, default: "" },
});
const emit = defineEmits(["update:modelValue", "update:selectedCompanies", "select", "search", "refresh", "load-more", "refresh-more"]);
const root = ref(null);
const control = ref(null);
const input = ref(null);
const submitButton = ref(null);
const menu = ref(null);
const scrollRegion = ref(null);
const open = ref(false);
const activeIndex = ref(0);
const menuStyle = ref({});
const fieldId = `registry-query-${useId()}`;
const listboxId = `${fieldId}-results`;
const companies = computed(() => props.result?.companies || []);
const canOpen = computed(() => props.result && !props.busy && ["succeeded", "empty"].includes(props.result.status)
  && (props.modelValue.trim() === props.result.keyword || props.selectedCompany || (props.multiple && !props.modelValue.trim())));
const selectedIndex = computed(() => companies.value.findIndex((company) => company === props.selectedCompany));
const selectedKeys = computed(() => new Set(props.selectedCompanies.map(companyKey)));
const activeOptionId = computed(() => open.value && companies.value[activeIndex.value] ? `${fieldId}-option-${activeIndex.value}` : undefined);
let alive = true;
let resizeObserver;
let lastScrollTop = 0;
let moreRequested = false;
let returnFocusAfterRequest = false;
let suppressAutomaticLoad = false;
let scrollFrame = null;

function suppressFocusScroll() {
  // Focusing/revealing an option or the footer can scroll without a paging gesture.
  suppressAutomaticLoad = true;
  cancelAnimationFrame(scrollFrame);
  scrollFrame = requestAnimationFrame(() => {
    scrollFrame = requestAnimationFrame(() => { suppressAutomaticLoad = false; });
  });
}

function isSelected(company, index) {
  return props.multiple ? selectedKeys.value.has(companyKey(company)) : selectedIndex.value === index;
}
function removeCompany(company) {
  if (props.busy || props.loadingMore) return;
  const key = companyKey(company);
  emit("update:selectedCompanies", props.selectedCompanies.filter((selected) => companyKey(selected) !== key));
  void nextTick(() => { input.value?.focus({ preventScroll: true }); positionMenu(); });
}
function requestMore() {
  if (!open.value || props.busy || props.loadingMore || props.morePending || !props.hasMore || props.configured !== true || moreRequested) return;
  moreRequested = true;
  emit("load-more");
  void nextTick(() => { moreRequested = false; });
}
function scrollResults(event) {
  const { scrollTop, scrollHeight, clientHeight } = event.currentTarget;
  const movedDown = scrollTop > lastScrollTop;
  lastScrollTop = scrollTop;
  if (movedDown && scrollHeight - scrollTop - clientHeight <= 2 && !props.moreError && !suppressAutomaticLoad) requestMore();
}

function positionMenu() {
  if (!open.value || !control.value) return;
  const controlBounds = control.value.getBoundingClientRect();
  const anchor = props.multiple ? input.value.getBoundingClientRect() : controlBounds;
  const gap = 6, margin = 12, preferredHeight = 360;
  const below = window.innerHeight - anchor.bottom - margin;
  const above = anchor.top - margin;
  const upwards = below < 160 && above > below;
  const width = Math.min(controlBounds.width, window.innerWidth - margin * 2);
  menuStyle.value = {
    width: `${width}px`,
    left: `${Math.max(margin, Math.min(controlBounds.left, window.innerWidth - width - margin))}px`,
    maxHeight: `${Math.max(0, Math.min(preferredHeight, (upwards ? above : below) - gap))}px`,
    ...(upwards ? { bottom: `${window.innerHeight - anchor.top + gap}px` } : { top: `${anchor.bottom + gap}px` }),
  };
}
async function revealActive() {
  await nextTick();
  if (!alive) return;
  const option = document.getElementById(activeOptionId.value);
  const region = scrollRegion.value;
  if (!option || !region) return;
  const bounds = option.getBoundingClientRect();
  const viewport = region.getBoundingClientRect();
  if (bounds.top >= viewport.top && bounds.bottom <= viewport.bottom) return;
  suppressFocusScroll();
  // Scroll only this menu; scrollIntoView can also move the drawer or the page.
  if (bounds.top < viewport.top) region.scrollTop -= viewport.top - bounds.top;
  else region.scrollTop += bounds.bottom - viewport.bottom;
}
async function openMenu() {
  if (!canOpen.value) return;
  if (!open.value) {
    activeIndex.value = Math.max(0, selectedIndex.value);
    lastScrollTop = 0;
  }
  open.value = true;
  await nextTick();
  if (!alive) return;
  input.value?.focus({ preventScroll: true });
  positionMenu();
  void revealActive();
}
function closeMenu() { open.value = false; }
function submit() {
  if (props.busy || props.loadingMore || !props.modelValue.trim() || props.configured !== true) return;
  closeMenu();
  emit("search");
}
function edit(event) {
  closeMenu();
  if (!props.multiple) emit("select", null);
  emit("update:modelValue", event.target.value);
}
function select(index) {
  const company = companies.value[index];
  if (props.busy || !company) return;
  if (props.multiple) {
    if (!selectedKeys.value.has(companyKey(company))) emit("update:selectedCompanies", [...props.selectedCompanies, company]);
    emit("update:modelValue", "");
    closeMenu();
    void nextTick(() => {
      if (!alive) return;
      input.value?.focus({ preventScroll: true });
      input.value?.scrollIntoView({ block: "nearest" });
    });
    return;
  }
  emit("select", company);
  emit("update:modelValue", company.companyName);
  closeMenu();
  input.value?.focus({ preventScroll: true });
}
function handleKeydown(event) {
  if (event.isComposing || event.keyCode === 229) {
    if (event.key === "Enter") event.preventDefault();
    return;
  }
  if (event.key === "Escape" && open.value) {
    event.preventDefault();
    event.stopPropagation();
    closeMenu();
    input.value?.focus({ preventScroll: true });
    return;
  }
  if (event.key === "Tab" && open.value) {
    const footer = menu.value?.querySelector("button:not([role='option']):not([disabled])");
    if (!event.shiftKey && footer && (event.target === submitButton.value || (event.target === input.value && submitButton.value?.disabled))) {
      event.preventDefault();
      event.stopPropagation();
      suppressFocusScroll();
      footer.focus({ preventScroll: true });
      footer.scrollIntoView({ block: "nearest" });
      return;
    }
    if (menu.value?.contains(event.target)) {
      closeMenu();
      const previous = submitButton.value?.disabled ? input.value : submitButton.value;
      previous?.focus({ preventScroll: true });
      if (event.shiftKey) { event.preventDefault(); event.stopPropagation(); }
      return;
    }
  }
  if (event.target !== input.value) return;
  if (event.key === "Enter" && open.value && companies.value.length) {
    event.preventDefault();
    select(activeIndex.value);
    return;
  }
  if (["ArrowDown", "ArrowUp"].includes(event.key)) {
    event.preventDefault();
    if (!open.value) { void openMenu(); return; }
    activeIndex.value = Math.max(0, Math.min(companies.value.length - 1, activeIndex.value + (event.key === "ArrowDown" ? 1 : -1)));
  } else if (open.value && ["Home", "End"].includes(event.key)) {
    event.preventDefault();
    activeIndex.value = event.key === "Home" ? 0 : Math.max(0, companies.value.length - 1);
  } else return;
  void revealActive();
}
function outside(event) {
  if (!root.value?.contains(event.target) && !menu.value?.contains(event.target)) {
    if (props.busy) returnFocusAfterRequest = false;
    if (open.value) closeMenu();
  }
}
onMounted(async () => {
  document.addEventListener("pointerdown", outside, true);
  document.addEventListener("focusin", outside, true);
  document.addEventListener("animationend", positionMenu, true);
  window.addEventListener("resize", positionMenu);
  window.addEventListener("scroll", positionMenu, true);
  resizeObserver = new ResizeObserver(positionMenu);
  if (control.value) resizeObserver.observe(control.value);
  await nextTick();
  if (alive && props.autofocus) input.value?.focus({ preventScroll: true });
});
watch(() => props.result?.id, () => { closeMenu(); activeIndex.value = 0; });
watch(() => props.loadingMore, (loading) => {
  // The focused pagination button is replaced by a loading message.
  if (loading && menu.value?.contains(document.activeElement)) input.value?.focus({ preventScroll: true });
});
watch(() => props.busy, async (busy, previous) => {
  if (busy) {
    returnFocusAfterRequest = root.value?.contains(document.activeElement) || menu.value?.contains(document.activeElement);
    closeMenu();
  } else if (previous && returnFocusAfterRequest) {
    returnFocusAfterRequest = false;
    await nextTick();
    if (!alive) return;
    if (document.activeElement !== document.body && !root.value?.contains(document.activeElement)) return;
    input.value?.focus({ preventScroll: true });
    await openMenu();
  }
});
onBeforeUnmount(() => {
  alive = false;
  cancelAnimationFrame(scrollFrame);
  resizeObserver?.disconnect();
  document.removeEventListener("pointerdown", outside, true);
  document.removeEventListener("focusin", outside, true);
  document.removeEventListener("animationend", positionMenu, true);
  window.removeEventListener("resize", positionMenu);
  window.removeEventListener("scroll", positionMenu, true);
});
</script>

<template>
  <section ref="root" class="min-w-0 rounded-lg border border-slate-200 bg-white p-4" :aria-labelledby="`${fieldId}-label`">
    <h3 :id="`${fieldId}-label`" class="mb-2 text-sm font-semibold text-slate-900"><label :for="fieldId">{{ label }}</label></h3>
    <form role="search" :aria-label="`${label}工商查询`" @submit.prevent="submit">
      <div ref="control" class="registry-query-control" :class="{ 'is-selected': !multiple && selectedCompany, 'is-busy': busy, 'is-multiple': multiple }" @keydown="handleKeydown">
        <div class="registry-query-entry" :class="{ 'is-multiple': multiple }">
          <ul v-if="multiple && selectedCompanies.length" role="list" aria-label="已选企业" class="registry-query-chips">
            <li v-for="company in selectedCompanies" :key="companyKey(company)" class="registry-query-chip">
              <span class="min-w-0 truncate" :title="company.companyName">{{ company.companyName }}</span>
              <button type="button" class="registry-query-chip-remove" :disabled="busy || loadingMore" :aria-label="`移除${company.companyName}`" @click.stop="removeCompany(company)">
                <X class="h-3 w-3" aria-hidden="true" />
              </button>
            </li>
          </ul>
        <input :id="fieldId" ref="input" :value="modelValue" type="text" role="combobox" required maxlength="200" autocomplete="off"
          aria-label="企业名称 / 统一社会信用代码 / 注册号" :aria-describedby="describedBy || undefined"
          :aria-invalid="error ? true : undefined" :aria-errormessage="error ? `${fieldId}-error` : undefined"
          :aria-expanded="open" :aria-controls="open ? listboxId : undefined" :aria-activedescendant="activeOptionId" aria-autocomplete="none"
          :title="selectedCompany ? `${selectedCompany.companyName} · ${selectedCompany.creditNo || '暂无统一社会信用代码'}` : undefined"
          :placeholder="multiple && selectedCompanies.length ? '继续输入企业名称' : '输入企业名称、信用代码或注册号'" class="registry-query-input" :disabled="busy" :readonly="loadingMore" @input="edit" @click="openMenu" />
        </div>
        <button ref="submitButton" type="submit" class="registry-query-submit" :aria-label="busy ? '查询中…' : '查询'" :aria-busy="busy" :disabled="busy || loadingMore || configured !== true || !modelValue.trim()">
          <LoaderCircle v-if="busy" class="h-4 w-4 animate-spin" aria-hidden="true" />
          <template v-else><Search class="h-4 w-4" aria-hidden="true" />查询</template>
        </button>
      </div>
    </form>
    <p v-if="error && !busy" :id="`${fieldId}-error`" role="alert" class="mt-2 text-sm text-red-700">{{ error }}</p>
    <p v-if="configured === false" role="status" class="mt-3 text-sm text-amber-700">工商查询服务尚未配置，请联系管理员配置服务凭证。</p>
    <div v-if="result?.status === 'running' && !busy" class="mt-3">
      <p role="status" class="text-sm text-slate-500">查询仍在处理中，请稍后刷新结果。</p>
      <button type="button" class="org-button mt-3" @click="emit('refresh', result.id)">刷新查询状态</button>
    </div>
    <Teleport to="body">
      <div v-if="open" ref="menu" class="registry-query-menu" :style="menuStyle" @keydown="handleKeydown" @focusin="suppressFocusScroll">
        <div ref="scrollRegion" role="region" :aria-label="multiple ? '多选企业查询结果' : '企业查询结果'" :aria-busy="loadingMore" class="registry-query-scroll min-h-0 overflow-y-auto p-1" @scroll.passive="scrollResults">
          <div :id="listboxId" role="listbox" :aria-label="`查询结果，${label}`" :aria-multiselectable="multiple ? true : undefined">
            <button v-for="(company, index) in companies" :id="`${fieldId}-option-${index}`" :key="index" type="button" role="option" tabindex="-1"
              class="registry-query-option flex w-full min-w-0 items-center gap-2 rounded-md px-3 py-1 text-left text-sm"
              :class="{ 'is-selected': isSelected(company, index), 'is-highlighted': activeIndex === index }" :aria-selected="isSelected(company, index)"
              :aria-label="`${company.companyName}，${company.creditNo || '暂无统一社会信用代码'}`" @mousedown.prevent @click="select(index)">
              <span class="flex min-w-0 flex-1 flex-col">
                <span class="break-words font-semibold leading-tight">{{ company.companyName }}</span>
                <span class="break-all text-xs leading-tight opacity-80">{{ company.creditNo || '暂无统一社会信用代码' }}</span>
              </span>
              <Check v-if="isSelected(company, index)" class="h-4 w-4 shrink-0" aria-hidden="true" />
            </button>
          </div>
          <p v-if="!companies.length && result.status === 'empty'" role="status" class="p-3 text-sm text-slate-500">没有匹配的企业，请调整关键词后重新查询。</p>
          <div v-else-if="companies.length" class="text-center text-xs">
            <p v-if="moreError" role="alert" class="px-3 py-2 text-red-700">{{ moreError }}</p>
            <p v-if="loadingMore" role="status" class="flex items-center justify-center gap-1 px-3 py-2 leading-4 text-slate-500"><LoaderCircle class="h-4 w-4 animate-spin" aria-hidden="true" />加载中…</p>
            <button v-else-if="morePending" type="button" class="registry-query-more" @mousedown.prevent @click="emit('refresh-more')">查询处理中，刷新结果</button>
            <button v-else-if="hasMore" type="button" class="registry-query-more" :disabled="busy || configured !== true" @mousedown.prevent @click="requestMore">{{ moreError ? '重试加载' : '加载更多' }}</button>
            <p v-else role="status" class="px-3 py-2 leading-4 text-slate-500">{{ endMessage }}</p>
          </div>
        </div>
      </div>
    </Teleport>
  </section>
</template>

<style scoped>
.registry-query-control { --registry-query-height: 36px; --registry-query-action-width: 72px; display: flex; min-width: 0; min-height: var(--registry-query-height); align-items: stretch; border: 1px solid var(--org-border, #e2e8f0); border-radius: var(--org-radius, 8px); background: white; }
.registry-query-control:focus-within { border-color: var(--org-primary, #2563eb); box-shadow: 0 0 0 1px var(--org-primary, #2563eb); }
.registry-query-control.is-selected { background: var(--color-blue-50, #eff6ff); border-color: var(--color-blue-200, #bfdbfe); }
.registry-query-control.is-busy { background: var(--color-slate-50, #f8fafc); }
.registry-query-control.is-multiple { position: relative; }
.registry-query-entry { display: flex; flex: 1; min-width: 0; align-items: stretch; }
.registry-query-entry.is-multiple { flex-wrap: wrap; align-items: center; gap: 4px; padding: 4px 8px; }
.registry-query-chips { display: contents; }
/* Match the application template's detail picker chips. */
.registry-query-chip { display: inline-flex; max-width: 100%; align-items: center; gap: 4px; border: 1px solid var(--color-blue-100, #dbeafe); border-radius: 6px; background: var(--color-blue-50, #eff6ff); padding: 2px 6px; color: var(--org-primary, #2563eb); font-size: 12px; font-weight: 700; line-height: 18px; }
.registry-query-chip-remove { display: inline-flex; width: 16px; height: 16px; flex-shrink: 0; align-items: center; justify-content: center; border-radius: 4px; color: var(--color-blue-400, #60a5fa); }
.registry-query-chip-remove:hover:enabled { background: var(--color-blue-100, #dbeafe); color: var(--color-blue-800, #1e40af); }
.registry-query-chip-remove:focus-visible { outline: 2px solid var(--org-primary, #2563eb); outline-offset: 1px; }
.registry-query-chip-remove:disabled { cursor: not-allowed; opacity: .5; }
.registry-query-input { flex: 1; width: 100%; min-width: 0; border: 0; outline: none; border-radius: inherit; padding: 0 10px; background: transparent; color: var(--color-slate-900, #0f172a); font-size: 13px; }
.registry-query-entry.is-multiple .registry-query-input { flex: 1 1 128px; width: 8rem; min-height: 26px; margin-right: calc(var(--registry-query-action-width) - 8px); padding: 0 2px; }
.registry-query-control .registry-query-input:focus-visible { outline: none; box-shadow: none; }
.registry-query-input::placeholder { color: var(--color-slate-400, #94a3b8); }
.registry-query-submit { display: flex; flex: 0 0 auto; min-width: var(--registry-query-action-width); align-items: center; justify-content: center; gap: 4px; border-radius: 0 var(--org-radius, 8px) var(--org-radius, 8px) 0; padding: 0 10px; background: var(--org-primary, #2563eb); color: white; font-size: 13px; font-weight: 600; }
.registry-query-control.is-multiple .registry-query-submit { position: absolute; right: 0; bottom: 0; height: calc(var(--registry-query-height) - 2px); border-radius: 6px 0 6px 0; }
.registry-query-submit:hover:enabled { background: var(--color-blue-700, #1d4ed8); }
.registry-query-submit:disabled { cursor: not-allowed; opacity: .5; }
.registry-query-submit:focus-visible { outline: 2px solid var(--color-blue-800, #1e40af); outline-offset: -3px; }
.registry-query-menu { position: fixed; z-index: 90; display: flex; flex-direction: column; overflow: hidden; border: 1px solid var(--color-slate-200, #e2e8f0); border-radius: 8px; background: white; box-shadow: 0 12px 30px rgb(15 23 42 / 12%); }
.registry-query-scroll { overflow-anchor: none; }
.registry-query-more { width: 100%; border-radius: 6px; padding: 8px 12px; color: var(--org-primary, #2563eb); font-size: 12px; line-height: 16px; }
.registry-query-more:hover:enabled { background: var(--color-blue-50, #eff6ff); }
.registry-query-more:focus-visible { outline: 2px solid var(--org-primary, #2563eb); outline-offset: -2px; }
.registry-query-more:disabled { cursor: not-allowed; opacity: .5; }
.registry-query-option { color: var(--color-slate-600, #475569); }
.registry-query-option:hover, .registry-query-option.is-highlighted { background: var(--color-blue-50, #eff6ff); color: var(--color-blue-700, #1d4ed8); }
.registry-query-option.is-selected { background: var(--color-blue-600, #2563eb); color: white; }
</style>
