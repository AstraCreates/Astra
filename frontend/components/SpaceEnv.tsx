"use client";

import { useEffect, useRef } from "react";
import { starPos } from "./starState";

// ─── layer config ─────────────────────────────────────────────────────────────
// Each layer: stars already exist around you, shifting at different rates as you scroll.
// Deeper = slower scroll rate = further away = smaller & dimmer.
// Closer = faster scroll = larger & brighter.
// Non-linear drift (sin waves of different freq) means no star moves in a straight line.
const LAYERS = [
  // { count, rMin, rMax, opMin, opMax, scrollRate, driftAmp, driftFreq, mouseRate }
  { n: 480, rMin: 0.18, rMax: 0.65, oMin: 0.12, oMax: 0.36, sr: 0.04,  da: 18,  df: 0.28, mr: 0.003 },
  { n: 200, rMin: 0.65, rMax: 1.20, oMin: 0.28, oMax: 0.56, sr: 0.12,  da: 48,  df: 0.45, mr: 0.012 },
  { n: 90,  rMin: 1.20, rMax: 2.00, oMin: 0.42, oMax: 0.78, sr: 0.28,  da: 90,  df: 0.70, mr: 0.040 },
  { n: 38,  rMin: 2.00, rMax: 3.20, oMin: 0.55, oMax: 0.90, sr: 0.55,  da: 150, df: 1.10, mr: 0.100 },
  { n: 14,  rMin: 3.20, rMax: 5.50, oMin: 0.65, oMax: 0.96, sr: 0.95,  da: 240, df: 1.60, mr: 0.180 },
] as const;

// ─── nebulae ─────────────────────────────────────────────────────────────────
// bx/by: base position 0–1 (y can exceed 1 — they live in the tall scroll-space)
// sr: scroll rate (how many viewport-heights they shift per full scroll)
// dr: drift rate (slow autonomous horizontal wandering)
const NEBULAE = [
  { bx: 0.20, by: 0.15, r: 0.50, c: [22, 10, 110] as RGB, a: 0.11, sr: 0.03, dr: 0.022 },
  { bx: 0.80, by: 0.42, r: 0.46, c: [65,  8, 145] as RGB, a: 0.10, sr: 0.07, dr: 0.031 },
  { bx: 0.12, by: 0.78, r: 0.44, c: [12, 35, 165] as RGB, a: 0.09, sr: 0.14, dr: 0.027 },
  { bx: 0.68, by: 1.05, r: 0.52, c: [85, 12, 125] as RGB, a: 0.12, sr: 0.09, dr: 0.040 },
  { bx: 0.35, by: 1.40, r: 0.48, c: [30,  8, 155] as RGB, a: 0.10, sr: 0.19, dr: 0.033 },
  { bx: 0.88, by: 1.72, r: 0.43, c: [75, 20, 110] as RGB, a: 0.09, sr: 0.12, dr: 0.025 },
  { bx: 0.50, by: 2.10, r: 0.55, c: [18, 45, 180] as RGB, a: 0.11, sr: 0.24, dr: 0.035 },
] as const;

type RGB = [number, number, number];

interface Star {
  bx: number; by: number;   // base position in scroll-space (by up to 3× H)
  r: number; op: number;
  li: number;               // layer index
  phase: number;            // sin drift phase (unique per star → no synchronised swaying)
  ph2: number;              // second harmonic phase
  freq: number;             // drift frequency multiplier
  r2: number; g2: number; b2: number;
}

function randColor(): RGB {
  const t = Math.random();
  if (t < 0.70) return [250, 252, 255];   // blue-white
  if (t < 0.85) return [200, 215, 255];   // cool blue
  if (t < 0.95) return [255, 248, 210];   // warm
  return [230, 200, 255];                  // faint violet
}

