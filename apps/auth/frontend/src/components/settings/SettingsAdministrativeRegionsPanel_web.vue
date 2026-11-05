<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { ChevronRight, LoaderCircle, MapPinned, RefreshCw, Search, X } from "@lucide/vue";

import { apiGet } from "@/api";
const currentUrl = new URL(window.location.href);
const administrativeRegions = ref([]);
const administrativeRegionStats = ref({ provinces: 0, cities: 0, districts: 0 });
const directoryLoading = ref(true);
const directoryError = ref("");
const selectedProvinceCode = ref(currentUrl.searchParams.get("province") || "");
const selectedCityCode = ref(currentUrl.searchParams.get("city") || "");
const keyword = ref(currentUrl.searchParams.get("q") || "");
const searchResults = ref([]);
const searchLoading = ref(false);
const searchError = ref("");
let searchTimer = null;
let searchRequestSequence = 0;
let directoryRequestSequence = 0;

const selectedProvince = computed(() => (
  administrativeRegions.value.find((item) => item.code === selectedProvinceCode.value) || null
));
const selectedCity = computed(() => (
  selectedProvince.value?.cities.find((item) => item.code === selectedCityCode.value) || null
));

async function loadDirectory() {
  const requestSequence = ++directoryRequestSequence;
  directoryLoading.value = true;
  directoryError.value = "";
  try {
    const data = await apiGet("/api/directory/administrative-regions");
    if (requestSequence !== directoryRequestSequence) return;
    if (!Array.isArray(data.items) || !data.stats) throw new Error("行政区域目录返回格式错误");
    administrativeRegions.value = data.items;
    administrativeRegionStats.value = data.stats;
    const province = data.items.find((item) => item.code === selectedProvinceCode.value) || data.items[0];
    const city = province?.cities.find((item) => item.code === selectedCityCode.value) || province?.cities[0];
    selectedProvinceCode.value = province?.code || "";
    selectedCityCode.value = city?.code || "";
  } catch (error) {
    if (requestSequence !== directoryRequestSequence) return;
    directoryError.value = error instanceof Error ? error.message : "行政区域目录加载失败";
  } finally {
    if (requestSequence === directoryRequestSequence) directoryLoading.value = false;
  }
}
function syncUrlState() {
  const url = new URL(window.location.href);
  if (selectedProvinceCode.value) url.searchParams.set("province", selectedProvinceCode.value);
  else url.searchParams.delete("province");
  if (selectedCityCode.value) url.searchParams.set("city", selectedCityCode.value);
  else url.searchParams.delete("city");
  const normalizedKeyword = keyword.value.trim();
  if (normalizedKeyword) url.searchParams.set("q", normalizedKeyword);
  else url.searchParams.delete("q");
  window.history.replaceState(window.history.state, "", url);
}

async function runSearch(normalizedKeyword, requestSequence) {
  try {
    const data = await apiGet("/api/directory/administrative-regions/search", {
      keyword: normalizedKeyword,
      limit: 100,
    });
    if (requestSequence !== searchRequestSequence) return;
    searchResults.value = Array.isArray(data.items) ? data.items : [];
    searchError.value = "";
  } catch (error) {
    if (requestSequence !== searchRequestSequence) return;
    searchResults.value = [];
    searchError.value = error instanceof Error ? error.message : "行政区域搜索失败";
  } finally {
    if (requestSequence === searchRequestSequence) searchLoading.value = false;
  }
}

function scheduleSearch() {
  window.clearTimeout(searchTimer);
  searchTimer = null;
  const normalizedKeyword = keyword.value.trim();
  const requestSequence = searchRequestSequence + 1;
  searchRequestSequence = requestSequence;
  searchResults.value = [];
  searchError.value = "";
  if (!normalizedKeyword) {
    searchLoading.value = false;
    return;
  }
  searchLoading.value = true;
  searchTimer = window.setTimeout(() => {
    searchTimer = null;
    runSearch(normalizedKeyword, requestSequence);
  }, 300);
}

