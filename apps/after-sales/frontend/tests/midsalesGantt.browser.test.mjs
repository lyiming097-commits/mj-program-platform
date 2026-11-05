import assert from "node:assert/strict";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

const frontend = createRequire(new URL("../package.json", import.meta.url));
const browserTools = createRequire(new URL("../../../../.codex-artifacts/package.json", import.meta.url));
const { chromium } = browserTools(process.env.PLAYWRIGHT_MODULE || "playwright");
const { createServer } = await import(frontend.resolve("vite"));
const root = fileURLToPath(new URL("../", import.meta.url));
const fixtureId = "/__midsales-gantt.js";
const fixture = `
import { createApp, h, ref } from 'vue';
import '/src/styles.css';
import MidsalesProjectGantt from '/src/components/MidsalesProjectGantt.vue';
import ModalShell from '/src/components/ModalShell.vue';
const scenario = new URL(location.href).searchParams.get('scenario');
const firstDay = { before: 20, within: 12, after: 3, excluded: 12, empty: 12 }[scenario];
const date = day => '2026-10-' + String(day).padStart(2, '0') + 'T00:00:00Z';
const keys = ['construction-work', 'furniture-install', 'device-install', 'device-debug', 'school-support', 'project-acceptance'];
const project = {
  currentNodeKey: scenario === 'within' ? 'furniture-install' : '',
  nodes: keys.map((nodeKey, index) => ({
    nodeKey, plannedStartAt: date(firstDay + index), plannedEndAt: date(firstDay + index + 1),
    enabled: scenario !== 'empty' && !(scenario === 'excluded' && [1, 4].includes(index)),
    status: scenario === 'after' || (scenario === 'within' && index === 0) ? 'completed'
      : scenario === 'within' && index === 1 ? 'active' : 'pending',
  })),
};
if (scenario === 'excluded') {
  for (const node of project.nodes.filter(node => !node.enabled)) {
    node.plannedStartAt = '2026-09-01T00:00:00Z';
    node.plannedEndAt = '2026-11-01T00:00:00Z';
  }
}
createApp({
  setup() {
    const open = ref(false);
    return () => [
      h(MidsalesProjectGantt, { project, compact: true, onOpen: () => { open.value = true; } }),
      h(ModalShell, { open: open.value, wide: true, title: '项目节点进度', onClose: () => { open.value = false; } },
        () => h(MidsalesProjectGantt, { project })),
    ];
  },
}).mount('#app');
`;

test("included nodes share a bounded today marker and excluded nodes do not affect the chart", { timeout: 90000 }, async () => {
  const server = await createServer({
    root, base: "/", configFile: path.join(root, "vite.config.ts"),
    cacheDir: path.resolve(root, "../../../.codex-artifacts/vite-after-sales-midsales-gantt"),
    server: { host: "127.0.0.1", port: 0 },
    plugins: [{
      name: "midsales-gantt-fixture",
      resolveId(id) { if (id === fixtureId) return id; },
      load(id) { if (id === fixtureId) return fixture; },
      configureServer(vite) {
        vite.middlewares.use((request, response, next) => {
          if (!request.url?.startsWith("/__midsales-gantt?")) return next();
          response.setHeader("Content-Type", "text/html; charset=utf-8");
          response.end(`<meta name="viewport" content="width=device-width, initial-scale=1"><div id="app"></div><script type="module" src="${fixtureId}"></script>`);
        });
      },
    }],
  });
  const errors = [];
  let browser;
  try {
    await server.listen();
    browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_PATH || undefined });
    const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, timezoneId: "Asia/Shanghai" });
    page.on("pageerror", error => errors.push(error.message));
    await page.clock.setFixedTime(new Date("2026-10-15T00:00:00Z"));
    const origin = `http://127.0.0.1:${server.httpServer.address().port}`;
    const dialog = page.getByRole("dialog", { name: "项目节点进度", exact: true });
    for (const [scenario, fraction] of [["before", 0], ["within", 0.5], ["after", 1], ["excluded", 0.5], ["empty", null]]) {
      await page.setViewportSize({ width: 1440, height: 900 });
      await page.goto(`${origin}/__midsales-gantt?scenario=${scenario}`);
      const count = scenario === "excluded" ? 4 : scenario === "empty" ? 0 : 6;
      assert.equal(await page.locator(".as-midsales-gantt__compact-track").count(), count);
      const trigger = page.getByRole("button", { name: "打开节点进度图", exact: true });
      if (scenario === "within") await trigger.press("Enter");
      else await trigger.click();
      await dialog.waitFor();
      if (scenario === "empty") {
        await dialog.getByText("本项目未包含进度节点", { exact: true }).waitFor();
        assert.equal(await dialog.locator(".as-midsales-gantt__row, .as-midsales-gantt__today").count(), 0);
        await dialog.getByRole("button", { name: "关闭", exact: true }).click();
        continue;
      }
      if (scenario === "excluded") {
        assert.deepEqual(await dialog.locator(".as-midsales-gantt__name").allTextContents(), ["工程施工", "设备安装", "设备调试", "项目验收"]);
        assert.doesNotMatch(await dialog.innerText(), /不含|家具安装|开学保障/);
      }
      for (const width of [1440, 1024, 375]) {
        await page.setViewportSize({ width, height: 900 });
        const geometry = await dialog.evaluate(el => {
          const box = selector => {
            const { left, right, top, bottom, width } = el.querySelector(selector).getBoundingClientRect();
            return { left, right, top, bottom, width };
          };
          return {
            tracks: [...el.querySelectorAll('.as-midsales-gantt__track')].map(track => {
              const { left, right, top, bottom, width } = track.getBoundingClientRect();
              return { left, right, top, bottom, width };
            }),
            line: box('.as-midsales-gantt__today'),
            label: box('.as-midsales-gantt__today span'),
            bodyOverflow: el.querySelector('.as-modal__body').scrollWidth - el.querySelector('.as-modal__body').clientWidth,
          };
        });
        const { tracks, line, label } = geometry;
        assert.equal(tracks.length, count);
        for (const track of tracks) {
          assert.ok(line.left >= track.left - 0.5 && line.right <= track.right + 0.5, `${scenario}/${width}: line stays in track`);
          assert.ok(label.left >= track.left - 0.5 && label.right <= track.right + 0.5, `${scenario}/${width}: label stays in track`);
          const expectedLeft = Math.min(track.left + fraction * track.width, track.right - line.width);
          assert.ok(Math.abs(line.left - expectedLeft) <= 0.5, `${scenario}/${width}: line follows the date scale`);
        }
        assert.ok(line.top <= tracks[0].top && line.bottom >= tracks.at(-1).bottom);
        assert.ok(geometry.bodyOverflow <= 1, `${scenario}/${width}: no horizontal overflow`);
        if (width === 1440 || (width === 375 && scenario === "within")) {
          await dialog.screenshot({ path: path.resolve(root, `../../../.codex-artifacts/after-sales-gantt-${scenario}-${width}.png`) });
        }
      }
      await dialog.getByRole("button", { name: "关闭", exact: true }).click();
      assert.equal(await dialog.count(), 0);
    }
    assert.deepEqual(errors, []);
  } finally {
    await browser?.close();
    await server.close();
  }
});
