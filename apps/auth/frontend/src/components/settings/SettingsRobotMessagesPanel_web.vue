<script setup>
import {
  computed,
  nextTick,
  onBeforeUnmount,
  onMounted,
  reactive,
  ref,
  watch,
} from "vue";
import {
  MessageSquare,
  Plus,
  Search,
  Send,
  Users,
  UserRound,
  X,
  RefreshCw,
  ImagePlus,
} from "@lucide/vue";
import {
  PlatformDetailDrawer,
  PlatformSearchSelect,
  PlatformRichTextEditor,
  preparePastedImage,
} from "@platform-ui";
import { backdropDismiss as vBackdropDismiss } from "@platform-ui/backdrop-dismiss.js";
import { apiGet, apiPost } from "@/api";
import { loadLoginSession } from "@/session";
import SettingsOrganizationPermissionsPanel from "./SettingsOrganizationPermissionsPanel.vue";
import SettingsUnsavedChangesDialog from "./SettingsUnsavedChangesDialog.vue";
import { useSettingsDialog } from "./useSettingsDialog";
import { useSettingsFeedback } from "./useSettingsFeedback";

import RobotMessageContent from "./RobotMessageContent.vue";
import { draftInfo, plainToHtml } from "./robotMessageContent";
import { clearPending, loadPending, storePending } from "./robotMessagePending";

const emit = defineEmits(["dirty-change", "saving-change"]);
const base = "/api/org/robot-messages";
const showFeedback = useSettingsFeedback();
const session = loadLoginSession();
const pendingKey = `mj_robot_pending:${session?.userId}:${session?.actorUserId || session?.userId}`;
const activeTab = ref(
  new URLSearchParams(location.search).get("tab") === "permissions"
    ? "permissions"
    : "send",
);
const capability = ref(null),
  loading = ref(true),
  error = ref("");
const groups = ref([]),
  people = ref([]),
  peopleTotal = ref(0);
const selectedGroups = ref([]),
  selectedPeople = ref([]),
  content = ref("");
const messageEditor = ref(null),
  imageInput = ref(null),
  imageProcessing = ref(false),
  detailPreviewOpen = ref(false);
const messageDraft = computed(() => draftInfo(content.value));
const hasMessage = computed(() =>
  Boolean(messageDraft.value.text || messageDraft.value.imageCount),
);
const draftError = computed(() =>
  messageDraft.value.imageCount > (capability.value?.maxImages || 6)
    ? "每条消息最多添加 6 张图片"
    : messageDraft.value.imageBytes >
        (capability.value?.maxImageBytes || 8 * 1024 * 1024)
      ? "单条消息的图片总大小不能超过 8 MB"
      : "",
);
const records = ref([]),
  historyTotal = ref(0),
  page = ref(1);
const historyLoading = ref(false),
  historyError = ref(""),
  groupsError = ref("");
const permissionPanel = ref(null),
  permissionDirty = ref(false),
  permissionSaving = ref(false);
const submitting = ref(false),
  pendingRequest = ref(null);
const composeOpen = ref(false),
  composePanel = ref(null),
  pickerTab = ref("group"),
  keyword = ref("");
const peopleLoading = ref(false),
  peopleError = ref("");
const groupOpen = ref(false),
  groupName = ref(""),
  groupCid = ref(""),
  groupSaving = ref(false),
  groupError = ref("");
const leaveOpen = ref(false);
const filterKeys = ["sentDate", "sender", "target", "content", "status"];
const historyFilters = reactive(
  Object.fromEntries(
    filterKeys.map((key) => [
      key,
      new URLSearchParams(location.search).get(key) || "",
    ]),
  ),
);
const selectedRecord = ref(null);
const detailRecord = computed(
  () =>
    records.value.find(
      (item) => item.requestId === selectedRecord.value?.requestId,
    ) || selectedRecord.value,
);
const hasFilters = computed(() =>
  filterKeys.some((key) => historyFilters[key].trim()),
);
const createDirty = computed(() =>
  Boolean(hasMessage.value || count.value || pendingRequest.value),
);
let leaveAction = null,
  searchTimer,
  historyTimer,
  pollTimer,
  peopleSeq = 0,
  historySeq = 0,
  disposed = false;
const labels = {
  pending: "排队中",
  sending: "发送中",
  accepted: "钉钉已受理",
  failed: "发送失败",
  unknown: "结果待核实",
  partial: "部分失败",
};
const statusOptions = [
  "sending",
  "accepted",
  "failed",
  "unknown",
  "partial",
].map((value) => ({ value, label: labels[value] }));
const count = computed(
  () => selectedGroups.value.length + selectedPeople.value.length,
);
const dirty = computed(() =>
  Boolean(
    hasMessage.value ||
      count.value ||
      pendingRequest.value ||
      permissionDirty.value ||
      (groupOpen.value && (groupName.value || groupCid.value)),
  ),
);
const busy = computed(
  () =>
    submitting.value ||
    imageProcessing.value ||
    permissionSaving.value ||
    groupSaving.value,
);
const sendDisabled = computed(
  () =>
    !capability.value?.configured ||
    !hasMessage.value ||
    Boolean(draftError.value) ||
    imageProcessing.value ||
    !count.value ||
    count.value > (capability.value?.maxTargets || 100) ||
    submitting.value ||
    Boolean(pendingRequest.value),
);
const filteredGroups = computed(() =>
  groups.value.filter((g) =>
    g.name.toLowerCase().includes(keyword.value.trim().toLowerCase()),
  ),
);
const formatTime = (value) =>
  value
    ? new Date(value).toLocaleString("zh-CN", {
        hour12: false,
        timeZone: "Asia/Shanghai",
      })
    : "";
const targetKey = (target) => String(target.userId ?? target.id);
const isSelected = (target) =>
  (pickerTab.value === "group"
    ? selectedGroups.value
    : selectedPeople.value
  ).some((item) => targetKey(item) === targetKey(target));