// ─── component ────────────────────────────────────────────────────────────────
export default function SpaceEnv() {
  const ref = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = ref.current!;
    const ctx    = canvas.getContext("2d")!;

    let W = 0, H = 0;
    let stars: Star[] = [];
    let raf   = 0;
    let scrollY = 0;
    let mx = 0.5, my = 0.5;

    // ── resize ────────────────────────────────────────────────────────────────
    function resize() {
      W = canvas.width  = window.innerWidth;
      H = canvas.height = window.innerHeight;
    }

    // ── build stars ───────────────────────────────────────────────────────────
    function init() {
      stars = [];
      LAYERS.forEach((L, li) => {
        for (let i = 0; i < L.n; i++) {
          const [r2, g2, b2] = randColor();
          stars.push({
            bx:    Math.random(),
            by:    Math.random() * 2.8,   // spread over 2.8× viewport height
            r:     L.rMin + Math.random() * (L.rMax - L.rMin),
            op:    L.oMin + Math.random() * (L.oMax - L.oMin),
            li,
            phase: Math.random() * Math.PI * 2,
            ph2:   Math.random() * Math.PI * 2,
            freq:  0.5 + Math.random() * 1.2,
            r2, g2, b2,
          });
        }
      });
    }

    // ── draw ──────────────────────────────────────────────────────────────────
    function draw(now: number) {
      ctx.fillStyle = "#030510";
      ctx.fillRect(0, 0, W, H);

      const totalH   = document.documentElement.scrollHeight;
      const maxSY    = Math.max(1, totalH - H);
      const sp       = scrollY / maxSY;    // 0–1 scroll progress

      // ── nebulae ──
      for (const neb of NEBULAE) {
        // Each nebula drifts slowly sideways (autonomous) + responds to mouse
        const wobble = Math.sin(now * 0.00004 * neb.dr + neb.bx * 6) * W * 0.05;
        const nx = neb.bx * W + wobble + (mx - 0.5) * 70;

        // Scroll: shift their Y; they live in scroll-space (by can be 0–2.5)
        // scrollRate × H is how many screen pixels they move per full scroll
        const rawY = neb.by * H - sp * H * neb.sr * 8;
        const ny   = ((rawY % (H * 3)) + H * 3) % (H * 3);
        if (ny > H + 350 || ny < -350) continue;

        const nr = neb.r * Math.min(W, H);
        const [r, g, b] = neb.c;
        const gr = ctx.createRadialGradient(nx, ny, 0, nx, ny, nr);
        gr.addColorStop(0,    `rgba(${r},${g},${b},${neb.a})`);
        gr.addColorStop(0.42, `rgba(${r},${g},${b},${neb.a * 0.35})`);
        gr.addColorStop(1,    `rgba(${r},${g},${b},0)`);
        ctx.fillStyle = gr;
        ctx.beginPath();
        ctx.arc(nx, ny, nr, 0, Math.PI * 2);
        ctx.fill();
      }

      // ── stars ──
      for (const s of stars) {
        const L = LAYERS[s.li];

        // Parallax scroll offset — different per layer, stars already exist around you
        const scrollOff = sp * H * L.sr * 8;

        // Non-linear horizontal drift: two harmonics at different frequencies
        // creates an organic figure-8 / Lissajous-like motion per star
        const t1 = now * 0.00007 * s.freq;
        const t2 = now * 0.00013 * s.freq;
        const driftX = Math.sin(t1 + s.phase)  * L.da
                     + Math.sin(t2 + s.ph2)    * L.da * 0.38;

        // Mouse parallax (deeper layers barely respond, closer layers feel immediate)
        const mox = (mx - 0.5) * 90 * (s.li + 1) * 0.14;
        const moy = (my - 0.5) * 60 * (s.li + 1) * 0.14;

        // Final screen position — Y wraps so the star field feels infinite
        const sx  = ((s.bx * W + driftX + mox) % W + W) % W;
        const rawY = s.by * H - scrollOff + moy;
        const sy  = ((rawY % (H * 3)) + H * 3) % (H * 3);

        if (sy > H + 8 || sy < -8) continue;

        // Slow per-star twinkle
        const twinkle = 0.76 + 0.24 * Math.sin(now * 0.0007 * s.freq + s.phase * 1.6);
        const alpha   = Math.min(0.98, s.op * twinkle);
        const { r2: r, g2: g, b2: b } = s;

        // Soft glow halo for brighter / larger stars
        if (s.r > 1.4 && alpha > 0.38) {
          const halo = ctx.createRadialGradient(sx, sy, 0, sx, sy, s.r * 4.5);
          halo.addColorStop(0, `rgba(${r},${g},${b},${alpha * 0.22})`);
          halo.addColorStop(1, `rgba(${r},${g},${b},0)`);
          ctx.fillStyle = halo;
          ctx.beginPath();
          ctx.arc(sx, sy, s.r * 4.5, 0, Math.PI * 2);
          ctx.fill();
        }

        ctx.fillStyle = `rgba(${r},${g},${b},${alpha})`;
        ctx.beginPath();
        ctx.arc(sx, sy, s.r, 0, Math.PI * 2);
        ctx.fill();
      }

      // ── guide star bloom: additive light in the canvas ──
      // The star guide publishes its screen px position each frame.
      // Drawing here means the bloom is composited with the actual stars — it really
      // illuminates them, not just overlaid on top.
      const bx = starPos.x, by = starPos.y;
      if (bx > -500 && bx < W + 500) {
        ctx.save();
        ctx.globalCompositeOperation = "lighter";

        const inner = ctx.createRadialGradient(bx, by, 0, bx, by, 100);
        inner.addColorStop(0,   "rgba(160, 220, 255, 0.18)");
        inner.addColorStop(0.35,"rgba(100, 160, 255, 0.07)");
        inner.addColorStop(1,   "rgba(0, 0, 0, 0)");
        ctx.fillStyle = inner;
        ctx.beginPath();
        ctx.arc(bx, by, 100, 0, Math.PI * 2);
        ctx.fill();

        const wide = ctx.createRadialGradient(bx, by, 0, bx, by, 260);
        wide.addColorStop(0, "rgba(80, 120, 255, 0.055)");
        wide.addColorStop(1, "rgba(0, 0, 0, 0)");
        ctx.fillStyle = wide;
        ctx.beginPath();
        ctx.arc(bx, by, 260, 0, Math.PI * 2);
        ctx.fill();

        ctx.restore();
      }

      raf = requestAnimationFrame(draw);
    }

    // ── events ────────────────────────────────────────────────────────────────
    const onScroll   = () => { scrollY = window.scrollY; };
    const onMouse    = (e: MouseEvent) => { mx = e.clientX / W; my = e.clientY / H; };
    const onResize   = () => { resize(); init(); };

    resize();
    init();
    window.addEventListener("scroll",    onScroll, { passive: true });
    window.addEventListener("mousemove", onMouse,  { passive: true });
    window.addEventListener("resize",    onResize);
    raf = requestAnimationFrame(draw);

    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("scroll",    onScroll);
      window.removeEventListener("mousemove", onMouse);
      window.removeEventListener("resize",    onResize);
    };
  }, []);

  return (
    <canvas
      ref={ref}
      style={{ position: "fixed", inset: 0, zIndex: 0, pointerEvents: "none", display: "block" }}
      aria-hidden="true"
    />
  );
}
