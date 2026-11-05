<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue';
import { LogOut } from '@lucide/vue';
import { API_BASE_URL } from '@/config';
import CableMallWorkspace from './CableMallWorkspace_web.vue';
import './ExternalCableMallApp.css';

const SESSION_KEY = 'cable_mall_external_session';

const session = ref(loadSession());
const busy = ref(false);
const error = ref('');
const accountMenuOpen = ref(false);
const accountMenuRef = ref(null);
const loginForm = reactive({ username: '', password: '' });

const isLoggedIn = computed(() => Boolean(session.value?.token));
const account = computed(() => session.value?.account || {});
const accountDisplayName = computed(() => account.value.display_name || account.value.username || '外部用户');
const accountLabel = computed(() => account.value.username || '线材商城账号');
const accountAvatarInitial = computed(() => accountDisplayName.value.slice(0, 1) || '线');

function loadSession() {
  try {
    return JSON.parse(window.localStorage.getItem(SESSION_KEY) || 'null');
  } catch {
    return null;
  }
}

function saveSession(payload) {
  session.value = payload;
  window.localStorage.setItem(SESSION_KEY, JSON.stringify(payload));
}

function clearSession(message = '') {
  session.value = null;
  accountMenuOpen.value = false;
  window.localStorage.removeItem(SESSION_KEY);
  if (typeof message === 'string' && message) error.value = message;
}

function handleExternalLogout(message = '') {
  clearSession(message);
}

function toggleAccountMenu() {
  accountMenuOpen.value = !accountMenuOpen.value;
}

function closeAccountMenu() {
  accountMenuOpen.value = false;
}

function handleDocumentClick(event) {
  if (!accountMenuRef.value?.contains(event.target)) {
    closeAccountMenu();
  }
}

async function login() {
  if (!loginForm.username.trim() || !loginForm.password) {
    error.value = '请输入账号和密码';
    return;
  }
  busy.value = true;
  error.value = '';
  try {
    const response = await fetch(new URL('/api/external-cable-mall/login/', API_BASE_URL).toString(), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        username: loginForm.username.trim(),
        password: loginForm.password,
      }),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data?.error || data?.message || '登录失败');
    loginForm.password = '';
    saveSession(data);
  } catch (err) {
    error.value = err.message || String(err);
  } finally {
    busy.value = false;
  }
}

onMounted(() => {
  document.addEventListener('click', handleDocumentClick);
});

onBeforeUnmount(() => {
  document.removeEventListener('click', handleDocumentClick);
});
</script>

<template>
  <div v-if="isLoggedIn" class="external-app-frame">
    <header class="external-global-header">
      <div class="external-header-brand">
        <h1>迈杰教育科技</h1>
      </div>
      <div ref="accountMenuRef" class="external-account-menu-wrap" @click.stop>
        <button class="external-header-account" type="button" aria-label="当前登录账号" @click="toggleAccountMenu">
          <div class="external-account-text">
            <strong>{{ accountDisplayName }}</strong>
            <span>{{ accountLabel }}</span>
          </div>
          <div class="external-account-avatar">{{ accountAvatarInitial }}</div>
        </button>
        <div v-if="accountMenuOpen" class="external-account-menu">
          <div class="external-account-card">
            <div class="external-account-card-avatar">{{ accountAvatarInitial }}</div>
            <div>
              <strong>{{ accountDisplayName }}</strong>
              <span>{{ accountLabel }}</span>
            </div>
          </div>
	          <button class="external-account-menu-action danger" type="button" @click="clearSession()">
            <LogOut :size="16" />
            <span>退出登录</span>
          </button>
        </div>
      </div>
    </header>
	    <CableMallWorkspace
	      external-mode
	      :external-session="session"
	      @external-logout="handleExternalLogout"
	    />
  </div>
  <main v-else class="external-login-shell">
    <section class="external-login-card">
      <div>
        <h1>线材商城</h1>
        <p>使用业务人员提供的账号登录。</p>
      </div>
      <form @submit.prevent="login">
        <label>
          <span>登录账号</span>
          <input v-model="loginForm.username" autocomplete="username" placeholder="请输入账号" />
        </label>
        <label>
          <span>登录密码</span>
          <input v-model="loginForm.password" autocomplete="current-password" type="password" placeholder="请输入密码" />
        </label>
        <div v-if="error" class="external-login-error">{{ error }}</div>
        <button type="submit" :disabled="busy">{{ busy ? '登录中...' : '登录商城' }}</button>
      </form>
    </section>
  </main>
</template>
