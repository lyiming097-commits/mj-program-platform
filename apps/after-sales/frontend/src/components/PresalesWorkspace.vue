<script setup>
import { defineAsyncComponent, nextTick, onBeforeUnmount, onMounted, ref, shallowRef, watch } from "vue";
import { ChartColumn, ClipboardList } from "@lucide/vue";
import ProjectWorkspace from "@/components/ProjectWorkspace.vue";
const PresalesStatistics = defineAsyncComponent(() => import("@/components/PresalesStatistics.vue"));

const props = defineProps({
  session: { type: Object, default: null },
  focusProjectId: { type: [String, Number], default: "" },
  focusNodeKey: { type: String, default: "" },
  focusRoundId: { type: String, default: "" },
});

const emit = defineEmits(["open-settlement", "dirty-change", "busy-change"]);
const workspaceRef = ref(null);
const desktopQuery = window.matchMedia("(min-width: 841px)");
const isDesktop = shallowRef(desktopQuery.matches);
const activeView = shallowRef(readView());
const statisticsVisited = shallowRef(activeView.value === "statistics");
const statisticsRevision = shallowRef(0);
const workspaceDirty = shallowRef(false);
const workspaceBusy = shallowRef(false);
const tabIds = { projects: "as-presales-projects-tab", statistics: "as-presales-statistics-tab" };

function readView() {
  return isDesktop.value && !props.focusProjectId && new URLSearchParams(window.location.search).get("tab") === "statistics"
    ? "statistics" : "projects";
}
function changeView(view, { writeUrl = true } = {}) {
  if (workspaceDirty.value || workspaceBusy.value) return;
  activeView.value = view;
  if (view === "statistics") statisticsVisited.value = true;
  if (!writeUrl) return;
  const url = new URL(window.location.href);
  if (view === "statistics") {
    url.searchParams.set("tab", "statistics");
    for (const key of ["projectId", "nodeKey", "roundId"]) url.searchParams.delete(key);
  } else url.searchParams.delete("tab");
  window.history.replaceState(window.history.state, "", url);
}
async function onTabKey(event) {
  const targets = { ArrowLeft: activeView.value === "projects" ? "statistics" : "projects",
    ArrowRight: activeView.value === "projects" ? "statistics" : "projects", Home: "projects", End: "statistics" };
  if (!targets[event.key] || workspaceDirty.value || workspaceBusy.value) return;
  event.preventDefault();
  changeView(targets[event.key]);
  await nextTick();
  document.getElementById(tabIds[activeView.value])?.focus();
}
function relayDirty(value) { workspaceDirty.value = value; emit("dirty-change", value); }
function relayBusy(value) { workspaceBusy.value = value; emit("busy-change", value); }
function restoreView() { changeView(readView(), { writeUrl: false }); }
function updateDesktop() { isDesktop.value = desktopQuery.matches; }
watch(() => [props.focusProjectId, props.focusNodeKey, props.focusRoundId], () => {
  if (props.focusProjectId) changeView("projects");
});
onMounted(() => {
  window.addEventListener("popstate", restoreView);
  desktopQuery.addEventListener("change", updateDesktop);
});
onBeforeUnmount(() => {
  window.removeEventListener("popstate", restoreView);
  desktopQuery.removeEventListener("change", updateDesktop);
});
defineExpose({ discard: () => workspaceRef.value?.discard() });
</script>

<template>
  <div class="as-presales-workspace" :class="{ 'is-statistics': isDesktop && activeView === 'statistics' }">
    <nav v-if="isDesktop" class="as-project-detail-tabs as-mall-tabbar as-presales-view-tabs" role="tablist" aria-label="售前服务视图" @keydown="onTabKey">
      <button :id="tabIds.projects" type="button" role="tab" aria-controls="as-presales-projects-panel" :aria-selected="activeView === 'projects'" :tabindex="activeView === 'projects' ? 0 : -1" :class="{ active: activeView === 'projects' }" :disabled="workspaceDirty || workspaceBusy" @click="changeView('projects')"><ClipboardList />项目列表</button>
      <button :id="tabIds.statistics" type="button" role="tab" aria-controls="as-presales-statistics-panel" :aria-selected="activeView === 'statistics'" :tabindex="activeView === 'statistics' ? 0 : -1" :class="{ active: activeView === 'statistics' }" :disabled="workspaceDirty || workspaceBusy" @click="changeView('statistics')"><ChartColumn />统计分析</button>
    </nav>
    <section v-show="!isDesktop || activeView === 'projects'" id="as-presales-projects-panel" :role="isDesktop ? 'tabpanel' : undefined" :aria-labelledby="isDesktop ? tabIds.projects : undefined">
      <ProjectWorkspace
        ref="workspaceRef"
        service-type="presales"
        :active="!isDesktop || activeView === 'projects'"
        :session="props.session"
        :focus-project-id="props.focusProjectId"
        :focus-node-key="props.focusNodeKey"
        :focus-round-id="props.focusRoundId"
        @open-settlement="emit('open-settlement', $event)"
        @dirty-change="relayDirty"
        @busy-change="relayBusy"
        @project-detail-closed="statisticsRevision++"
      />
    </section>
    <section v-if="statisticsVisited && isDesktop" v-show="activeView === 'statistics'" id="as-presales-statistics-panel" role="tabpanel" :aria-labelledby="tabIds.statistics">
      <PresalesStatistics :session="session" :active="activeView === 'statistics'" :refresh-key="statisticsRevision" @open-project="workspaceRef?.openProject($event)" />
    </section>
  </div>
</template>

<style scoped>
.as-presales-view-tabs { margin: 18px 18px 0; }
@media (min-width: 841px) {
  .as-presales-workspace { display: flex; height: calc(100dvh - var(--platform-shell-top-inset, 0px)); min-width: 0; flex-direction: column; }
  .as-presales-workspace.is-statistics { height: auto; min-height: calc(100dvh - var(--platform-shell-top-inset, 0px)); }
  .as-presales-view-tabs { flex-shrink: 0; }
  .as-presales-workspace > section { min-width: 0; min-height: 0; flex: 1; }
  #as-presales-projects-panel :deep(.as-project-page) { height: 100%; }
  #as-presales-statistics-panel { flex: 0 0 auto; }
}
</style>
