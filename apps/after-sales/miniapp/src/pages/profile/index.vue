<script setup lang="ts">
import { onShow } from "@dcloudio/uni-app";
import { computed, shallowRef } from "vue";
import { ApiError, readStoredSession } from "@/api/client";
import { applyProvider, uploadAttachment } from "@/api/mobile";
import type { MobileTask, PendingUploadFile, ServiceReward } from "@/api/types";
import { usePagedRecords } from "@/composables/usePagedRecords";
import MobileAttachmentPanel from "@/components/MobileAttachmentPanel.vue";
import PendingFilePicker from "@/components/PendingFilePicker.vue";
import { taskTiming, useMobileTasks } from "@/composables/useMobileTasks";
import { useAccountDeletion } from "@/composables/useAccountDeletion";
import { useServiceRegistrationForm } from "@/composables/useServiceRegistrationForm";
import { useProviderTags } from "@/composables/useProviderTags";
import { logoutWithWeChat } from "@/composables/useSession";

const { workspace, tasks, loading, error, loadMobileTasks } = useMobileTasks();
const { form, roleIndex, selectedSkills, roleOptions, validationError, selectRole, toggleSkill, buildProfile } = useServiceRegistrationForm();
const { tags: providerTags, load: loadProviderTags } = useProviderTags();
const { deleting, deletionError, requestAccountDeletion } = useAccountDeletion();
const profileEditing = shallowRef(false);
const saving = shallowRef(false);
const qualificationFiles = shallowRef<PendingUploadFile[]>([]);
const loggingOut = shallowRef(false);
const profile = computed(() => workspace.value?.profile || null);
const { rows: rewards, total: rewardTotal, loading: rewardsLoading, error: rewardsError, hasMore: moreRewards, load: loadRewards } = usePagedRecords<ServiceReward>(() => "rewards", 5);
function serviceRecordTime(task: MobileTask): string {
  return String(
    task.assignment.completedAt
    || task.node.completedAt
    || task.node.actualEndAt
    || task.assignment.updatedAt
    || task.node.updatedAt
    || task.assignment.acceptedAt
    || task.assignment.assignedAt
    || task.node.plannedStartAt
    || "",
  );
}

const serviceRecords = computed<MobileTask[]>(() => (
  tasks.value
    .filter((task) => taskTiming(task).group === "completed")
    .slice()
    .sort((left, right) => (
      Date.parse(serviceRecordTime(right)) - Date.parse(serviceRecordTime(left))
    ))
));
const serviceAreas = computed(() => {
  const values = [...(profile.value?.regions || []), profile.value?.city || ""];
  return [...new Set(values.map((value) => value.trim()).filter(Boolean))];
});

function serviceRecordMeta(record: MobileTask): string {
  return `${record.serviceTypeLabel} · ${record.nodeName}`;
}

function dateText(value: unknown): string {
  return value ? String(value).replace("T", " ").slice(0, 10) : "";
}

function openService(record: MobileTask): void {
  uni.navigateTo({ url: `/pages/task-detail/index?id=${record.id}` });
}

function openReward(rewardId: number): void {
  uni.navigateTo({ url: `/pages/reward-detail/index?id=${rewardId}` });
}

function fillForm(): void {
  const current = profile.value;
  if (!current) return;
  form.name = current.name || "";
  form.role = current.role || "installer";
  form.phone = current.phone || "";
  form.city = current.city || "";
  form.regions = (current.regions || []).join("、");
  form.skills = (current.skills || []).join("、");
  form.bio = current.bio || "";
}

function beginEdit(): void {
  fillForm();
  qualificationFiles.value = [];
  profileEditing.value = true;
}

function cancelEdit(): void {
  profileEditing.value = false;
  qualificationFiles.value = [];
  validationError.value = "";
  fillForm();
}

async function submitProfile(): Promise<void> {
  const payload = buildProfile();
  if (!payload || saving.value) return;
  saving.value = true;
  try {
    const response = await applyProvider(payload);
    const providerId = Number(response.item?.id || 0);
    if (qualificationFiles.value.length && (!Number.isInteger(providerId) || providerId <= 0)) {
      throw new Error("服务档案记录无效");
    }
    while (qualificationFiles.value.length) {
      const file = qualificationFiles.value[0];
      if (!file) break;
      await uploadAttachment("provider_application", providerId, file.path, "qualification");
      qualificationFiles.value = qualificationFiles.value.slice(1);
    }
    if (response.item?.certificationStatus === "certified") {
      await loadMobileTasks({ force: true, silent: true });
      profileEditing.value = false;
      uni.showToast({ title: "服务档案已更新", icon: "success" });
    } else {
      uni.reLaunch({ url: "/pages/pending/index" });
    }
  } catch (reason) {
    validationError.value = reason instanceof Error ? reason.message : "服务档案提交失败";
  } finally {
    saving.value = false;
  }
}

