<script setup>
import { onBeforeUnmount, shallowRef, useTemplateRef } from "vue";
import { LocateFixed, MapPin, Navigation, Search, X } from "lucide-vue-next";
import { useAmapPicker } from "@/composables/useAmapPicker";
import AppDrawer from "@/shared/AppDrawer.vue";

const props = defineProps({ open: Boolean, readonly: Boolean, initial: { type: Object, default: () => ({}) } });
const emit = defineEmits(["close", "select"]);
const mapElement = useTemplateRef("map");
const { places, centerAddress, loading, locating, notice, error, locate, searchPlaces, chooseCenter, choosePlace } = useAmapPicker(mapElement, props.initial, { viewOnly: props.readonly });
const placeQuery = shallowRef("");
let searchTimer;
function select(value) { if (!props.readonly && value) emit("select", value); }
function runSearch() { window.clearTimeout(searchTimer); searchPlaces(placeQuery.value); }
function scheduleSearch() { window.clearTimeout(searchTimer); searchTimer = window.setTimeout(runSearch, 260); }
function clearSearch() { placeQuery.value = ""; runSearch(); }
onBeforeUnmount(() => window.clearTimeout(searchTimer));
</script>

<template>
  <AppDrawer :open="open" :title="readonly ? '查看采集地点' : '选择采集地点'" width="720px" nested @close="emit('close')">
    <div class="picker" :class="{ 'is-readonly': readonly }"><div v-if="readonly" class="location-summary"><MapPin :size="17" aria-hidden="true" /><span>{{ initial.location || '暂无具体地点' }}</span></div><form v-else class="place-search" role="search" @submit.prevent="runSearch"><Search :size="16" aria-hidden="true" /><label class="sr-only" for="desktop-place-search">搜索采集地点</label><input id="desktop-place-search" v-model="placeQuery" type="search" placeholder="搜索地点名称或地址" autocomplete="off" @input="scheduleSearch" /><button v-if="placeQuery" type="button" aria-label="清除地点搜索" @click="clearSearch"><X :size="15" /></button></form><section class="map-wrap"><div ref="map" class="map"></div><MapPin v-if="!readonly" class="center-pin" :size="38" fill="#2563eb" /><button v-if="!readonly" class="locate-button" type="button" :disabled="locating" title="回到当前位置" aria-label="回到当前位置" @click="locate"><LocateFixed :size="18" /></button></section><p v-if="notice" class="notice" role="status">{{ notice }}</p><section v-if="!readonly" class="nearby"><header><Navigation :size="15" /><strong>{{ placeQuery.trim() ? '搜索结果' : '附近地点' }}</strong><span aria-live="polite">{{ loading ? '加载中' : `${places.length + 1} 个地点` }}</span></header><button type="button" :disabled="!centerAddress" @click="select(chooseCenter())"><LocateFixed :size="17" /><div><strong>地图中心位置</strong><span>{{ centerAddress || '正在解析地址' }}</span></div></button><button v-for="place in places" :key="place.id" type="button" @click="select(choosePlace(place))"><MapPin :size="17" /><div><strong>{{ place.name }}</strong><span>{{ place.detail }}</span></div><small v-if="place.distance != null">{{ place.distance < 1000 ? `${Math.round(place.distance)} m` : `${(place.distance / 1000).toFixed(1)} km` }}</small></button><div v-if="!loading && error" class="empty-state compact">{{ error }}</div></section></div>
  </AppDrawer>
</template>

<style scoped>
.picker { display: flex; height: calc(100vh - 98px); min-height: 560px; flex-direction: column; margin: -20px; }.place-search{position:relative;display:flex;min-height:52px;flex:0 0 auto;align-items:center;border-bottom:1px solid #dfe6ee;background:#f8fafc;padding:8px 16px}.place-search>svg{position:absolute;left:28px;color:#94a3b8;pointer-events:none}.place-search input{width:100%;height:36px;border:1px solid #cbd5e1;border-radius:7px;outline:0;background:#fff;padding:0 38px;color:#1e293b;font-size:12px}.place-search input:focus{border-color:#2563eb;box-shadow:0 0 0 2px #dbeafe}.place-search input::-webkit-search-cancel-button{display:none}.place-search button{position:absolute;right:20px;display:grid;width:30px;height:30px;place-items:center;border:0;border-radius:5px;background:transparent;color:#64748b}.place-search button:hover{background:#f1f5f9;color:#0f172a}.sr-only{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;clip-path:inset(50%)}.map-wrap { position: relative; height: 44%; min-height: 280px; border-bottom: 1px solid #dfe6ee; }.map { position: absolute; inset: 0; }.center-pin { position: absolute; top: 50%; left: 50%; transform: translate(-50%, -100%); color: #fff; filter: drop-shadow(0 4px 5px rgba(15,23,42,.25)); }.locate-button { position: absolute; right: 16px; bottom: 16px; display: grid; width: 40px; height: 40px; place-items: center; border: 1px solid #d5dfeb; border-radius: 6px; background: #fff; color: #2563eb; box-shadow: 0 4px 14px rgba(15,23,42,.16); }.notice { margin: 0; border-bottom: 1px solid #fde68a; background: #fffbeb; padding: 8px 16px; color: #92400e; font-size: 10px; }.nearby { min-height: 0; flex: 1; overflow-y: auto; }.nearby > header { display: flex; height: 42px; align-items: center; gap: 7px; border-bottom: 1px solid #dfe6ee; padding: 0 16px; color: #2563eb; }.nearby header strong { color: #0f172a; font-size: 12px; }.nearby header span { margin-left: auto; color: #94a3b8; font-size: 10px; }.nearby > button { display: grid; width: 100%; min-height: 64px; grid-template-columns: 32px minmax(0, 1fr) auto; align-items: center; gap: 8px; border: 0; border-bottom: 1px solid #edf1f5; background: #fff; padding: 9px 16px; color: #475569; text-align: left; }.nearby > button:hover { background: #f8fbff; }.nearby button div { min-width: 0; }.nearby button strong, .nearby button span { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }.nearby button strong { color: #0f172a; font-size: 12px; }.nearby button span { margin-top: 4px; color: #64748b; font-size: 10px; }.nearby button small { color: #94a3b8; font-size: 9px; }.compact { min-height: 80px; }
.location-summary { display: flex; min-height: 52px; flex: 0 0 auto; align-items: center; gap: 8px; border-bottom: 1px solid #dfe6ee; background: #f8fafc; padding: 12px 16px; color: #334155; font-size: 13px; line-height: 1.5; }
.location-summary svg { flex: 0 0 auto; color: #2563eb; }
.location-summary span { min-width: 0; overflow-wrap: anywhere; }
.picker.is-readonly .map-wrap { height: auto; min-height: 280px; flex: 1; }
</style>
