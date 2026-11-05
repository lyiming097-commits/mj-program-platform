import { defineConfig } from "vite";
import fs from "fs";
import path from "path";
import tailwindcss from "@tailwindcss/vite";
import vue from "@vitejs/plugin-vue";

const sharedUiPath = path.resolve(__dirname, "../../../packages/platform-ui/src");
const platformUiPath = fs.existsSync(sharedUiPath) ? sharedUiPath : "/platform-ui/src";
const localNodeModulesPath = path.resolve(__dirname, "node_modules");

export default defineConfig({
  base: "/approval-center/",
  plugins: [vue(), tailwindcss()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
      "@platform-ui": platformUiPath,
      "@lucide/vue": path.resolve(localNodeModulesPath, "@lucide/vue/dist/esm/lucide-vue.mjs"),
      "vue": path.resolve(localNodeModulesPath, "vue/dist/vue.runtime.esm-bundler.js"),
    },
    dedupe: ["vue", "@lucide/vue"],
  },
  server: { host: "0.0.0.0", fs: { allow: [path.resolve(__dirname, "../../.."), "/platform-ui"] } },
});
