import { defineConfig, loadEnv } from "vite";
import uniModule from "@dcloudio/vite-plugin-uni";

const uni = typeof uniModule === "function"
  ? uniModule
  : (uniModule as unknown as { default: typeof uniModule }).default;

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, ".", "");
  const apiBaseUrl = String(env.VITE_API_BASE_URL || "").trim().replace(/\/+$/, "");
  const isProduction = mode === "production";
  if (isProduction && !apiBaseUrl.startsWith("https://")) {
    throw new Error("Production mini program builds require an HTTPS VITE_API_BASE_URL");
  }
  return {
    plugins: [uni()],
    define: {
      __API_BASE_URL__: JSON.stringify(apiBaseUrl || "http://localhost:8080"),
      __WECHAT_DEV_AUTH__: JSON.stringify(!isProduction && env.VITE_WECHAT_DEV_AUTH === "1"),
    },
  };
});