async function load(): Promise<void> {
  if (!readStoredSession()) {
    uni.reLaunch({ url: "/pages/login/index" });
    return;
  }
  try {
    await loadMobileTasks({ force: true });
    await loadRewards(true);
  } catch (reason) {
    if (reason instanceof ApiError && reason.status === 401) uni.reLaunch({ url: "/pages/login/index" });
    else if (reason instanceof ApiError && ["SERVICE_PROVIDER_REQUIRED", "SERVICE_PROVIDER_NOT_CERTIFIED"].includes(reason.code)) {
      uni.reLaunch({ url: "/pages/pending/index" });
    }
  }
}

async function logout(): Promise<void> {
  if (loggingOut.value) return;
  loggingOut.value = true;
  try {
    await logoutWithWeChat();
    uni.reLaunch({ url: "/pages/login/index" });
  } finally {
    loggingOut.value = false;
  }
}

onShow(() => { void load(); void loadProviderTags(); });
</script>

<template>
  <view class="page-shell field-page">
    <view class="page-content field-main">
      <view v-if="error" class="error-banner">{{ error }}</view>
      <view v-if="loading && !profile" class="empty-state">正在加载档案...</view>
      <template v-else-if="profile">
        <view class="profile-overview">
          <view class="profile-identity-row">
            <view class="profile-avatar">{{ String(profile.name || "服").slice(0, 1) }}</view>
            <view class="profile-copy">
              <view class="profile-name-line">
                <text class="profile-name">{{ profile.name }}</text>
                <view class="profile-status" :class="{ 'is-certified': profile.certificationStatus === 'certified' }"><view class="profile-status-dot" /><text>{{ profile.certificationStatusLabel || "已认证" }}</text></view>
              </view>
              <text class="profile-role">{{ profile.roleLabel || profile.role || "服务人员" }}</text>
              <text class="profile-contact">{{ profile.phone || "未填写电话" }}<template v-if="profile.city"> · {{ profile.city }}</template></text>
            </view>
          </view>
          <view class="profile-stats">
            <view class="profile-stat"><text class="profile-stat-value">{{ tasks.length }}</text><text class="profile-stat-label">服务任务</text></view>
            <view class="profile-stat"><text class="profile-stat-value">{{ profile.skills?.length || 0 }}</text><text class="profile-stat-label">服务技能</text></view>
            <view class="profile-stat"><text class="profile-stat-value">{{ rewardTotal }}</text><text class="profile-stat-label">奖励记录</text></view>
          </view>
        </view>

        <view v-if="profileEditing" class="profile-section profile-form">
          <view class="section-heading"><view><text class="section-title">更新服务档案</text><text class="section-description">修改后需要管理端重新审核，请确认联系方式准确。</text></view></view>
          <view v-if="validationError" class="error-banner">{{ validationError }}</view>
          <label class="form-field"><text class="field-label">姓名 *</text><input v-model="form.name" class="field-input" /></label>
          <view class="form-field"><text class="field-label">服务角色</text><picker :range="roleOptions" range-key="label" :value="roleIndex" @change="selectRole(Number($event.detail.value))"><view class="field-picker">{{ roleOptions[roleIndex]?.label }}</view></picker></view>
          <label class="form-field"><text class="field-label">联系电话 *</text><input v-model="form.phone" class="field-input" type="number" /></label>
          <label class="form-field"><text class="field-label">所在城市 *</text><input v-model="form.city" class="field-input" /></label>
          <label class="form-field"><text class="field-label">服务地区</text><input v-model="form.regions" class="field-input" placeholder="杭州、宁波、绍兴" /></label>
          <view class="form-field"><text class="field-label">服务技能</text><view v-if="providerTags.length" class="tag-options"><text v-for="tag in providerTags" :key="tag" class="tag-option" :class="{ selected: selectedSkills.includes(tag) }" @tap="toggleSkill(tag)">{{ tag }}</text></view><input v-model="form.skills" class="field-input" placeholder="可补充其他技能，多个用逗号分隔" /></view>
          <label class="form-field"><text class="field-label">人员简介</text><textarea v-model="form.bio" class="field-textarea" /></label>
          <view class="form-field"><text class="field-label">新增资质附件</text><PendingFilePicker :files="qualificationFiles" button-label="选择资质附件" :disabled="saving" @update:files="qualificationFiles = $event" @error="validationError = $event" /></view>
          <view class="form-actions"><button class="secondary-button" @tap.stop="cancelEdit">取消</button><button class="primary-button" :disabled="saving" @tap.stop="submitProfile">{{ saving ? "提交中..." : "提交审核" }}</button></view>
        </view>

        <view v-else class="profile-section">
          <view class="section-heading"><view><text class="section-title">服务能力</text><text class="section-description">管理端派单时会参考以下地区和技能。</text></view><button class="text-action" @tap.stop="beginEdit">编辑</button></view>
          <view class="profile-facts">
            <view class="profile-fact"><text class="profile-fact-label">服务角色</text><text class="profile-fact-value">{{ profile.roleLabel || profile.role || "-" }}</text></view>
            <view class="profile-fact"><text class="profile-fact-label">主要城市</text><text class="profile-fact-value">{{ profile.city || "未设置" }}</text></view>
          </view>
          <view class="tag-list">
            <text v-for="region in serviceAreas" :key="region" class="profile-tag">{{ region }}</text>
            <text v-for="skill in (profile.skills || [])" :key="skill" class="profile-tag skill-tag">{{ skill }}</text>
            <text v-if="!serviceAreas.length && !(profile.skills || []).length" class="empty-tag">暂未设置能力与地区</text>
          </view>
          <view v-if="profile.bio" class="profile-bio"><text class="profile-fact-label">人员简介</text><text class="profile-bio-text">{{ profile.bio }}</text></view>
        </view>

        <view v-if="profile.id" class="profile-section">
          <view class="section-heading"><view><text class="section-title">资质附件</text><text class="section-description">用于服务人员认证的证明材料。</text></view></view>
          <MobileAttachmentPanel target-type="provider_application" :target-id="profile.id" category="qualification" :editable="false" empty-label="暂无资质附件" />
        </view>

        <view class="profile-section">
          <view class="section-heading"><view><text class="section-title">最近服务</text><text class="section-description">最近完成的现场服务任务。</text></view><text class="section-count">{{ serviceRecords.length }}</text></view>
          <view v-for="record in serviceRecords.slice(0, 5)" :key="String(record.id)" class="simple-row simple-row--link" role="button" :aria-label="`查看${record.projectName || '服务记录'}任务详情`" hover-class="simple-row--pressed" @tap="openService(record)">
            <view class="row-indicator row-indicator--service" />
            <view class="simple-row-copy"><text class="simple-row-title">{{ record.projectName || "服务记录" }}</text><text class="simple-row-meta">{{ serviceRecordMeta(record) }}<template v-if="dateText(serviceRecordTime(record))"> · {{ dateText(serviceRecordTime(record)) }}</template></text></view>
            <view class="simple-row-end"><text class="simple-row-status">{{ taskTiming(record).label }}</text><view class="row-arrow" /></view>
          </view>
          <view v-if="!serviceRecords.length" class="compact-empty">暂无服务记录</view>
        </view>

        <view class="profile-section">
          <view class="section-heading"><view><text class="section-title">奖励记录</text><text class="section-description">现场反馈审核通过后的奖励信息。</text></view><text class="section-count">{{ rewardTotal }}</text></view>
          <view v-for="reward in rewards" :key="reward.id" class="simple-row simple-row--link" role="button" :aria-label="`查看${reward.title || reward.prize || '服务奖励'}详情`" hover-class="simple-row--pressed" @tap="openReward(reward.id)">
            <view class="row-indicator row-indicator--reward" />
            <view class="simple-row-copy"><text class="simple-row-title">{{ reward.prize || reward.title || "服务奖励" }}</text><text class="simple-row-meta">{{ reward.projectName || "服务奖励" }}</text></view>
            <view class="simple-row-end"><text class="simple-row-status">{{ reward.statusLabel || reward.status || "-" }}</text><view class="row-arrow" /></view>
          </view>
          <view v-if="!rewards.length && !rewardsLoading && !rewardsError" class="compact-empty">暂无奖励记录</view>
          <view v-if="rewardsError" class="error-banner">{{ rewardsError }}</view>
          <button v-if="moreRewards || rewardsLoading || rewardsError" class="secondary-button" :disabled="rewardsLoading" @tap="loadRewards(!rewards.length)">{{ rewardsLoading ? '正在加载…' : rewardsError ? '重试加载' : '加载更多奖励' }}</button>
        </view>

        <view class="profile-section account-section">
          <view class="section-heading"><view><text class="section-title">账号与隐私</text><text class="section-description">查看服务条款或管理当前登录账号。</text></view></view>
          <view class="document-links">
            <navigator url="/pages/privacy/index?document=agreement"><text>用户协议</text><view class="link-arrow" /></navigator>
            <navigator url="/pages/privacy/index?document=privacy"><text>隐私保护指引</text><view class="link-arrow" /></navigator>
          </view>
          <view v-if="deletionError" class="error-banner account-error">{{ deletionError }}</view>
          <view class="account-actions"><button class="secondary-button account-button" :disabled="loggingOut" @tap.stop="logout">{{ loggingOut ? "正在退出..." : "退出登录" }}</button><button class="danger-button account-button" :disabled="deleting" @tap.stop="requestAccountDeletion">{{ deleting ? "正在注销..." : "注销服务账号" }}</button></view>
        </view>
      </template>
    </view>
  </view>
