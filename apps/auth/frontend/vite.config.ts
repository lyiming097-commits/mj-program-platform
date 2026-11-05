import { defineConfig } from "vite";
import fs from "fs";
import path from "path";
import tailwindcss from "@tailwindcss/vite";
import vue from "@vitejs/plugin-vue";

const sharedUiPath = path.resolve(__dirname, "../../../packages/platform-ui/src");
const dockerSharedUiPath = "/platform-ui/src";
const platformUiPath = fs.existsSync(sharedUiPath) ? sharedUiPath : dockerSharedUiPath;
const localNodeModulesPath = path.resolve(__dirname, "node_modules");

export default defineConfig({
  base: "/auth/",
  plugins: [vue(), tailwindcss()],
  build: {
    rollupOptions: {
      input: path.resolve(__dirname, "index.html"),
    },
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
      "@platform-ui": platformUiPath,
      "@lucide/vue": path.resolve(localNodeModulesPath, "@lucide/vue/dist/esm/lucide-vue.mjs"),
      "vue": path.resolve(localNodeModulesPath, "vue/dist/vue.runtime.esm-bundler.js"),
    },
    dedupe: ["vue", "@lucide/vue"],
  },
  assetsInclude: ["**/*.svg", "**/*.csv"],
  server: {
    host: "0.0.0.0",
    port: 5610,
    strictPort: true,
    hmr: false,
    watch: {
      ignored: ["**/dist/**", "**/*.log"],
    },
    fs: {
      allow: [path.resolve(__dirname, "../../.."), "/platform-ui"],
    },
  },
});
