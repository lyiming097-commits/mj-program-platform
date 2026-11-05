import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { existsSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
export default defineConfig(() => {
  const sdk = process.env.MJ_PLATFORM_UI_PATH || process.env.MJ_PLATFORM_LOCAL_UI || fileURLToPath(new URL('../../../packages/platform-ui/src', import.meta.url))
  if (!existsSync(sdk)) throw new Error('缺少 packages/platform-ui/src。请使用公司完整 SDK；本地验证请运行配套启动脚本。')
  return {
    base: '/form-designer/', plugins: [vue()],
    resolve: { alias: { '@platform-ui': sdk }, dedupe: ['vue', 'lucide-vue-next'] },
    server: { host: '127.0.0.1', port: 18280, strictPort: true,
      fs: { allow: ['..', sdk] },
      proxy: { '/api/form-designer': 'http://127.0.0.1:18211', '/api/auth': 'http://127.0.0.1:18210', '/auth': 'http://127.0.0.1:18210' },
    },
  }
})
