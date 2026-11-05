<script setup>
import { computed, onBeforeUnmount, shallowRef } from "vue";
import VChart from "vue-echarts";
import { registerMap, use } from "echarts/core";
import { MapChart } from "echarts/charts";
import { TooltipComponent, VisualMapComponent } from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import { ChevronDown, MapPin, Users } from "@lucide/vue";
import chinaGeoJson from "@/data/china.json";
import { normalizeAreaName, providerProvinceNames } from "@/data/chinaRegions";

use([MapChart, TooltipComponent, VisualMapComponent, CanvasRenderer]);

const props = defineProps({
  providers: { type: Array, default: () => [] },
});
const mapReady = shallowRef(false);
const collapsed = shallowRef(false);
const desktopQuery = window.matchMedia("(min-width: 841px)");
const desktopPalette = shallowRef(desktopQuery.matches);
function updatePalette(event) { desktopPalette.value = event.matches; }
desktopQuery.addEventListener("change", updatePalette);
onBeforeUnmount(() => desktopQuery.removeEventListener("change", updatePalette));

try {
  const geoJson = structuredClone(chinaGeoJson);
  geoJson.features = (geoJson.features || []).filter((feature) => feature?.properties?.name !== "南海诸岛");
  registerMap("after-sales-china", geoJson);
  mapReady.value = true;
} catch {
  mapReady.value = false;
}

function escapeHtml(value) {
  return String(value || "").replace(/[&<>'"]/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;",
  })[character]);
}

function providerAreas(provider) {
  const regions = Array.isArray(provider?.regions) ? provider.regions.filter(Boolean) : [];
  return regions.length ? regions : [provider?.city].filter(Boolean);
}

const coverageData = computed(() => {
  const provinces = new Map();
  props.providers.forEach((provider) => {
    const provinceNames = providerProvinceNames(provider);
    provinceNames.forEach((province) => {
      if (!provinces.has(province)) provinces.set(province, { providers: new Map(), areas: new Set() });
      const entry = provinces.get(province);
      entry.providers.set(String(provider.id), provider);
      providerAreas(provider).forEach((area) => entry.areas.add(normalizeAreaName(area)));
    });
  });
  const entries = [...provinces.entries()];
  const maximum = Math.max(1, ...entries.map(([, entry]) => entry.providers.size));
  return entries.map(([name, entry]) => {
    const darkArea = entry.providers.size / maximum >= 0.55;
    return {
      name,
      value: entry.providers.size,
      providerCount: entry.providers.size,
      providerNames: [...entry.providers.values()].map((provider) => provider.name).filter(Boolean),
      areas: [...entry.areas].filter(Boolean),
      label: { color: darkArea ? "#ffffff" : "#344054", fontWeight: darkArea ? 800 : 500 },
    };
  });
});

const coverageProvinceCount = computed(() => coverageData.value.length);
const coverageAreaCount = computed(() => new Set(coverageData.value.flatMap((item) => item.areas)).size);
const maxCoverage = computed(() => Math.max(1, ...coverageData.value.map((item) => item.value)));

const mapOption = computed(() => ({
  backgroundColor: "transparent",
  tooltip: {
    trigger: "item",
    confine: true,
    backgroundColor: "rgba(255,255,255,.98)",
    borderColor: desktopPalette.value ? "#dbe5ef" : "#dbe5df",
    padding: 10,
    extraCssText: "max-width:300px;white-space:normal;overflow-wrap:anywhere;box-sizing:border-box;",
    textStyle: { color: "#344054", fontSize: 11 },
    formatter: ({ name, data }) => {
      if (!data?.providerCount) return `<strong>${escapeHtml(name)}</strong><br><span style="color:#98a2b3">暂无服务人员覆盖</span>`;
      const people = data.providerNames.map(escapeHtml).join("、") || "-";
      const areas = data.areas.map(escapeHtml).join("、") || "-";
      return `<div style="width:260px;max-width:100%;white-space:normal;line-height:1.55"><strong>${escapeHtml(name)}</strong><div style="margin-top:6px;color:#667085">服务人员：${data.providerCount} 人</div><div style="display:grid;grid-template-columns:58px minmax(0,1fr);gap:4px;margin-top:3px;color:#667085"><span>人员：</span><span style="min-width:0;white-space:normal;overflow-wrap:anywhere">${people}</span></div><div style="display:grid;grid-template-columns:58px minmax(0,1fr);gap:4px;margin-top:3px;color:#667085"><span>覆盖区域：</span><span style="min-width:0;white-space:normal;overflow-wrap:anywhere">${areas}</span></div></div>`;
    },
  },
  visualMap: {
    show: true,
    left: 16,
    bottom: 14,
    min: 0,
    max: maxCoverage.value,
    itemWidth: 12,
    itemHeight: 78,
    text: [`${maxCoverage.value} 人`, "0 人"],
    textStyle: { color: "#667085", fontSize: 9 },
    calculable: false,
    inRange: { color: desktopPalette.value
      ? ["#eff6ff", "#bfdbfe", "#60a5fa", "#2563eb", "#1746a2"]
      : ["#e8f2ed", "#afd4c1", "#6fb28e", "#2e8b62", "#155f45"] },
  },
  series: [{
    name: "服务人员覆盖",
    type: "map",
    map: "after-sales-china",
    roam: false,
    selectedMode: false,
    layoutCenter: ["50%", "50%"],
    layoutSize: "125%",
    label: { show: true, color: "#526273", fontSize: 9 },
    itemStyle: { areaColor: desktopPalette.value ? "#f1f5f9" : "#eef3f0", borderColor: desktopPalette.value ? "#a9bed8" : "#9bb6a8", borderWidth: 1 },
    emphasis: {
      itemStyle: { areaColor: "#d5a637", borderColor: "#ffffff", borderWidth: 1 },
      label: { show: true, color: "#172033", fontWeight: 700 },
    },
    data: coverageData.value,
  }],
}));