function retrySearch() {
  window.clearTimeout(searchTimer);
  searchTimer = null;
  const normalizedKeyword = keyword.value.trim();
  if (!normalizedKeyword) return;
  const requestSequence = searchRequestSequence + 1;
  searchRequestSequence = requestSequence;
  searchLoading.value = true;
  searchError.value = "";
  runSearch(normalizedKeyword, requestSequence);
}

function selectProvince(province) {
  selectedProvinceCode.value = province.code;
  selectedCityCode.value = province.cities[0]?.code || "";
}

function selectCity(city) {
  selectedCityCode.value = city.code;
}

function openSearchResult(result) {
  selectedProvinceCode.value = result.provinceCode;
  selectedCityCode.value = result.cityCode;
  keyword.value = "";
}

watch([selectedProvinceCode, selectedCityCode, keyword], syncUrlState);
watch(keyword, scheduleSearch, { immediate: true });
onMounted(loadDirectory);
onBeforeUnmount(() => {
  window.clearTimeout(searchTimer);
  searchRequestSequence += 1;
  directoryRequestSequence += 1;
});
</script>

<template>
  <section
    id="auth-administrative-regions-panel"
    class="flex h-full min-h-0 flex-col overflow-hidden rounded-[8px] border border-slate-200 bg-white shadow-sm"
    role="tabpanel"
    aria-labelledby="auth-administrative-regions-tab"
  >
    <header class="flex min-h-14 shrink-0 items-center justify-between gap-4 border-b border-slate-200 px-4">
      <div class="flex min-w-0 items-center gap-3">
        <div class="flex h-9 w-9 shrink-0 items-center justify-center rounded-[8px] bg-blue-50 text-blue-600" aria-hidden="true">
          <MapPinned class="h-4.5 w-4.5" />
        </div>
        <div class="min-w-0">
          <h1 class="text-base font-semibold text-slate-900">省市区域</h1>
          <p v-if="!directoryLoading && !directoryError" class="mt-0.5 text-xs tabular-nums text-slate-500">
            {{ administrativeRegionStats.provinces }} 个省级 · {{ administrativeRegionStats.cities }} 个市级 · {{ administrativeRegionStats.districts }} 个区县
          </p>
        </div>
      </div>

      <div class="relative w-full max-w-[360px] shrink-0" role="search">
        <label for="administrative-region-search" class="sr-only">搜索省市区名称、行政区代码或拼音</label>
        <Search class="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" aria-hidden="true" />
        <input
          id="administrative-region-search"
          v-model="keyword"
          type="search"
          class="h-9 w-full rounded-md border border-slate-200 bg-white pl-9 pr-9 text-sm text-slate-800 outline-none placeholder:text-slate-400 focus:border-blue-400 focus:ring-2 focus:ring-blue-100"
          placeholder="名称、代码或拼音"
          autocomplete="off"
        />
        <button
          v-if="keyword"
          type="button"
          class="absolute right-1.5 top-1/2 inline-flex h-7 w-7 -translate-y-1/2 items-center justify-center rounded-md text-slate-400 hover:bg-slate-100 hover:text-slate-700"
          aria-label="清除区域搜索"
          @click="keyword = ''"
        >
          <X class="h-4 w-4" aria-hidden="true" />
        </button>
      </div>
    </header>

    <div
      v-if="keyword.trim()"
      class="min-h-0 flex-1 overflow-auto"
      role="region"
      aria-label="行政区域搜索结果"
      :aria-busy="searchLoading"
    >
      <div v-if="searchLoading" class="flex min-h-64 items-center justify-center gap-2 text-sm text-slate-500" role="status">
        <LoaderCircle class="h-4 w-4 animate-spin" aria-hidden="true" />正在搜索行政区域...
      </div>
      <div v-else-if="searchError" class="flex min-h-64 flex-col items-center justify-center gap-3 p-6 text-sm text-red-600" role="alert">
        <span>{{ searchError }}</span>
        <button type="button" class="inline-flex h-8 items-center gap-1.5 rounded-md bg-blue-600 px-3 font-medium text-white hover:bg-blue-700" @click="retrySearch">
          <RefreshCw class="h-3.5 w-3.5" aria-hidden="true" />重新搜索
        </button>
      </div>
      <table v-else class="w-full table-fixed border-separate border-spacing-0 text-sm">
        <caption class="sr-only">省市区行政区域搜索结果</caption>
        <colgroup>
          <col class="w-24" />
          <col class="w-48" />
          <col />
          <col class="w-32" />
        </colgroup>
        <thead class="sticky top-0 z-10 bg-slate-50 text-slate-700">
          <tr>
            <th scope="col" class="border-b border-r border-slate-200 px-4 py-3 text-left font-semibold">级别</th>
            <th scope="col" class="border-b border-r border-slate-200 px-4 py-3 text-left font-semibold">行政区域</th>
            <th scope="col" class="border-b border-r border-slate-200 px-4 py-3 text-left font-semibold">完整路径</th>
            <th scope="col" class="border-b border-slate-200 px-4 py-3 text-left font-semibold">行政区代码</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="result in searchResults" :key="`${result.level}-${result.code}`" class="odd:bg-white even:bg-slate-50/50 hover:bg-blue-50/60">
            <td class="border-b border-r border-slate-100 px-4 py-2.5 text-slate-500">{{ result.levelLabel }}</td>
            <td class="border-b border-r border-slate-100 p-0">
              <button type="button" class="w-full px-4 py-2.5 text-left font-medium text-blue-700 hover:text-blue-800" @click="openSearchResult(result)">
                {{ result.name }}
              </button>
            </td>
            <td class="truncate border-b border-r border-slate-100 px-4 py-2.5 text-slate-700" :title="result.path">{{ result.path }}</td>
            <td class="border-b border-slate-100 px-4 py-2.5 font-mono tabular-nums text-slate-600">{{ result.code }}</td>
          </tr>
        </tbody>
      </table>
      <div v-if="!searchLoading && !searchError && !searchResults.length" class="flex h-full min-h-64 items-center justify-center text-sm text-slate-400">
        没有匹配的省市区
      </div>
    </div>

    <div v-else-if="directoryLoading" class="flex min-h-64 flex-1 items-center justify-center gap-2 text-sm text-slate-500" role="status">
      <LoaderCircle class="h-4 w-4 animate-spin" aria-hidden="true" />正在加载行政区域...
    </div>
    <div v-else-if="directoryError" class="flex min-h-64 flex-1 flex-col items-center justify-center gap-3 p-6 text-sm text-red-600" role="alert">
      <span>{{ directoryError }}</span>
      <button type="button" class="inline-flex h-8 items-center gap-1.5 rounded-md bg-blue-600 px-3 font-medium text-white hover:bg-blue-700" @click="loadDirectory">
        <RefreshCw class="h-3.5 w-3.5" aria-hidden="true" />重新加载行政区域
      </button>
    </div>
    <div v-else-if="!administrativeRegions.length" class="flex min-h-64 flex-1 items-center justify-center text-sm text-slate-400" role="status">
      暂无行政区域数据
    </div>
    <div v-else class="administrative-region-columns grid min-h-0 flex-1 divide-x divide-slate-200">
      <section class="flex min-h-0 min-w-0 flex-col" aria-labelledby="province-directory-title">
        <header class="flex h-11 shrink-0 items-center justify-between border-b border-slate-200 bg-slate-50 px-3">
          <h2 id="province-directory-title" class="text-sm font-semibold text-slate-800">省级行政区</h2>
          <span class="text-xs tabular-nums text-slate-500">{{ administrativeRegions.length }}</span>
        </header>
        <nav class="min-h-0 flex-1 overflow-y-auto p-2" aria-label="省级行政区">
          <button
            v-for="province in administrativeRegions"
            :key="province.code"
            type="button"
            class="flex h-10 w-full min-w-0 items-center gap-2 rounded-md px-2.5 text-left text-sm transition-colors"
            :class="province.code === selectedProvinceCode ? 'bg-blue-50 font-semibold text-blue-700' : 'text-slate-700 hover:bg-slate-50'"
            :aria-current="province.code === selectedProvinceCode ? 'true' : undefined"
            @click="selectProvince(province)"
          >
            <span class="min-w-0 flex-1 truncate" :title="province.name">{{ province.name }}</span>
            <span class="font-mono text-xs tabular-nums text-slate-400">{{ province.code }}</span>
            <ChevronRight class="h-3.5 w-3.5 shrink-0 text-slate-400" aria-hidden="true" />
          </button>
        </nav>
      </section>

      <section class="flex min-h-0 min-w-0 flex-col" aria-labelledby="city-directory-title">
        <header class="flex h-11 shrink-0 items-center justify-between border-b border-slate-200 bg-slate-50 px-3">
          <h2 id="city-directory-title" class="min-w-0 truncate text-sm font-semibold text-slate-800" :title="`${selectedProvince?.name || ''}市级行政区`">
            {{ selectedProvince?.name || "-" }} · 市级
          </h2>
          <span class="ml-2 text-xs tabular-nums text-slate-500">{{ selectedProvince?.cities.length || 0 }}</span>
        </header>
        <nav class="min-h-0 flex-1 overflow-y-auto p-2" :aria-label="`${selectedProvince?.name || ''}市级行政区`">
          <button
            v-for="city in selectedProvince?.cities || []"
            :key="city.code"
            type="button"
            class="flex h-10 w-full min-w-0 items-center gap-2 rounded-md px-2.5 text-left text-sm transition-colors"
            :class="city.code === selectedCityCode ? 'bg-blue-50 font-semibold text-blue-700' : 'text-slate-700 hover:bg-slate-50'"
            :aria-current="city.code === selectedCityCode ? 'true' : undefined"
            @click="selectCity(city)"
          >
            <span class="min-w-0 flex-1 truncate" :title="city.name">{{ city.name }}</span>
            <span class="font-mono text-xs tabular-nums text-slate-400">{{ city.code }}</span>
            <ChevronRight class="h-3.5 w-3.5 shrink-0 text-slate-400" aria-hidden="true" />
          </button>
        </nav>
      </section>

      <section class="flex min-h-0 min-w-0 flex-col" aria-labelledby="district-directory-title">
        <header class="flex h-11 shrink-0 items-center justify-between border-b border-slate-200 bg-slate-50 px-3">
          <h2 id="district-directory-title" class="min-w-0 truncate text-sm font-semibold text-slate-800" :title="`${selectedCity?.name || ''}区县`">
            {{ selectedCity?.name || "-" }} · 区县
          </h2>
          <span class="ml-2 text-xs tabular-nums text-slate-500">{{ selectedCity?.districts.length || 0 }}</span>
        </header>
        <ul v-if="selectedCity?.districts.length" class="min-h-0 flex-1 overflow-y-auto p-2" :aria-label="`${selectedCity.name}区县`">
          <li v-for="district in selectedCity.districts" :key="district.code" class="flex h-10 min-w-0 items-center gap-3 border-b border-slate-100 px-2.5 text-sm last:border-b-0">
            <MapPinned class="h-3.5 w-3.5 shrink-0 text-slate-400" aria-hidden="true" />
            <span class="min-w-0 flex-1 truncate font-medium text-slate-700" :title="district.name">{{ district.name }}</span>
            <span class="font-mono text-xs tabular-nums text-slate-400">{{ district.code }}</span>
          </li>
        </ul>
        <div v-else class="flex min-h-0 flex-1 items-center justify-center px-4 text-center text-sm text-slate-400">
          该市级行政区暂无区县数据
        </div>
      </section>
    </div>
  </section>
</template>

<style scoped>
.administrative-region-columns {
  grid-template-columns: minmax(0, 0.82fr) minmax(0, 0.95fr) minmax(0, 1.23fr);
}
</style>
