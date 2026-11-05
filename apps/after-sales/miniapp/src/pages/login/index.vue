<script setup lang="ts">
import { onLoad } from "@dcloudio/uni-app";
import { computed, shallowRef } from "vue";
import { readStoredSession } from "@/api/client";
import { applyProvider, fetchProviderMe, uploadAttachment } from "@/api/mobile";
import type {
  MiniSession,
  PendingUploadFile,
  WeChatLoginResult,
  WeChatRegistrationChallenge,
} from "@/api/types";
import PendingFilePicker from "@/components/PendingFilePicker.vue";
import { useServiceRegistrationForm } from "@/composables/useServiceRegistrationForm";
import { useProviderTags } from "@/composables/useProviderTags";
import {
  isManuallyLoggedOut,
  loginWithWeChat,
  registerWithWeChat,
  restoreSession,
} from "@/composables/useSession";

type LoginViewState =
  | { status: "loading" }
  | { status: "signed_out" }
  | { status: "error"; message: string }
  | { status: "registration"; challenge: WeChatRegistrationChallenge | null; initialName: string };

const view = shallowRef<LoginViewState>({ status: "loading" });
const submitting = shallowRef(false);
const formError = shallowRef("");
const qualificationFiles = shallowRef<PendingUploadFile[]>([]);
const privacyAccepted = shallowRef(false);
const PRIVACY_VERSION = "2026-09-15";
const pageError = computed(() => view.value.status === "error" ? view.value.message : "");
const {
  form,
  roleIndex,
  selectedSkills,
  roleOptions,
  validationError,
  setInitialName,
  selectRole,
  toggleSkill,
  buildProfile,
} = useServiceRegistrationForm();
const { tags: providerTags, load: loadProviderTags } = useProviderTags();
const registrationError = computed(() => formError.value || validationError.value);

function isRegistrationChallenge(result: WeChatLoginResult): result is WeChatRegistrationChallenge {
  return "registrationRequired" in result && result.registrationRequired === true;
}

function openTasks(): void {
  uni.reLaunch({ url: "/pages/tasks/index" });
}

function openPending(): void {
  uni.reLaunch({ url: "/pages/pending/index" });
}

async function continueFromSession(session: MiniSession): Promise<void> {
  const response = await fetchProviderMe();
  if (!response.item) {
    setInitialName(session.user.name);
    view.value = { status: "registration", challenge: null, initialName: session.user.name };
    return;
  }
  if (response.item.certificationStatus === "certified") openTasks();
  else openPending();
}

async function startLogin(): Promise<void> {
  view.value = { status: "loading" };
  formError.value = "";
  try {
    const result = await loginWithWeChat();
    if (isRegistrationChallenge(result)) {
      view.value = { status: "registration", challenge: result, initialName: "" };
      return;
    }
    await continueFromSession(result);
  } catch (reason) {
    view.value = {
      status: "error",
      message: reason instanceof Error ? reason.message : "微信登录失败",
    };
  }
}

async function submitRegistration(): Promise<void> {
  if (submitting.value || view.value.status !== "registration") return;
  const profile = buildProfile();
  if (!profile) return;
  if (!privacyAccepted.value) {
    formError.value = "请先阅读并同意用户协议和隐私保护指引";
    return;
  }
  submitting.value = true;
  formError.value = "";
  try {
    if (!readStoredSession()) {
      const token = view.value.challenge?.registrationToken || "";
      if (!token) throw new Error("注册凭证已失效，请重新进入小程序");
      await registerWithWeChat(
        token,
        profile.name,
        view.value.challenge?.privacyVersion || PRIVACY_VERSION,
      );
    }
    const response = await applyProvider(profile);
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
    openPending();
  } catch (reason) {
    formError.value = reason instanceof Error ? reason.message : "注册提交失败";
  } finally {
    submitting.value = false;
  }
}

function updatePrivacyConsent(event: { detail: { value: string[] } }): void {
  privacyAccepted.value = event.detail.value.includes("accepted");
  if (privacyAccepted.value && formError.value.includes("隐私")) formError.value = "";
}

onLoad(async () => {
  void loadProviderTags();
  if (isManuallyLoggedOut()) {
    view.value = { status: "signed_out" };
    return;
  }
  if (await restoreSession()) {
    const session = readStoredSession();
    if (session) {
      try {
        await continueFromSession(session);
        return;
      } catch (reason) {
        view.value = {
          status: "error",
          message: reason instanceof Error ? reason.message : "账号状态读取失败",
        };
        return;
      }
    }
  }
  await startLogin();
});
</script>

