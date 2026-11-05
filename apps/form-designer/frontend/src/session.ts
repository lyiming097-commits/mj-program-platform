import { createPlatformSessionStore, createPlatformApiClient, loginSessionIdentityKey, startSessionKeepAlive } from '@platform-ui'
import { API_BASE_URL } from './config'
const store = createPlatformSessionStore({ apiBaseUrl: API_BASE_URL, additionalAllowedKeys: ['canManageApp', 'canDesign'] })
export const { apiFetchRaw } = createPlatformApiClient({ apiBaseUrl: API_BASE_URL, sessionStore: store })
export const { logoutLoginSession, loadLoginSession } = store
let stop: (() => void) | undefined
let identity = ''
const changed = (event: Event) => {
  const next = (event as CustomEvent).detail?.session ?? store.loadLoginSession()
  if (identity && loginSessionIdentityKey(next) !== identity) window.location.reload()
}
export function loginUrl() { return `/auth/?redirect=${encodeURIComponent(window.location.pathname + window.location.search)}` }
export async function initializeSession() {
  const validated = await store.validateLoginSession(store.loadLoginSession())
  store.saveLoginSession(validated)
  identity = loginSessionIdentityKey(validated)
  window.addEventListener(store.LOGIN_SESSION_CHANGE_EVENT, changed)
  stop = startSessionKeepAlive({ shouldRun: () => Boolean(store.loadLoginSession()), validate: () => store.validateLoginSession(store.loadLoginSession()), onValidated: (next: unknown) => store.saveLoginSession(next, { broadcast: false }) })
}
export function disposeSession() { stop?.(); window.removeEventListener(store.LOGIN_SESSION_CHANGE_EVENT, changed) }
