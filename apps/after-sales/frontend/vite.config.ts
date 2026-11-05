import { defineConfig } from "vite";
import fs from "fs";
import path from "path";
import tailwindcss from "@tailwindcss/vite";
import vue from "@vitejs/plugin-vue";

const sharedUiPath = path.resolve(__dirname, "../../../packages/platform-ui/src");
const platformUiPath = fs.existsSync(sharedUiPath) ? sharedUiPath : "/platform-ui/src";
const localNodeModulesPath = path.resolve(__dirname, "node_modules");

export default defineConfig({
  base: "/after-sales/",
  plugins: [vue(), tailwindcss()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
      "@platform-ui": platformUiPath,
      "@lucide/vue": path.resolve(localNodeModulesPath, "@lucide/vue/dist/esm/lucide-vue.mjs"),
      "lucide-vue-next": path.resolve(
        localNodeModulesPath,
        "lucide-vue-next/dist/esm/lucide-vue-next.js",
      ),
      "vue": path.resolve(localNodeModulesPath, "vue/dist/vue.runtime.esm-bundler.js"),
    },
    dedupe: ["vue", "@lucide/vue", "lucide-vue-next"],
  },
  server: { host: "0.0.0.0", fs: { allow: [path.resolve(__dirname, "../../.."), "/platform-ui"] } },
});