function guard(action) {
  if (busy.value) return false;
  if (!dirty.value) {
    action();
    return true;
  }
  leaveAction = action;
  leaveOpen.value = true;
  return false;
}
function switchTab(tab, focus = false) {
  if (tab === activeTab.value) return;
  guard(() => {
    content.value =
      pendingRequest.value?.contentHtml ??
      plainToHtml(pendingRequest.value?.content);
    selectedGroups.value = [];
    selectedPeople.value = [];
    permissionDirty.value = false;
    composeOpen.value = false;
    activeTab.value = tab;
    const url = new URL(location.href);
    url.searchParams.set("tab", tab);
    history.replaceState({}, "", url);
    if (focus)
      nextTick(() => document.getElementById(`robot-${tab}-tab`)?.focus());
  });
}
function tabKeydown(event) {
  if (
    !["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key) ||
    !capability.value?.canManage
  )
    return;
  event.preventDefault();
  switchTab(
    event.key === "Home"
      ? "send"
      : event.key === "End"
        ? "permissions"
        : activeTab.value === "send"
          ? "permissions"
          : "send",
    true,
  );
}
function discardAndContinue() {
  leaveOpen.value = false;
  const action = leaveAction;
  leaveAction = null;
  action?.();
}
function openCompose() {
  if (busy.value) return;
  error.value = "";
  choosePickerTab("group");
  composeOpen.value = true;
}
function closeCompose() {
  if (busy.value || groupOpen.value || leaveOpen.value) return;
  const close = () => {
    composeOpen.value = false;
    if (!pendingRequest.value) {
      content.value = "";
      selectedGroups.value = [];
      selectedPeople.value = [];
    }
    error.value = "";
  };
  if (createDirty.value) {
    leaveAction = close;
    leaveOpen.value = true;
  } else close();
}
function choosePickerTab(tab) {
  pickerTab.value = tab;
  keyword.value = "";
}
function pickerTabKeydown(event) {
  if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
  event.preventDefault();
  choosePickerTab(
    event.key === "Home"
      ? "group"
      : event.key === "End"
        ? "person"
        : pickerTab.value === "group"
          ? "person"
          : "group",
  );
  nextTick(() =>
    document
      .getElementById(
        pickerTab.value === "group"
          ? "robot-groups-choice"
          : "robot-people-choice",
      )
      ?.focus(),
  );
}
useSettingsDialog(
  composeOpen,
  composePanel,
  closeCompose,
  () =>
    leaveOpen.value ||
    groupOpen.value ||
    Boolean(document.querySelector(".platform-image-preview")),
);
watch(composeOpen, async (open) => {
  if (open) {
    await nextTick();
    if (composeOpen.value)
      document.getElementById("robot-recipient-search")?.focus();
  }
});
function toggleTarget(target) {
  if (pendingRequest.value || submitting.value) return;
  const list = pickerTab.value === "group" ? selectedGroups : selectedPeople;
  const index = list.value.findIndex(
    (item) => targetKey(item) === targetKey(target),
  );
  if (index >= 0) list.value.splice(index, 1);
  else if (count.value < (capability.value?.maxTargets || 100))
    list.value.push(target);
}
async function loadGroups() {
  groupsError.value = "";
  try {
    groups.value = (await apiGet(`${base}/groups`)).items || [];
  } catch (e) {
    if (!disposed) groupsError.value = e.message;
  }
}
async function loadPeople() {
  const seq = ++peopleSeq;
  peopleLoading.value = true;
  peopleError.value = "";
  try {
    const data = await apiGet(`${base}/people`, {
      keyword: keyword.value.trim(),
    });
    if (seq !== peopleSeq || disposed) return;
    people.value = data.items || [];
    peopleTotal.value = data.total || 0;
  } catch (e) {
    if (seq === peopleSeq && !disposed) peopleError.value = e.message;
  } finally {
    if (seq === peopleSeq) peopleLoading.value = false;
  }
}
watch([keyword, pickerTab], () => {
  clearTimeout(searchTimer);
  ++peopleSeq;
  if (pickerTab.value !== "person") return;
  peopleLoading.value = true;
  searchTimer = setTimeout(loadPeople, 250);
});
async function loadHistory({ quiet = false } = {}) {
  const seq = ++historySeq;
  if (!quiet) historyLoading.value = true;
  historyError.value = "";
  clearTimeout(pollTimer);
  try {
    const data = await apiGet(`${base}/history`, {
      page: page.value,
      ...Object.fromEntries(
        filterKeys.map((key) => [key, historyFilters[key].trim()]),
      ),
    });
    if (seq !== historySeq || disposed) return;
    records.value = data.items || [];
    historyTotal.value = data.total || 0;
    if (records.value.some((record) => record.status === "sending")) {
      pollTimer = setTimeout(() => {
        void loadHistory({ quiet: true });
        void loadGroups();
      }, 3000);
    }
  } catch (e) {
    if (seq === historySeq && !disposed) historyError.value = e.message;
  } finally {
    if (seq === historySeq) historyLoading.value = false;
  }
}
function syncHistoryQuery() {
  const url = new URL(location.href);
  url.searchParams.delete("q");
  url.searchParams.delete("group");
  for (const key of filterKeys) {
    const value = historyFilters[key].trim();
    if (value) url.searchParams.set(key, value);
    else url.searchParams.delete(key);
  }
  history.replaceState({}, "", url);
}
watch(historyFilters, () => {
  clearTimeout(historyTimer);
  ++historySeq;
  page.value = 1;
  syncHistoryQuery();
  historyLoading.value = true;
  historyTimer = setTimeout(() => loadHistory(), 300);
});
function resetFilters() {
  for (const key of filterKeys) historyFilters[key] = "";
}
function refreshHistory() {
  clearTimeout(historyTimer);
  void loadHistory();
}
function changePage(delta) {
  page.value += delta;
  void loadHistory();
}
async function savePending(payload) {
  if (!payload) {
    pendingRequest.value = null;
    await clearPending(pendingKey);
    return;
  }
  await storePending(pendingKey, {
    ...payload,
    recipientLabels: {
      groups: selectedGroups.value.map((g) => ({ id: g.id, name: g.name })),
      people: selectedPeople.value.map((p) => ({
        userId: p.userId,
        name: p.name,
      })),
    },
  });
  pendingRequest.value = payload;
}
async function addImages(event) {
  const files = [...(event.target.files || [])];
  event.target.value = "";
  if (!files.length || submitting.value || pendingRequest.value) return;
  error.value = "";
  if (
    messageDraft.value.imageCount + files.length >
    (capability.value?.maxImages || 6)
  ) {
    error.value = "每条消息最多添加 6 张图片";
    return;
  }
  imageProcessing.value = true;
  try {
    const sources = [];
    for (const file of files) sources.push(await preparePastedImage(file));
    const next =
      content.value +
      sources.map((source) => `<p><img src="${source}"></p>`).join("");
    if (
      draftInfo(next).imageBytes >
      (capability.value?.maxImageBytes || 8 * 1024 * 1024)
    )
      throw new Error("单条消息的图片总大小不能超过 8 MB");
    content.value = next;
    await nextTick();
  } catch (e) {
    error.value = e.message;
  } finally {
    imageProcessing.value = false;
    await nextTick();
    messageEditor.value?.focus();
  }
}
function accepted() {
  showFeedback("发送请求已提交，可在发送记录中查看处理结果");
  void savePending(null).catch(() => {});
  content.value = "";
  selectedGroups.value = [];
  selectedPeople.value = [];
  composeOpen.value = false;
  error.value = "";
  resetFilters();
  page.value = 1;
  clearTimeout(historyTimer);
  void loadHistory();
  void loadGroups();
}
async function submitPayload(payload) {
  submitting.value = true;
  error.value = "";
  try {
    await savePending(payload);
  } catch {
    error.value =
      "无法保存本次发送，请检查浏览器存储空间后重试。消息尚未提交。";
    submitting.value = false;
    return;
  }
  try {
    const { requestId, content, contentHtml, groupIds, userIds } = payload;
    const body = {
      requestId,
      groupIds,
      userIds,
      ...(typeof contentHtml === "string" ? { contentHtml } : { content }),
    };
    await apiPost(`${base}/send`, body, { timeoutMs: 60000 });
    if (!disposed) accepted();
  } catch (e) {
    if (disposed) return;
    if (
      (e.status >= 400 && e.status < 500 && e.status !== 409) ||
      e.code === "ROBOT_NOT_CONFIGURED"
    ) {
      void savePending(null).catch(() => {});
      error.value = e.message;
    } else {
      error.value =
        "尚未确认本次提交结果。请核对发送状态，系统会沿用同一请求，避免重复发送。";
    }
  } finally {
    submitting.value = false;
  }
}
function send() {
  if (sendDisabled.value) return;
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 15) | 64;
  bytes[8] = (bytes[8] & 63) | 128;
  const hex = [...bytes].map((b) => b.toString(16).padStart(2, "0")).join("");
  const requestId = `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
  void submitPayload({
    requestId,
    contentHtml: messageDraft.value.html,
    groupIds: selectedGroups.value.map((g) => g.id),
    userIds: selectedPeople.value.map((p) => String(p.userId)),
  });
}
async function recoverPending(resubmit = false) {
  if (!pendingRequest.value || submitting.value) return;
  submitting.value = true;
  try {
    await apiGet(`${base}/requests/${pendingRequest.value.requestId}`);
    if (!disposed) accepted();
  } catch (e) {
    if (disposed) return;
    if (e.status === 404 && resubmit) {
      submitting.value = false;
      await submitPayload(pendingRequest.value);
    } else
      error.value =
        e.status === 404
          ? "尚未找到发送记录，可核对并继续提交本次发送。"
          : "暂时无法核对发送状态，请稍后重试。";
  } finally {
    submitting.value = false;
  }
}
function closeGroup() {
  if (groupSaving.value) return;
  if (groupName.value || groupCid.value) {
    leaveAction = () => {
      groupOpen.value = false;
      groupName.value = "";
      groupCid.value = "";
    };
    leaveOpen.value = true;
  } else groupOpen.value = false;
}
async function registerGroup() {
  if (groupSaving.value) return;
  groupSaving.value = true;
  groupError.value = "";
  try {
    await apiPost(`${base}/groups`, {
      name: groupName.value.trim(),
      openConversationId: groupCid.value.trim(),
    });
    groupOpen.value = false;
    groupName.value = "";
    groupCid.value = "";
    showFeedback("通知群已登记");
    await loadGroups();
  } catch (e) {
    groupError.value = e.message;
  } finally {
    groupSaving.value = false;
  }
}
async function initialize() {
  loading.value = true;
  error.value = "";
  try {
    capability.value = await apiGet(`${base}/capabilities`);
    if (!capability.value.canManage) activeTab.value = "send";
    if (capability.value.canSend) {
      await Promise.all([loadGroups(), loadHistory()]);
      try {
        const pending = await loadPending(pendingKey);
        if (pending?.requestId) {
          pendingRequest.value = pending;
          content.value = pending.contentHtml ?? plainToHtml(pending.content);
          selectedGroups.value = (pending.groupIds || []).map(
            (id) =>
              groups.value.find((g) => g.id === id) ||
              pending.recipientLabels?.groups?.find((g) => g.id === id) || {
                id,
                name: `群聊 ${id}`,
              },
          );
          selectedPeople.value = (pending.userIds || []).map(
            (userId) =>
              pending.recipientLabels?.people?.find(
                (p) => p.userId === userId,
              ) || { userId, name: userId },
          );
          await recoverPending();
        }
      } catch {
        /* ignore invalid local recovery state */
      }
    }
  } catch (e) {
    error.value = e.message;
  } finally {
    loading.value = false;
  }
}
function startTableDrag(event) {
  event.currentTarget.dataset.dragged = "false";
  if (
    event.button !== 0 ||
    event.target?.closest?.(
      'button,input,textarea,select,a,[contenteditable="true"],[role="option"]',
    )
  )
    return;
  const el = event.currentTarget;
  el.dataset.isDown = "true";
  el.dataset.dragged = "false";
  el.dataset.startX = String(event.pageX);
  el.dataset.scrollLeft = String(el.scrollLeft);
}

function moveTableDrag(event) {
  const el = event.currentTarget;
  if (el.dataset.isDown !== "true") return;
  const walk = (event.pageX - Number(el.dataset.startX || 0)) * 1.2;
  if (Math.abs(walk) > 5) {
    el.dataset.dragged = "true";
    event.preventDefault();
  }
  el.scrollLeft = Number(el.dataset.scrollLeft || 0) - walk;
}

function endTableDrag(event) {
  event.currentTarget.dataset.isDown = "false";
}

function scrollTableByKeyboard(event) {
  if (
    event.target !== event.currentTarget ||
    !["ArrowLeft", "ArrowRight"].includes(event.key)
  )
    return;
  event.preventDefault();
  event.currentTarget.scrollLeft += event.key === "ArrowRight" ? 120 : -120;
}

function suppressDraggedClick(event) {
  if (event.currentTarget.dataset.dragged !== "true") return;
  event.currentTarget.dataset.dragged = "false";
  event.preventDefault();
  event.stopPropagation();
}

watch(dirty, (value) => emit("dirty-change", value), { immediate: true });
watch(busy, (value) => emit("saving-change", value), { immediate: true });
onMounted(initialize);
onBeforeUnmount(() => {
  disposed = true;
  ++peopleSeq;
  ++historySeq;
  clearTimeout(searchTimer);
  clearTimeout(historyTimer);
  clearTimeout(pollTimer);
  emit("dirty-change", false);
  emit("saving-change", false);
});
defineExpose({
  hasPendingChanges: () => dirty.value,
  isSaveInProgress: () => busy.value,
});
</script>

<template>
  <div
    class="robot-page flex min-h-0 min-w-0 flex-1 flex-col"
    :inert="
      composeOpen || groupOpen || selectedRecord || leaveOpen ? true : undefined
    "
  >
    <nav class="robot-tabs" aria-label="机器人群发页面">
      <div role="tablist" aria-label="机器人群发" @keydown="tabKeydown">
        <button
          id="robot-send-tab"
          type="button"
          role="tab"
          :aria-selected="activeTab === 'send'"
          aria-controls="robot-send-panel"
          :tabindex="activeTab === 'send' ? 0 : -1"
          :disabled="busy"
          @click="switchTab('send')"
        >
          发送历史
        </button>
        <button
          v-if="capability?.canManage"
          id="robot-permissions-tab"
          type="button"
          role="tab"
          :aria-selected="activeTab === 'permissions'"
          aria-controls="robot-permissions-panel"
          :tabindex="activeTab === 'permissions' ? 0 : -1"
          :disabled="busy"
          @click="switchTab('permissions')"
        >
          权限管理
        </button>
      </div>
    </nav>
    <p v-if="loading" class="robot-notice" role="status">正在加载发送历史…</p>
    <div v-else-if="!capability" class="robot-notice" role="alert">
      {{ error }}
      <button class="robot-button" @click="initialize">重新加载</button>
    </div>
    <p v-else-if="!capability.canSend" class="robot-notice">
      当前账号没有机器人发送权限，请联系后台管理员开通。
    </p>
    <template v-else>
      <section
        v-if="activeTab === 'permissions'"
        id="robot-permissions-panel"
        role="tabpanel"
        aria-labelledby="robot-permissions-tab"
        class="flex min-h-0 flex-1"
      >
        <SettingsOrganizationPermissionsPanel
          ref="permissionPanel"
          :api-path="`${base}/permissions`"
          permission-label="机器人发送权限"
          member-label="发送人员"
          permission-note="可向登记群聊和启用员工发送消息。后台管理员始终可发送并管理权限；此处授权不包含后台管理权限。"
          @dirty-change="permissionDirty = $event"
          @saving-change="permissionSaving = $event"
        />
      </section>
      <section
        v-else
        id="robot-send-panel"
        role="tabpanel"
        aria-labelledby="robot-send-tab"
        class="robot-ledger"
      >
        <header class="robot-toolbar">
          <div class="robot-toolbar-title">
            <h2>发送历史记录</h2>
            <span class="robot-muted">{{
              capability.canManage ? "全部人员的发送记录" : "我的发送记录"
            }}</span>
          </div>
          <div class="robot-toolbar-actions">
            <button
              v-if="hasFilters"
              type="button"
              class="robot-button"
              @click="resetFilters"
            >
              重置筛选
            </button>
            <button
              v-if="capability.canManage"
              type="button"
              class="robot-button"
              @click="groupOpen = true"
            >
              登记群聊
            </button>
            <button
              type="button"
              class="robot-button"
              :disabled="historyLoading"
              @click="refreshHistory"
            >
              <RefreshCw :size="14" />刷新
            </button>
            <button
              type="button"
              class="robot-button robot-primary"
              :disabled="!capability.configured || busy"
              @click="openCompose"
            >
              <Plus :size="16" />发送消息
            </button>
          </div>
        </header>
        <p
          v-if="!capability.configured"
          role="alert"
          class="robot-error robot-banner"
        >
          尚未配置钉钉机器人，请联系管理员。
        </p>
        <p v-if="groupsError" role="alert" class="robot-error robot-banner">
          {{ groupsError }}
          <button class="robot-text-button" @click="loadGroups">
            重新加载群聊
          </button>
        </p>
        <div
          v-if="pendingRequest"
          class="robot-pending robot-banner"
          role="status"
        >
          <span>有一笔发送尚未确认结果。</span
          ><button
            type="button"
            class="robot-text-button"
            :disabled="busy"
            @click="openCompose"
          >
            查看待确认发送
          </button>
        </div>
        <p v-if="historyError" role="alert" class="robot-error robot-banner">
          {{ historyError }}
          <button class="robot-text-button" @click="refreshHistory">
            重试
          </button>
        </p>
        <div
          class="robot-table-scroll"
          tabindex="0"
          role="region"
          aria-label="发送历史表格，可拖拽或使用左右键横向浏览"
          :aria-busy="historyLoading"
          @keydown="scrollTableByKeyboard"
          @click.capture="suppressDraggedClick"
          @mousedown="startTableDrag"
          @mousemove="moveTableDrag"
          @mouseup="endTableDrag"
          @mouseleave="endTableDrag"
        >
          <table class="robot-table">
            <caption class="sr-only">
              发送历史记录
            </caption>
            <colgroup>
              <col class="robot-col-number" />
              <col class="robot-col-time" />
              <col class="robot-col-sender" />
              <col class="robot-col-targets" />
              <col />
              <col class="robot-col-status" />
              <col class="robot-col-action" />
            </colgroup>
            <thead>
              <tr>
                <th scope="col">序号</th>
                <th scope="col" aria-sort="descending" title="北京时间">
                  发送时间
                </th>
                <th scope="col">发送人</th>
                <th scope="col">发送对象</th>
                <th scope="col">消息内容</th>
                <th scope="col">发送结果</th>
                <th scope="col">操作</th>
              </tr>
              <tr class="robot-filter-row" aria-label="发送历史列筛选">
                <td></td>
                <td>
                  <input
                    v-model="historyFilters.sentDate"
                    type="date"
                    class="robot-column-input"
                    :class="{ 'is-active': historyFilters.sentDate }"
                    aria-label="筛选发送日期"
                    title="按北京时间筛选"
                  />
                </td>
                <td>
                  <input
                    v-model="historyFilters.sender"
                    class="robot-column-input"
                    :class="{ 'is-active': historyFilters.sender }"
                    aria-label="筛选发送人"
                    placeholder="姓名"
                    maxlength="100"
                    @keydown.enter.prevent="refreshHistory"
                  />
                </td>
                <td>
                  <input
                    v-model="historyFilters.target"
                    class="robot-column-input"
                    :class="{ 'is-active': historyFilters.target }"
                    aria-label="筛选发送对象"
                    placeholder="群聊或人员"
                    maxlength="100"
                    @keydown.enter.prevent="refreshHistory"
                  />
                </td>
                <td>
                  <input
                    v-model="historyFilters.content"
                    class="robot-column-input"
                    :class="{ 'is-active': historyFilters.content }"
                    aria-label="筛选消息内容"
                    placeholder="消息内容"
                    maxlength="100"
                    @keydown.enter.prevent="refreshHistory"
                  />
                </td>
                <td>
                  <PlatformSearchSelect
                    v-model="historyFilters.status"
                    :options="statusOptions"
                    aria-label="筛选发送结果"
                    placeholder="全部"
                    search-placeholder="筛选结果"
                    :menu-z-index="90"
                  />
                </td>
                <td></td>
              </tr>
            </thead>
            <tbody>
              <tr v-if="historyLoading">
                <td colspan="7" class="robot-table-empty" role="status">
                  正在加载发送历史…
                </td>
              </tr>
              <tr v-else-if="historyError">
                <td colspan="7" class="robot-table-empty">
                  发送历史加载失败，请重试。
                </td>
              </tr>
              <tr v-else-if="!records.length">
                <td colspan="7" class="robot-table-empty">
                  <MessageSquare :size="24" />
                  <p>
                    {{ hasFilters ? "没有匹配的发送记录" : "暂无发送记录" }}
                  </p>
                  <span class="robot-muted">{{
                    hasFilters
                      ? "调整筛选条件后重试。"
                      : "点击右上角“发送消息”，新增一条发送记录。"
                  }}</span>
                </td>
              </tr>
              <tr
                v-for="(record, index) in records"
                v-else
                :key="record.requestId"
                :data-request-id="record.requestId"
                class="robot-history-row"
                @click="selectedRecord = record"
              >
                <td class="robot-row-number">
                  {{ (page - 1) * 20 + index + 1 }}
                </td>
                <td>
                  <time :datetime="record.createdAt">{{
                    formatTime(record.createdAt)
                  }}</time>
                </td>
                <td>
                  <span>{{ record.senderName }}</span
                  ><small
                    v-if="record.sourceKind === 'application'"
                    class="robot-muted block"
                    >应用通知</small
                  ><small
                    v-if="
                      record.actorName && record.actorName !== record.senderName
                    "
                    class="robot-muted block"
                    >{{ record.actorName }} 代理</small
                  >
                </td>
                <td>
                  <span
                    class="robot-clamp"
                    :title="
                      record.recipients.map((r) => r.targetName).join('、')
                    "
                    >{{
                      record.recipients.map((r) => r.targetName).join("、")
                    }}</span
                  ><small class="robot-muted"
                    >{{
                      record.recipients.filter((r) => r.kind === "group").length
                    }}
                    个群聊 ·
                    {{
                      record.recipients.filter((r) => r.kind === "person")
                        .length
                    }}
                    人</small
                  >
                </td>
                <td>
                  <span
                    class="robot-clamp robot-message-preview"
                    :title="record.content"
                    >{{ record.content }}</span
                  >
                  <div
                    v-if="record.images?.length"
                    class="robot-history-images"
                    aria-label="消息图片缩略图"
                  >
                    <img
                      v-for="image in record.images.slice(0, 3)"
                      :key="image.id"
                      :src="image.url"
                      alt="消息图片"
                      loading="lazy"
                    />
                    <small v-if="record.images.length > 3" class="robot-muted"
                      >共 {{ record.images.length }} 张</small
                    >
                  </div>
                </td>
                <td>
                  <span class="robot-status" :data-status="record.status">{{
                    labels[record.status]
                  }}</span>
                </td>
                <td>
                  <button
                    type="button"
                    class="robot-text-button"
                    :aria-label="`查看第 ${(page - 1) * 20 + index + 1} 条发送记录`"
                    @click.stop="selectedRecord = record"
                  >
                    详情
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <footer class="robot-pagination">
          <span class="robot-muted">共 {{ historyTotal }} 条 · 每页 20 条</span>
          <div>
            <button
              type="button"
              class="robot-button"
              :disabled="page <= 1 || historyLoading"
              @click="changePage(-1)"
            >
              上一页</button
            ><span
              >第 {{ page }} /
              {{ Math.max(1, Math.ceil(historyTotal / 20)) }} 页</span
            ><button
              type="button"
              class="robot-button"
              :disabled="page * 20 >= historyTotal || historyLoading"
              @click="changePage(1)"
            >
              下一页
            </button>
          </div>
        </footer>
      </section>
    </template>
  </div>

  <Teleport to="body">
    <div
      v-if="composeOpen"
      v-backdrop-dismiss="closeCompose"
      class="robot-overlay"
      :inert="groupOpen || leaveOpen ? true : undefined"
    >
      <section
        ref="composePanel"
        class="robot-compose-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="robot-compose-title"
        :aria-busy="submitting"
        tabindex="-1"
      >
        <header class="robot-dialog-header">
          <div class="flex items-center gap-2">
            <Send :size="18" class="text-blue-600" />
            <h2 id="robot-compose-title">发送消息</h2>
          </div>
          <button
            type="button"
            class="robot-icon-button"
            aria-label="关闭发送消息"
            :disabled="submitting || imageProcessing"
            @click="closeCompose"
          >
            <X :size="18" />
          </button>
        </header>
        <form class="robot-compose-form" @submit.prevent="send">
          <div class="robot-dialog-body">
            <div class="robot-field-heading">
              <span id="robot-targets-label"
                >发送对象 <span class="text-red-600">*</span></span
              ><span class="robot-muted"
                >{{ selectedGroups.length }} 个群聊 ·
                {{ selectedPeople.length }} 人 / 最多
                {{ capability.maxTargets }} 个对象</span
              >
            </div>
            <fieldset
              class="robot-recipient-picker"
              :disabled="submitting || !!pendingRequest"
              aria-labelledby="robot-targets-label"
            >
              <div class="robot-picker-tools">
                <div
                  role="tablist"
                  aria-label="发送对象类型"
                  @keydown="pickerTabKeydown"
                >
                  <button
                    id="robot-groups-choice"
                    type="button"
                    role="tab"
                    aria-controls="robot-picker-results"
                    :aria-selected="pickerTab === 'group'"
                    :tabindex="pickerTab === 'group' ? 0 : -1"
                    @click="choosePickerTab('group')"
                  >
                    群聊</button
                  ><button
                    id="robot-people-choice"
                    type="button"
                    role="tab"
                    aria-controls="robot-picker-results"
                    :aria-selected="pickerTab === 'person'"
                    :tabindex="pickerTab === 'person' ? 0 : -1"
                    @click="choosePickerTab('person')"
                  >
                    人员
                  </button>
                </div>
                <label class="robot-search"
                  ><Search :size="15" /><input
                    id="robot-recipient-search"
                    v-model="keyword"
                    :aria-label="
                      pickerTab === 'group' ? '搜索群聊' : '搜索人员'
                    "
                    :placeholder="
                      pickerTab === 'group'
                        ? '搜索已登记群聊'
                        : '姓名、员工 ID、拼音或首字母'
                    "
                /></label>
              </div>
              <div
                id="robot-picker-results"
                class="robot-picker-results"
                role="tabpanel"
                :aria-labelledby="
                  pickerTab === 'group'
                    ? 'robot-groups-choice'
                    : 'robot-people-choice'
                "
              >
                <p
                  v-if="pickerTab === 'person' && peopleLoading"
                  role="status"
                  class="robot-notice"
                >
                  正在搜索人员…
                </p>
                <p
                  v-else-if="pickerTab === 'person' && peopleError"
                  role="alert"
                  class="robot-notice"
                >
                  {{ peopleError }}
                  <button
                    type="button"
                    class="robot-text-button"
                    @click="loadPeople"
                  >
                    重试
                  </button>
                </p>
                <p
                  v-else-if="pickerTab === 'group' && groupsError"
                  role="alert"
                  class="robot-notice"
                >
                  {{ groupsError }}
                  <button
                    type="button"
                    class="robot-text-button"
                    @click="loadGroups"
                  >
                    重试
                  </button>
                </p>
                <template v-else
                  ><label
                    v-for="target in pickerTab === 'group'
                      ? filteredGroups
                      : people"
                    :key="targetKey(target)"
                    class="robot-target"
                    ><input
                      type="checkbox"
                      :checked="isSelected(target)"
                      :disabled="
                        !isSelected(target) && count >= capability.maxTargets
                      "
                      :aria-label="`${pickerTab === 'group' ? '群聊' : '人员'}：${target.name}`"
                      @change="toggleTarget(target)"
                    /><component
                      :is="pickerTab === 'group' ? Users : UserRound"
                      :size="16"
                    /><span
                      ><strong>{{ target.name }}</strong
                      ><small class="robot-muted">{{
                        pickerTab === "group"
                          ? target.sentCount
                            ? `已受理 ${target.sentCount} 次`
                            : "已登记群聊"
                          : `${(target.departments || []).map((d) => d.name).join(" / ")} · ${target.userId}`
                      }}</small></span
                    ></label
                  >
                  <p
                    v-if="
                      !(pickerTab === 'group' ? filteredGroups : people).length
                    "
                    class="robot-notice"
                  >
                    没有匹配的{{ pickerTab === "group" ? "群聊" : "人员" }}
                  </p></template
                >
                <p
                  v-if="pickerTab === 'person' && peopleTotal > 100"
                  class="robot-notice"
                >
                  显示前 100 人，请输入关键词缩小范围。
                </p>
              </div>
            </fieldset>
            <div v-if="count" class="robot-selected" aria-label="已选发送对象">
              <span
                v-for="group in selectedGroups"
                :key="`g${group.id}`"
                class="robot-chip"
                ><Users :size="13" />{{ group.name
                }}<button
                  type="button"
                  :aria-label="`移除群聊${group.name}`"
                  :disabled="submitting || !!pendingRequest"
                  @click="
                    selectedGroups = selectedGroups.filter(
                      (g) => g.id !== group.id,
                    )
                  "
                >
                  <X :size="12" /></button></span
              ><span
                v-for="person in selectedPeople"
                :key="person.userId"
                class="robot-chip"
                ><UserRound :size="13" />{{ person.name
                }}<button
                  type="button"
                  :aria-label="`移除人员${person.name}`"
                  :disabled="submitting || !!pendingRequest"
                  @click="
                    selectedPeople = selectedPeople.filter(
                      (p) => p.userId !== person.userId,
                    )
                  "
                >
                  <X :size="12" /></button
              ></span>
            </div>
            <div class="robot-content-heading">
              <label class="robot-content-label" for="robot-message-content"
                >发送内容 <span class="text-red-600">*</span></label
              >
              <button
                type="button"
                class="robot-text-button flex items-center gap-1"
                :disabled="submitting || imageProcessing || !!pendingRequest"
                @click="imageInput?.click()"
              >
                <ImagePlus :size="15" />{{
                  imageProcessing ? "正在添加…" : "添加图片"
                }}
              </button>
              <input
                ref="imageInput"
                type="file"
                accept="image/png,image/jpeg,image/gif,image/webp"
                multiple
                class="hidden"
                tabindex="-1"
                aria-label="添加消息图片"
                @change="addImages"
              />
            </div>
            <PlatformRichTextEditor
              ref="messageEditor"
              editor-id="robot-message-content"
              v-model="content"
              :show-toolbar="false"
              :disabled="submitting || imageProcessing || !!pendingRequest"
              :invalid="Boolean(draftError)"
              aria-label="发送内容"
              aria-describedby="robot-content-help"
              placeholder="输入内容，可粘贴文字、截图或图片"
              class="robot-message-editor"
            />
            <p id="robot-content-help" class="robot-muted mt-2">
              文字、图片可单独发送或混合排版；最多 6 张图片，图片合计不超过 8
              MB。
            </p>
            <p v-if="draftError" role="alert" class="robot-error mt-2">
              {{ draftError }}
            </p>
            <p v-if="error" role="alert" class="robot-error mt-3">
              {{ error }}
            </p>
            <div v-if="pendingRequest" class="robot-pending mt-3" role="status">
              <span>本次发送待确认，请先核对状态。</span
              ><button
                type="button"
                class="robot-button"
                :disabled="submitting"
                @click="recoverPending(true)"
              >
                {{ submitting ? "正在核对…" : "核对并继续本次发送" }}
              </button>
            </div>
          </div>
          <footer class="robot-dialog-footer">
            <button
              type="button"
              class="robot-button"
              :disabled="submitting"
              @click="closeCompose"
            >
              取消</button
            ><button
              type="submit"
              class="robot-button robot-primary"
              :disabled="sendDisabled"
            >
              <Send :size="14" />{{ submitting ? "正在提交…" : "发送" }}
            </button>
          </footer>
        </form>
      </section>
    </div>
  </Teleport>

  <PlatformDetailDrawer
    :open="Boolean(selectedRecord)"
    labelled-by="robot-detail-title"
    :suspended="detailPreviewOpen"
    @close="selectedRecord = null"
  >
    <template v-if="detailRecord">
      <header class="robot-detail-header">
        <div class="robot-detail-icon"><MessageSquare :size="20" /></div>
        <div class="min-w-0 flex-1">
          <h2 id="robot-detail-title">发送记录详情</h2>
          <p class="robot-muted mt-1">
            {{ formatTime(detailRecord.createdAt) }} ·
            {{ detailRecord.senderName }}
          </p>
        </div>
        <button
          type="button"
          class="robot-icon-button"
          aria-label="关闭发送记录详情"
          @click="selectedRecord = null"
        >
          <X :size="18" />
        </button>
      </header>
      <div class="robot-detail-body">
        <section class="robot-detail-section">
          <h3>发送信息</h3>
          <dl class="robot-detail-fields">
            <div v-if="detailRecord.sourceKind === 'application'">
              <dt>来源应用</dt>
              <dd>
                {{ detailRecord.senderName }}（{{ detailRecord.sourceAppId }}）
              </dd>
            </div>
            <div v-if="detailRecord.businessKey">
              <dt>业务编号</dt>
              <dd>{{ detailRecord.businessKey }}</dd>
            </div>
            <div>
              <dt>发送人</dt>
              <dd>{{ detailRecord.senderName }}</dd>
            </div>
            <div>
              <dt>发送时间</dt>
              <dd>{{ formatTime(detailRecord.createdAt) }}</dd>
            </div>
            <div>
              <dt>发送结果</dt>
              <dd class="robot-status" :data-status="detailRecord.status">
                {{ labels[detailRecord.status] }}
              </dd>
            </div>
            <div
              v-if="
                detailRecord.actorName &&
                detailRecord.actorName !== detailRecord.senderName
              "
            >
              <dt>实际操作者</dt>
              <dd>{{ detailRecord.actorName }}</dd>
            </div>
          </dl>
        </section>
        <section class="robot-detail-section">
          <h3>消息内容</h3>
          <RobotMessageContent
            class="robot-detail-content"
            :html="detailRecord.contentHtml"
            :text="detailRecord.content"
            @preview-change="detailPreviewOpen = $event"
          />
        </section>
        <section class="robot-detail-section">
          <h3>发送对象 · {{ detailRecord.recipients.length }}</h3>
          <ul class="robot-deliveries">
            <li
              v-for="recipient in detailRecord.recipients"
              :key="recipient.id"
            >
              <span
                >{{ recipient.kind === "group" ? "群聊" : "人员" }} ·
                {{ recipient.targetName }}</span
              ><span class="robot-status" :data-status="recipient.status">{{
                labels[recipient.status]
              }}</span>
              <p v-if="recipient.message" class="robot-muted">
                {{ recipient.message }}
              </p>
            </li>
          </ul>
        </section>
      </div>
      <footer class="robot-dialog-footer robot-detail-footer">
        <button
          type="button"
          class="robot-button"
          @click="selectedRecord = null"
        >
          关闭
        </button>
      </footer>
    </template>
  </PlatformDetailDrawer>
  <SettingsUnsavedChangesDialog
    :open="groupOpen && !leaveOpen"
    title="登记群聊"
    message="填写已加入机器人的群聊信息。群名称用于识别，群标识可从机器人收到的群消息事件中获取。"
    cancel-text="取消"
    cancel-tone="secondary"
    confirm-text="登记"
    confirm-tone="primary"
    :busy="groupSaving"
    :confirm-disabled="!groupName.trim() || !groupCid.trim()"
    :error="groupError"
    @cancel="closeGroup"
    @confirm="registerGroup"
    ><label class="robot-field"
      >群名称<input
        v-model="groupName"
        maxlength="128"
        :disabled="groupSaving"
        placeholder="例如：渠道销售部" /></label
    ><label class="robot-field"
      >群标识（openConversationId）<input
        v-model="groupCid"
        maxlength="256"
        :disabled="groupSaving"
        placeholder="cid…" /></label
  ></SettingsUnsavedChangesDialog>
  <SettingsUnsavedChangesDialog
    :open="leaveOpen"
    message="当前内容尚未保存或发送，确认放弃并继续？已提交的发送任务不会被取消。"
    @cancel="
      leaveOpen = false;
      leaveAction = null;
    "
    @confirm="discardAndContinue"
  />
</template>

<style scoped>
/* Values follow the application template; tokens also apply to teleported surfaces. */
.robot-page,
.robot-compose-dialog,
.robot-detail-header,
.robot-detail-body,
.robot-dialog-footer {
  color: var(--mj-body, #475569);
  font-size: 14px;
}
.robot-page h2,
.robot-compose-dialog h2 {
  color: var(--mj-text, #0f172a);
  font-size: 14px;
  font-weight: 600;
}
.robot-tabs {
  flex-shrink: 0;
  margin: -16px -16px 16px;
  padding: 8px 12px;
  background: var(--mj-surface, #fff);
  border-bottom: 1px solid var(--mj-border, #e2e8f0);
}
.robot-tabs [role="tablist"] {
  display: flex;
  justify-content: space-between;
}
.robot-tabs button,
.robot-picker-tools [role="tab"] {
  padding: 6px 12px;
  border-radius: 6px;
  color: var(--mj-muted, #64748b);
}
.robot-tabs button[aria-selected="true"] {
  background: var(--mj-text, #0f172a);
  color: white;
}
.robot-ledger {
  display: flex;
  flex: 1;
  min-height: 0;
  flex-direction: column;
  overflow: hidden;
  border: 1px solid var(--mj-border, #e2e8f0);
  border-radius: 8px;
  background: var(--mj-surface, #fff);
}
.robot-toolbar,
.robot-toolbar-title,
.robot-toolbar-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}
.robot-toolbar {
  justify-content: space-between;
  padding: 12px 16px;
  border-bottom: 1px solid var(--mj-border, #e2e8f0);
}
.robot-toolbar {
  flex-wrap: wrap;
}
.robot-toolbar-title {
  flex-wrap: wrap;
}
.robot-toolbar-actions {
  margin-left: auto;
  flex-wrap: wrap;
}
.robot-search {
  width: 260px;
}
.robot-group-filter {
  width: 190px;
}
.robot-history-scope {
  margin-left: auto;
}
.robot-search {
  display: flex;
  gap: 8px;
  align-items: center;
  border: 1px solid var(--mj-border, #e2e8f0);
  border-radius: 6px;
  padding: 6px 10px;
  color: var(--mj-muted, #64748b);
  background: white;
}
.robot-search input {
  min-width: 0;
  width: 100%;
  border: 0;
  outline: 0;
  font-size: 13px;
}
.robot-search:focus-within {
  outline: 2px solid var(--mj-primary, #2563eb);
  outline-offset: 1px;
}
.robot-button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  min-height: 32px;
  padding: 4px 12px;
  border: 1px solid var(--mj-border, #e2e8f0);
  border-radius: 6px;
  background: var(--mj-surface, #fff);
  color: var(--mj-body, #475569);
  font-size: 13px;
  white-space: nowrap;
}
.robot-button:hover {
  background: var(--mj-surface-soft, #f8fafc);
}
.robot-primary {
  background: var(--mj-primary, #2563eb);
  border-color: var(--mj-primary, #2563eb);
  color: white;
}
.robot-primary:hover {
  background: var(--mj-primary-hover, #1d4ed8);
}
.robot-text-button {
  color: var(--mj-primary, #2563eb);
  font-size: 13px;
  white-space: nowrap;
}
.robot-text-button:hover {
  text-decoration: underline;
}
button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.robot-icon-button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border-radius: 6px;
  color: var(--mj-muted, #64748b);
}
.robot-icon-button:hover {
  background: var(--mj-workspace, #f1f5f9);
}
.robot-muted {
  color: var(--mj-muted, #64748b);
  font-size: 12px;
  font-weight: 400;
}
.robot-table-scroll {
  flex: 1;
  min-height: 0;
  overflow: auto;
  scrollbar-width: none;
  cursor: grab;
}
.robot-table-scroll:active {
  cursor: grabbing;
}
.robot-table-scroll::-webkit-scrollbar {
  display: none;
}
.robot-table {
  width: 100%;
  min-width: 990px;
  table-layout: fixed;
  border-collapse: separate;
  border-spacing: 0;
  font-size: 13px;
}
.robot-col-number {
  width: 52px;
}
.robot-col-time {
  width: 174px;
}
.robot-col-sender {
  width: 120px;
}
.robot-col-targets {
  width: 190px;
}
.robot-col-status {
  width: 130px;
}
.robot-col-action {
  width: 64px;
}
.robot-table thead {
  position: sticky;
  top: 0;
  z-index: 10;
}
.robot-table th {
  background: var(--mj-surface-soft, #f8fafc);
  text-align: left;
  font-weight: 600;
  color: var(--mj-muted, #64748b);
  white-space: nowrap;
}
.robot-table :is(th, td) {
  padding: 10px 12px;
  border-right: 1px solid var(--mj-table-border, #e5edf6);
  border-bottom: 1px solid var(--mj-table-border, #e5edf6);
  vertical-align: middle;
}
.robot-table :is(th, td):last-child {
  border-right: 0;
}
.robot-table .robot-filter-row td {
  padding: 4px 8px;
  height: 40px;
  background: var(--mj-surface, #fff);
}
.robot-column-input {
  width: 100%;
  min-width: 0;
  height: 30px;
  border: 1px solid var(--mj-border, #e2e8f0);
  border-radius: 6px;
  padding: 4px 8px;
  font-size: 12px;
  color: var(--mj-body, #475569);
  background: var(--mj-surface, #fff);
}
.robot-column-input::placeholder {
  color: var(--mj-muted, #64748b);
}
.robot-column-input.is-active {
  background: var(--mj-primary-soft, #eff6ff);
  border-color: #bfdbfe;
}
.robot-filter-row :deep(.platform-search-select-trigger),
.robot-filter-row :deep(.platform-search-select-input) {
  height: 30px;
  min-height: 30px;
  font-size: 12px;
  border-radius: 6px;
}
.robot-history-row {
  cursor: pointer;
}
.robot-history-row:nth-child(even) {
  background: var(--mj-surface-soft, #f8fafc);
}
.robot-history-row:hover {
  background: var(--mj-primary-soft, #eff6ff);
}
.robot-row-number {
  text-align: center;
  color: var(--mj-muted, #64748b);
}
.robot-clamp {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  overflow-wrap: anywhere;
  line-height: 1.6;
}
.robot-message-preview {
  white-space: pre-wrap;
}
.robot-table .robot-table-empty {
  padding: 80px 16px;
  text-align: center;
  color: var(--mj-muted, #64748b);
  cursor: default;
}
.robot-table-empty svg {
  display: block;
  margin: 0 auto 12px;
}
.robot-table-empty p {
  margin-bottom: 6px;
}
.robot-pagination {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 16px;
  border-top: 1px solid var(--mj-border, #e2e8f0);
  font-size: 12px;
}
.robot-pagination > div {
  display: flex;
  align-items: center;
  gap: 12px;
}
.robot-status {
  color: var(--mj-muted, #64748b);
  font-size: 12px;
}
.robot-status[data-status="accepted"] {
  color: var(--mj-success, #047857);
}
.robot-status[data-status="failed"],
.robot-status[data-status="partial"] {
  color: var(--mj-danger, #dc2626);
}
.robot-status[data-status="unknown"] {
  color: var(--mj-warning, #b45309);
}
.robot-notice {
  padding: 16px;
  color: var(--mj-muted, #64748b);
  font-size: 13px;
}
.robot-error {
  color: var(--mj-danger, #dc2626);
  font-size: 13px;
}
.robot-pending {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  font-size: 13px;
  color: var(--mj-warning, #b45309);
}
.robot-banner {
  padding: 10px 16px;
  border-bottom: 1px solid var(--mj-border, #e2e8f0);
}
.robot-overlay {
  position: fixed;
  inset: 0;
  z-index: var(--mj-layer-dialog, 170);
  display: flex;
  align-items: center;
  justify-content: center;
  background: #0f172a66;
  padding: 24px;
}
.robot-compose-dialog {
  width: 680px;
  max-width: calc(100vw - 48px);
  max-height: calc(100dvh - 48px);
  display: flex;
  flex-direction: column;
  background: var(--mj-surface, #fff);
  border-radius: 12px;
  box-shadow: 0 20px 25px -5px #0002;
  overflow: hidden;
}
.robot-dialog-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 20px;
  border-bottom: 1px solid var(--mj-border, #e2e8f0);
  flex-shrink: 0;
}
.robot-compose-form {
  display: flex;
  flex-direction: column;
  min-height: 0;
}
.robot-dialog-body {
  overflow: auto;
  min-height: 0;
  padding: 20px;
}
.robot-field-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 8px;
  font-size: 13px;
  font-weight: 500;
  color: var(--mj-text, #0f172a);
}
.robot-recipient-picker {
  min-width: 0;
  border: 1px solid var(--mj-border, #e2e8f0);
  border-radius: 8px;
  overflow: hidden;
}
.robot-recipient-picker:disabled {
  opacity: 0.65;
}
.robot-picker-tools {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 10px;
  border-bottom: 1px solid var(--mj-border, #e2e8f0);
  background: var(--mj-surface-soft, #f8fafc);
}
.robot-picker-tools .robot-search {
  flex: 1;
}
.robot-picker-tools [role="tablist"] {
  display: flex;
  flex-shrink: 0;
}
.robot-picker-tools [role="tab"][aria-selected="true"] {
  background: var(--mj-primary-soft, #eff6ff);
  color: var(--mj-primary-hover, #1d4ed8);
}
.robot-picker-results {
  height: 164px;
  overflow: auto;
  padding: 0 10px;
}
.robot-target {
  display: flex;
  align-items: center;
  gap: 10px;
  min-height: 54px;
  padding: 8px 2px;
  border-bottom: 1px solid var(--mj-workspace, #f1f5f9);
  cursor: pointer;
}
.robot-target:hover {
  background: var(--mj-surface-soft, #f8fafc);
}
.robot-target > span {
  min-width: 0;
  overflow-wrap: anywhere;
}
.robot-target strong {
  font-size: 13px;
  font-weight: 500;
}
.robot-target small {
  display: block;
}
.robot-target input {
  width: 16px;
  height: 16px;
  accent-color: var(--mj-primary, #2563eb);
  flex-shrink: 0;
}
.robot-selected {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 10px;
  max-height: 84px;
  overflow: auto;
}
.robot-chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  border: 1px solid var(--mj-border, #e2e8f0);
  background: var(--mj-primary-soft, #eff6ff);
  color: var(--mj-primary-hover, #1d4ed8);
  font-size: 12px;
  padding: 3px 6px;
  border-radius: 4px;
}
.robot-chip button {
  display: inline-flex;
}
.robot-content-label {
  display: block;
  margin: 20px 0 8px;
  font-size: 13px;
  font-weight: 500;
  color: var(--mj-text, #0f172a);
}
.robot-content-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin: 20px 0 8px;
}
.robot-content-heading .robot-content-label {
  margin: 0;
}
.robot-message-editor :deep(.platform-rich-editor-content) {
  min-height: 150px;
  max-height: 280px;
  overflow-y: auto;
}
.robot-history-images {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 6px;
}
.robot-history-images img {
  width: 44px;
  height: 36px;
  object-fit: cover;
  border: 1px solid var(--mj-border, #e2e8f0);
  border-radius: 4px;
}
.robot-dialog-footer {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  padding: 12px 20px;
  border-top: 1px solid var(--mj-border, #e2e8f0);
  flex-shrink: 0;
  background: var(--mj-surface, #fff);
}
.robot-detail-footer {
  justify-content: center;
}
.robot-field {
  display: block;
  font-size: 13px;
  margin-top: 14px;
}
.robot-field input {
  display: block;
  width: 100%;
  margin-top: 6px;
  border: 1px solid var(--mj-border, #e2e8f0);
  border-radius: 6px;
  padding: 8px;
  font-size: 13px;
}
.robot-detail-header {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 16px 24px;
  border-bottom: 1px solid var(--mj-border, #e2e8f0);
  background: var(--mj-surface, #fff);
}
.robot-detail-header h2 {
  font-weight: 600;
  font-size: 16px;
  color: var(--mj-text, #0f172a);
}
.robot-detail-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 40px;
  height: 40px;
  border-radius: 50%;
  background: var(--mj-primary-soft, #eff6ff);
  color: var(--mj-primary, #2563eb);
}
.robot-detail-body {
  min-height: 0;
  flex: 1;
  overflow: auto;
  padding: 24px;
  background: var(--mj-workspace, #f1f5f9);
}
.robot-detail-section {
  padding: 16px;
  margin-bottom: 16px;
  border: 1px solid var(--mj-border, #e2e8f0);
  border-radius: 8px;
  background: var(--mj-surface, #fff);
}
.robot-detail-section h3 {
  border-left: 3px solid var(--mj-primary, #2563eb);
  padding-left: 8px;
  margin-bottom: 16px;
  font-weight: 600;
  color: var(--mj-text, #0f172a);
}
.robot-detail-fields {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}
.robot-detail-fields dt {
  color: var(--mj-muted, #64748b);
  font-size: 12px;
  margin-bottom: 4px;
}
.robot-detail-content {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  line-height: 1.8;
}
.robot-deliveries li {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  justify-content: space-between;
  padding: 12px 0;
  border-bottom: 1px solid var(--mj-border, #e2e8f0);
  font-size: 13px;
}
.robot-deliveries li:last-child {
  border-bottom: 0;
  padding-bottom: 0;
}
.robot-deliveries p {
  width: 100%;
}
:where(button, input, textarea):focus-visible {
  outline: 2px solid var(--mj-primary, #2563eb);
  outline-offset: 2px;
}
</style>