</script>

<template>
  <section class="as-team-coverage-map" aria-label="全国服务人员覆盖地图">
    <header class="as-team-coverage-map__head">
      <div><h2>全国服务覆盖</h2><p>按服务人员维护的城市与区域统计</p></div>
      <div class="as-team-coverage-map__summary"><span><Users />{{ providers.length }} 人</span><span><MapPin />{{ coverageProvinceCount }} 个省份 · {{ coverageAreaCount }} 个区域</span><button type="button" class="as-team-coverage-map__toggle" :class="{ collapsed }" :title="collapsed ? '展开地图' : '收起地图'" :aria-label="collapsed ? '展开全国服务覆盖' : '收起全国服务覆盖'" :aria-expanded="!collapsed" @click="collapsed = !collapsed"><ChevronDown /></button></div>
    </header>
    <div v-show="!collapsed" class="as-team-coverage-map__body">
      <div v-if="!mapReady" class="as-empty as-empty--compact">地图数据加载失败</div>
      <VChart v-else class="as-team-coverage-map__chart" :option="mapOption" autoresize />
    </div>
  </section>
</template>

<style scoped>
.as-team-coverage-map { min-width: 0; overflow: hidden; border: 1px solid #dbe5ef; border-radius: 8px; background: var(--as-positive-bg, #f4f8f6); margin-bottom: 14px; }
.as-team-coverage-map__head { display: flex; min-height: 58px; align-items: center; justify-content: space-between; gap: 16px; border-bottom: 1px solid #dbe5ef; background: #fff; padding: 10px 14px; }
.as-team-coverage-map__head h2 { margin: 0; color: #172033; font-size: 14px; }
.as-team-coverage-map__head p { margin: 3px 0 0; color: #7b8da3; font-size: 9px; }
.as-team-coverage-map__summary { display: flex; flex-wrap: wrap; align-items: center; justify-content: flex-end; gap: 7px; }
.as-team-coverage-map__summary span, .as-team-coverage-map__summary button { display: inline-flex; min-height: 28px; align-items: center; gap: 5px; border: 1px solid var(--as-positive-border, #d7e2dc); border-radius: 6px; background: #fff; padding: 0 9px; color: #526273; font-size: 9px; font-weight: 750; }
.as-team-coverage-map__summary svg { width: 13px; height: 13px; color: var(--as-positive-text, #2e8b62); }
.as-team-coverage-map__summary button { cursor: pointer; }
.as-team-coverage-map__summary .as-team-coverage-map__toggle { width: 28px; justify-content: center; padding: 0; }
.as-team-coverage-map__toggle svg { width: 14px; height: 14px; transition: transform 160ms ease; }
.as-team-coverage-map__toggle.collapsed svg { transform: rotate(-90deg); }
.as-team-coverage-map__body { min-height: 430px; }
.as-team-coverage-map__chart { width: 100%; height: 430px; }
@media (max-width: 840px) { .as-team-coverage-map__head { align-items: flex-start; flex-direction: column; } .as-team-coverage-map__summary { justify-content: flex-start; } }
</style>
