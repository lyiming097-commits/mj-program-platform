declare module '@platform-ui' {
  import type { DefineComponent } from 'vue'
  export const PlatformTopBar: DefineComponent<any, any, any>
  export const PlatformSidebar: DefineComponent<any, any, any>
  export const PlatformDetailDrawer: DefineComponent<any, any, any>
  export function createPlatformSessionStore(options: any): any
  export function createPlatformApiClient(options: any): any
  export function loginSessionIdentityKey(session: any): string
  export function startSessionKeepAlive(options: any): () => void
}
declare module '@platform-ui/backdrop-dismiss.js' { export const backdropDismiss: any }