</template>

<style scoped>
.field-main { min-width: 0; padding: 0 0 36rpx; }
.profile-overview { border-bottom: 1rpx solid #dfe3e8; background: #fff; }
.profile-identity-row { display: flex; align-items: center; gap: 24rpx; padding: 38rpx 32rpx 32rpx; }
.profile-avatar { display: grid; width: 104rpx; height: 104rpx; flex: 0 0 auto; place-items: center; border-radius: 14rpx; background: #155eef; color: #fff; font-size: 38rpx; font-weight: 800; box-shadow: 0 6rpx 14rpx rgba(21, 94, 239, .18); }
.profile-copy { min-width: 0; flex: 1 1 auto; }
.profile-name-line { display: flex; min-width: 0; align-items: center; gap: 14rpx; }
.profile-name { min-width: 0; overflow: hidden; color: #111827; font-size: 34rpx; font-weight: 800; text-overflow: ellipsis; white-space: nowrap; }
.profile-status { display: flex; min-height: 40rpx; flex: 0 0 auto; align-items: center; gap: 8rpx; border: 1rpx solid #cfd8e5; border-radius: 8rpx; background: #f7f9fc; padding: 0 12rpx; color: #526174; font-size: 19rpx; font-weight: 700; }
.profile-status.is-certified { border-color: #b7decf; background: #eef9f4; color: #087550; }
.profile-status-dot { width: 10rpx; height: 10rpx; border-radius: 50%; background: currentColor; }
.profile-role, .profile-contact { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.profile-role { margin-top: 8rpx; color: #344054; font-size: 23rpx; font-weight: 700; }
.profile-contact { margin-top: 5rpx; color: #7b8798; font-size: 20rpx; }
.profile-stats { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); border-top: 1rpx solid #edf0f2; margin: 0 32rpx; }
.profile-stat { position: relative; min-height: 126rpx; padding: 22rpx 12rpx; text-align: center; }
.profile-stat + .profile-stat::before { position: absolute; top: 26rpx; bottom: 26rpx; left: 0; width: 1rpx; background: #e4e7ec; content: ""; }
.profile-stat-value, .profile-stat-label { display: block; }
.profile-stat-value { color: #182230; font-size: 34rpx; font-weight: 800; line-height: 44rpx; }
.profile-stat-label { margin-top: 5rpx; color: #667085; font-size: 20rpx; }
.profile-section { border-top: 1rpx solid #dfe3e8; border-bottom: 1rpx solid #dfe3e8; background: #fff; margin-top: 22rpx; padding: 30rpx 32rpx; }
.section-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 24rpx; margin-bottom: 22rpx; }
.section-heading > view { min-width: 0; }
.section-title, .section-description { display: block; }
.section-title { color: #182230; font-size: 29rpx; font-weight: 800; line-height: 40rpx; }
.section-description { margin-top: 5rpx; color: #7b8798; font-size: 20rpx; line-height: 32rpx; }
.section-count { display: grid; min-width: 38rpx; height: 38rpx; flex: 0 0 auto; place-items: center; border-radius: 19rpx; background: #edf2f8; padding: 0 9rpx; color: #526174; font-size: 19rpx; font-weight: 800; }
.text-action { min-width: 92rpx; min-height: 58rpx; flex: 0 0 auto; margin: 0; border: 1rpx solid #bfd2f7; border-radius: 9rpx; background: #edf4ff; padding: 0 18rpx; color: #155eef; font-size: 21rpx; font-weight: 700; line-height: 56rpx; }
.profile-facts { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); border-top: 1rpx solid #edf0f2; border-bottom: 1rpx solid #edf0f2; margin-bottom: 20rpx; }
.profile-fact { min-width: 0; padding: 18rpx 0; }
.profile-fact + .profile-fact { border-left: 1rpx solid #edf0f2; padding-left: 24rpx; }
.profile-fact-label, .profile-fact-value { display: block; }
.profile-fact-label { color: #8a96a7; font-size: 19rpx; }
.profile-fact-value { overflow: hidden; margin-top: 6rpx; color: #344054; font-size: 23rpx; font-weight: 700; text-overflow: ellipsis; white-space: nowrap; }
.tag-list { display: flex; flex-wrap: wrap; gap: 12rpx; }
.profile-tag, .empty-tag { display: inline-flex; min-height: 48rpx; align-items: center; border: 1rpx solid #d1dae6; border-radius: 8rpx; background: #f7f9fb; padding: 4rpx 16rpx; color: #526174; font-size: 20rpx; }
.profile-tag.skill-tag { border-color: #bed0ef; background: #f0f5ff; color: #315f9f; }
.empty-tag { border-style: dashed; color: #8a96a7; }
.profile-bio { border-top: 1rpx solid #edf0f2; margin-top: 22rpx; padding-top: 20rpx; }
.profile-bio-text { display: block; margin-top: 8rpx; color: #526174; font-size: 22rpx; line-height: 36rpx; }
.simple-row { display: grid; min-height: 96rpx; grid-template-columns: 10rpx minmax(0, 1fr) auto; align-items: center; gap: 18rpx; border-bottom: 1rpx solid #edf0f2; }
.simple-row:last-child { border-bottom: 0; }
.simple-row--link { margin: 0 -12rpx; padding: 0 12rpx; }
.simple-row--pressed { background: #f5f7fa; }
.row-indicator { width: 8rpx; height: 38rpx; border-radius: 4rpx; background: #7b9bc8; }
.row-indicator--reward { background: #c39a39; }
.simple-row-copy { min-width: 0; }
.simple-row-title, .simple-row-meta { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.simple-row-title { color: #344054; font-size: 23rpx; font-weight: 700; }
.simple-row-meta { margin-top: 5rpx; color: #98a2b3; font-size: 18rpx; }
.simple-row-end { display: flex; min-width: 0; align-items: center; gap: 15rpx; }
.simple-row-status { max-width: 210rpx; overflow: hidden; color: #667085; font-size: 19rpx; text-overflow: ellipsis; white-space: nowrap; }
.row-arrow { width: 14rpx; height: 14rpx; flex: 0 0 auto; border-top: 3rpx solid #a5adba; border-right: 3rpx solid #a5adba; margin-right: 5rpx; transform: rotate(45deg); }
.compact-empty { display: grid; min-height: 120rpx; place-items: center; color: #8490a2; font-size: 22rpx; }
.profile-form { display: grid; gap: 24rpx; }
.profile-form .section-heading { margin-bottom: 0; }
.form-field { display: block; }
.tag-options { display: flex; flex-wrap: wrap; gap: 12rpx; margin-bottom: 12rpx; }
.tag-option { display: inline-flex; min-height: 48rpx; align-items: center; border: 1rpx solid #d1dae6; border-radius: 10rpx; background: #f7f9fb; padding: 4rpx 16rpx; color: #526174; font-size: 21rpx; }
.tag-option.selected { border-color: #9bb8ed; background: #eef5ff; color: #155eef; font-weight: 700; }
.form-actions { display: grid; grid-template-columns: 180rpx minmax(0, 1fr); gap: 16rpx; border-top: 1rpx solid #edf0f2; padding-top: 24rpx; }
.account-section { margin-bottom: 24rpx; }
.document-links { border-top: 1rpx solid #edf0f2; }
.document-links navigator { display: flex; min-height: 82rpx; align-items: center; justify-content: space-between; border-bottom: 1rpx solid #edf0f2; color: #344054; font-size: 23rpx; font-weight: 700; }
.link-arrow { width: 15rpx; height: 15rpx; border-top: 3rpx solid #98a2b3; border-right: 3rpx solid #98a2b3; margin-right: 5rpx; transform: rotate(45deg); }
.account-error { margin-top: 20rpx; margin-bottom: 0; }
.account-actions { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14rpx; margin-top: 24rpx; }
.account-button { width: 100%; margin: 0; padding: 0 14rpx; font-size: 22rpx; }
@media (max-width: 360px) {
  .profile-name-line { align-items: flex-start; flex-direction: column; gap: 8rpx; }
  .profile-status { min-height: 34rpx; }
  .profile-avatar { width: 92rpx; height: 92rpx; }
  .account-actions { grid-template-columns: 1fr; }
}
</style>
