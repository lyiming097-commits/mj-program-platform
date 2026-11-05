<script setup>
import { onBeforeUnmount, onMounted, ref } from "vue";

const canvasRef = ref(null);
const triStateMap = new Map();

const points = Array.from({ length: 14 }, () => ({
  x: Math.random() * 1200,
  y: Math.random() * 800,
  vx: (Math.random() - 0.5) * 0.5,
  vy: (Math.random() - 0.5) * 0.5,
  baseSpeed: 0.12 + Math.random() * 0.25,
  phase: Math.random() * Math.PI * 2,
  freq: 0.2 + Math.random() * 0.4,
}));

let frame = 0;
let resizeHandler = null;

onMounted(() => {
  const canvas = canvasRef.value;
  if (!canvas) {
    return;
  }
  const ctx = canvas.getContext("2d");
  if (!ctx) {
    return;
  }

  let t = 0;
  const stateMap = triStateMap;

  const resize = () => {
    const dpr = window.devicePixelRatio || 1;
    canvas.width = window.innerWidth * dpr;
    canvas.height = window.innerHeight * dpr;
    canvas.style.width = `${window.innerWidth}px`;
    canvas.style.height = `${window.innerHeight}px`;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  };
  resize();
  resizeHandler = resize;
  window.addEventListener("resize", resize);

  const W = () => window.innerWidth;
  const H = () => window.innerHeight;

  function triangulate(pts) {
    const triangles = [];
    const n = pts.length;
    if (n < 3) {
      return triangles;
    }
    for (let i = 0; i < n; i++) {
      const dists = [];
      for (let j = 0; j < n; j++) {
        if (i === j) continue;
        const dx = pts[i].x - pts[j].x;
        const dy = pts[i].y - pts[j].y;
        dists.push({ idx: j, d: Math.sqrt(dx * dx + dy * dy) });
      }
      dists.sort((a, b) => a.d - b.d);
      const neighbors = dists.slice(0, 3);
      for (let a = 0; a < neighbors.length; a++) {
        for (let b = a + 1; b < neighbors.length; b++) {
          const idxA = neighbors[a].idx;
          const idxB = neighbors[b].idx;
          const tri = [i, idxA, idxB].sort((x, y) => x - y);
          if (!triangles.some((tt) => tt[0] === tri[0] && tt[1] === tri[1] && tt[2] === tri[2])) {
            const d1 = Math.hypot(pts[tri[0]].x - pts[tri[1]].x, pts[tri[0]].y - pts[tri[1]].y);
            const d2 = Math.hypot(pts[tri[1]].x - pts[tri[2]].x, pts[tri[1]].y - pts[tri[2]].y);
            const d3 = Math.hypot(pts[tri[0]].x - pts[tri[2]].x, pts[tri[0]].y - pts[tri[2]].y);
            const maxEdge = Math.max(W(), H()) * 0.45;
            if (d1 < maxEdge && d2 < maxEdge && d3 < maxEdge) {
              triangles.push(tri);
            }
          }
        }
      }
    }
    return triangles;
  }

  const animate = () => {
    t += 0.016;
    const w = W();
    const h = H();
    ctx.clearRect(0, 0, w, h);

    for (const p of points) {
      p.x += p.vx + Math.sin(t * p.freq + p.phase) * p.baseSpeed * 0.5;
      p.y += p.vy + Math.cos(t * p.freq * 0.8 + p.phase) * p.baseSpeed * 0.5;
      const margin = 60;
      if (p.x < -margin) {
        p.x = -margin;
        p.vx = Math.abs(p.vx);
      }
      if (p.x > w + margin) {
        p.x = w + margin;
        p.vx = -Math.abs(p.vx);
      }
      if (p.y < -margin) {
        p.y = -margin;
        p.vy = Math.abs(p.vy);
      }
      if (p.y > h + margin) {
        p.y = h + margin;
        p.vy = -Math.abs(p.vy);
      }
      p.vx += (Math.random() - 0.5) * 0.01;
      p.vy += (Math.random() - 0.5) * 0.01;
      const speed = Math.sqrt(p.vx * p.vx + p.vy * p.vy);
      if (speed > 0.8) {
        p.vx *= 0.8 / speed;
        p.vy *= 0.8 / speed;
      }
    }

    const tris = triangulate(points);
    const activeKeys = new Set();
    const brightTargets = new Map();
    const brightUsedVerts = new Set();

    const trisWithKeys = tris.map(([a, b, c]) => {
      const key = `${a}-${b}-${c}`;
      const currentBright = stateMap.get(key)?.bright ?? 0;
      return { a, b, c, key, currentBright };
    });
    trisWithKeys.sort((x, y) => y.currentBright - x.currentBright);

    for (const { a, b, c, key } of trisWithKeys) {
      activeKeys.add(key);

      const pa = points[a];
      const pb = points[b];
      const pc = points[c];
      const cx = (pa.x + pb.x + pc.x) / 3;
      const cy = (pa.y + pb.y + pc.y) / 3;
      const brightness = Math.sin(t * 0.5 + cx * 0.005 + cy * 0.003) * 0.5 + 0.5;
      const wantsBright = brightness > 0.55;

      if (wantsBright && !brightUsedVerts.has(a) && !brightUsedVerts.has(b) && !brightUsedVerts.has(c)) {
        brightTargets.set(key, true);
        brightUsedVerts.add(a);
        brightUsedVerts.add(b);
        brightUsedVerts.add(c);
      } else {
        brightTargets.set(key, false);
      }
    }

    const fadeInSpeed = 0.016;
    const fadeOutSpeed = 0.016;
    const brightLerp = 0.015;

    for (const [a, b, c] of tris) {
      const key = `${a}-${b}-${c}`;
      const pa = points[a];
      const pb = points[b];
      const pc = points[c];
      const cross = (pb.x - pa.x) * (pc.y - pa.y) - (pb.y - pa.y) * (pc.x - pa.x);
      const normalFactor = Math.min(Math.abs(cross) / 40000, 1);

      let state = stateMap.get(key);
      if (!state) {
        state = { fade: 0, bright: 0, verts: [a, b, c] };
        stateMap.set(key, state);
      }
      state.verts = [a, b, c];
      state.fade = Math.min(1, state.fade + fadeInSpeed);

      const brightTarget = brightTargets.get(key) ? 1 : 0;
      state.bright += (brightTarget - state.bright) * brightLerp;

      ctx.beginPath();
      ctx.moveTo(pa.x, pa.y);
      ctx.lineTo(pb.x, pb.y);
      ctx.lineTo(pc.x, pc.y);
      ctx.closePath();

      const bVal = state.bright;
      const fVal = state.fade;
      const brightAlpha = (0.015 + normalFactor * 0.03) * bVal * fVal;
      const darkAlpha = (0.005 + normalFactor * 0.012) * (1 - bVal) * fVal;

      if (darkAlpha > 0.0005) {
        ctx.fillStyle = `rgba(15,23,42,${Math.min(darkAlpha, 0.025)})`;
        ctx.fill();
      }
      if (brightAlpha > 0.0005) {
        ctx.fillStyle = `rgba(56,189,248,${Math.min(brightAlpha, 0.045)})`;
        ctx.fill();
      }
    }

    for (const [key, state] of stateMap) {
      if (!activeKeys.has(key)) {
        state.fade = Math.max(0, state.fade - fadeOutSpeed);
        state.bright *= 1 - brightLerp;
        if (state.fade < 0.001) {
          stateMap.delete(key);
          continue;
        }
        const verts = state.verts;
        if (!verts) {
          stateMap.delete(key);
          continue;
        }
        const [va, vb, vc] = verts;
        if (va < points.length && vb < points.length && vc < points.length) {
          const pa = points[va];
          const pb = points[vb];
          const pc = points[vc];
          const cross = (pb.x - pa.x) * (pc.y - pa.y) - (pb.y - pa.y) * (pc.x - pa.x);
          const normalFactor = Math.min(Math.abs(cross) / 40000, 1);
          const bVal = state.bright;
          const fVal = state.fade;

          ctx.beginPath();
          ctx.moveTo(pa.x, pa.y);
          ctx.lineTo(pb.x, pb.y);
          ctx.lineTo(pc.x, pc.y);
          ctx.closePath();

          const brightAlpha = (0.015 + normalFactor * 0.03) * bVal * fVal;
          const darkAlpha = (0.005 + normalFactor * 0.012) * (1 - bVal) * fVal;
          if (darkAlpha > 0.0005) {
            ctx.fillStyle = `rgba(15,23,42,${Math.min(darkAlpha, 0.025)})`;
            ctx.fill();
          }
          if (brightAlpha > 0.0005) {
            ctx.fillStyle = `rgba(56,189,248,${Math.min(brightAlpha, 0.045)})`;
            ctx.fill();
          }
        }
      }
    }

    const drawnEdges = new Set();
    for (const [a, b, c] of tris) {
      const edges = [
        [a, b],
        [b, c],
        [a, c],
      ];
      for (const [i, j] of edges) {
        const key = `${Math.min(i, j)}-${Math.max(i, j)}`;
        if (drawnEdges.has(key)) continue;
        drawnEdges.add(key);
        const pi = points[i];
        const pj = points[j];
        const mx = (pi.x + pj.x) / 2;
        const my = (pi.y + pj.y) / 2;
        const edgeBrightness = Math.sin(t * 0.7 + mx * 0.004 + my * 0.006) * 0.5 + 0.5;
        const dist = Math.hypot(pi.x - pj.x, pi.y - pj.y);
        const distFade = Math.max(0, 1 - dist / (Math.max(w, h) * 0.3));
        const alpha = (0.04 + edgeBrightness * 0.08) * distFade * Math.min(t * 0.5, 1);

        ctx.beginPath();
        ctx.moveTo(pi.x, pi.y);
        ctx.lineTo(pj.x, pj.y);
        ctx.strokeStyle = edgeBrightness > 0.5 ? `rgba(56,189,248,${alpha})` : `rgba(99,102,241,${alpha * 0.7})`;
        ctx.lineWidth = 0.4 + edgeBrightness * 0.3;
        ctx.stroke();
      }
    }

    for (const p of points) {
      const glow = Math.sin(t * 0.8 + p.phase) * 0.5 + 0.5;
      const globalFade = Math.min(t * 0.5, 1);
      const radius = 1 + glow * 1.5;
      const alpha = (0.08 + glow * 0.15) * globalFade;
      ctx.beginPath();
      ctx.arc(p.x, p.y, radius, 0, Math.PI * 2);
      ctx.fillStyle = `rgba(56,189,248,${alpha})`;
      ctx.fill();

      if (glow > 0.7) {
        const grad = ctx.createRadialGradient(p.x, p.y, 0, p.x, p.y, 8);
        grad.addColorStop(0, `rgba(56,189,248,${(glow - 0.7) * 0.12 * globalFade})`);
        grad.addColorStop(1, "rgba(56,189,248,0)");
        ctx.beginPath();
        ctx.arc(p.x, p.y, 8, 0, Math.PI * 2);
        ctx.fillStyle = grad;
        ctx.fill();
      }
    }

    frame = requestAnimationFrame(animate);
  };

  frame = requestAnimationFrame(animate);
});

onBeforeUnmount(() => {
  cancelAnimationFrame(frame);
  if (resizeHandler) {
    window.removeEventListener("resize", resizeHandler);
    resizeHandler = null;
  }
});
</script>

<template>
  <canvas ref="canvasRef" class="absolute inset-0 pointer-events-none" style="opacity: 0.7" />
</template>