<template>
  <view class="login-page" :class="{ 'is-registration': view.status === 'registration' }">
    <view class="brand-head">
      <view class="brand-mark"><text>MJ</text></view>
      <view><text class="brand-name">迈杰现场服务</text><text class="brand-subtitle">服务人员注册</text></view>
    </view>

    <view v-if="view.status === 'loading'" class="login-loading"><view class="spinner" /><text>正在验证微信身份...</text></view>

    <view v-else-if="view.status === 'signed_out'" class="login-action">
      <text class="login-status">已退出登录</text>
      <button class="primary-button" @click="startLogin">微信登录 / 注册</button>
    </view>

    <view v-else-if="view.status === 'error'" class="login-action">
      <view class="error-banner">{{ pageError }}</view>
      <button class="secondary-button" @click="startLogin">重新登录</button>
    </view>

    <view v-else class="registration-panel">
      <view v-if="registrationError" class="error-banner">{{ registrationError }}</view>
      <view class="registration-form">
        <label class="registration-field">
          <text class="field-label">姓名 *</text>
          <input v-model="form.name" class="field-input" maxlength="128" placeholder="填写真实姓名" />
        </label>
        <label class="registration-field">
          <text class="field-label">联系电话 *</text>
          <input v-model="form.phone" class="field-input" type="number" maxlength="32" placeholder="填写常用联系电话" />
        </label>
        <label class="registration-field">
          <text class="field-label">所在城市 *</text>
          <input v-model="form.city" class="field-input" maxlength="64" placeholder="例如：杭州" />
        </label>
        <view class="registration-field">
          <text class="field-label">服务角色</text>
          <picker :range="roleOptions" range-key="label" :value="roleIndex" @change="selectRole(Number($event.detail.value))">
            <view class="field-picker">{{ roleOptions[roleIndex]?.label }}</view>
          </picker>
        </view>
        <label class="registration-field">
          <text class="field-label">服务地区</text>
          <input v-model="form.regions" class="field-input" maxlength="500" placeholder="多个地区用逗号分隔" />
        </label>
        <view class="registration-field">
          <text class="field-label">服务技能</text>
          <view v-if="providerTags.length" class="tag-options"><text v-for="tag in providerTags" :key="tag" class="tag-option" :class="{ selected: selectedSkills.includes(tag) }" @tap="toggleSkill(tag)">{{ tag }}</text></view>
          <input v-model="form.skills" class="field-input" maxlength="500" placeholder="可补充其他技能，多个用逗号分隔" />
        </view>
        <label class="registration-field">
          <text class="field-label">人员简介</text>
          <textarea v-model="form.bio" class="field-textarea" maxlength="5000" placeholder="填写项目经验或擅长领域" />
        </label>
        <view class="registration-field">
          <text class="field-label">资质附件</text>
          <PendingFilePicker :files="qualificationFiles" button-label="选择资质附件" :disabled="submitting" @update:files="qualificationFiles = $event" @error="formError = $event" />
        </view>
        <view class="consent-row">
          <checkbox-group @change="updatePrivacyConsent">
            <label class="consent-check"><checkbox value="accepted" :checked="privacyAccepted" color="#155eef" /><text>我已阅读并同意</text></label>
          </checkbox-group>
          <view class="consent-links">
            <navigator url="/pages/privacy/index?document=agreement">《用户协议》</navigator>
            <text>和</text>
            <navigator url="/pages/privacy/index?document=privacy">《隐私保护指引》</navigator>
          </view>
        </view>
        <button class="primary-button" :disabled="submitting" @click="submitRegistration">{{ submitting ? "提交中..." : "提交注册" }}</button>
      </view>
    </view>
  </view>
</template>

<style scoped>
.login-page { display: flex; min-height: 100vh; flex-direction: column; background: #fff; padding: 92rpx 46rpx 80rpx; }
.login-page.is-registration { justify-content: flex-start; }
.brand-head { display: flex; align-items: center; justify-content: center; gap: 20rpx; }
.brand-mark { display: grid; width: 76rpx; height: 76rpx; flex: 0 0 76rpx; place-items: center; border-radius: 14rpx; background: #155eef; color: #fff; }
.brand-mark text { font-size: 25rpx; font-weight: 700; }
.brand-name, .brand-subtitle { display: block; }
.brand-name { color: #182230; font-size: 34rpx; font-weight: 600; }
.brand-subtitle { margin-top: 5rpx; color: #7a8794; font-size: 23rpx; }
.login-loading { display: flex; height: 320rpx; align-items: center; justify-content: center; gap: 18rpx; color: #64748b; font-size: 25rpx; }
.spinner { width: 30rpx; height: 30rpx; border: 4rpx solid #dce6f5; border-top-color: #155eef; border-radius: 50%; animation: spin .8s linear infinite; }
.login-action { display: grid; gap: 24rpx; margin-top: 72rpx; }
.login-status { color: #526174; font-size: 25rpx; text-align: center; }
.registration-panel { margin-top: 46rpx; border-top: 1rpx solid #e8edf1; padding-top: 32rpx; }
.registration-form { display: grid; gap: 22rpx; }
.registration-field { display: block; }
.tag-options { display: flex; flex-wrap: wrap; gap: 12rpx; margin-bottom: 12rpx; }
.tag-option { display: inline-flex; min-height: 48rpx; align-items: center; border: 1rpx solid #d1dae6; border-radius: 10rpx; background: #f7f9fb; padding: 4rpx 16rpx; color: #526174; font-size: 21rpx; }
.tag-option.selected { border-color: #9bb8ed; background: #eef5ff; color: #155eef; font-weight: 700; }
.consent-row { display: flex; flex-wrap: wrap; align-items: center; gap: 6rpx 10rpx; color: #667085; font-size: 21rpx; line-height: 34rpx; }
.consent-check { display: flex; align-items: center; gap: 8rpx; }
.consent-check checkbox { transform: scale(.78); transform-origin: left center; }
.consent-links { display: flex; flex-wrap: wrap; align-items: center; gap: 2rpx; }
.consent-links navigator { color: #155eef; }
.registration-form .primary-button { margin-top: 8rpx; }
@keyframes spin { to { transform: rotate(360deg); } }
</style>
