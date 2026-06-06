"use client";
import { useEffect, useRef } from "react";

type Theme = "dark" | "light";
type Star = {
  x: number;
  y: number;
  z: number;
  r: number;
  baseA: number;
  tw: number;
  twSpeed: number;
  hueShift: boolean;
  cross: boolean;
};
type ShootingStar = { x: number; y: number; vx: number; vy: number; life: number; maxLife: number };

export default function StarField() {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d")!;
    if (!ctx) return;

    let w = 0, h = 0;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    let _seed = 0x9e3779b1;
    const srand = () => { _seed = (Math.imul(_seed, 1664525) + 1013904223) >>> 0; return _seed / 0xffffffff; };
    const resetSeed = () => { _seed = 0x9e3779b1; };

    let stars: Star[] = [];
    const shootingStars: ShootingStar[] = [];
    let rafId: number;
    let theme: Theme = document.documentElement.getAttribute("data-theme") === "light" ? "light" : "dark";

    function currentPalette() {
      return theme === "dark"
        ? {
          count: 0,
          radiusMin: 0.42,
          radiusMax: 1.9,
          alphaMin: 0.22,
          alphaMax: 0.94,
          drift: 0.05,
          cool: "214,226,255",
          warm: "255,221,170",
          glowCool: "112,144,255",
          glowWarm: "255,190,126",
          crossChance: 0.34,
          shootingChance: 0,
          canvasOpacity: 1,
        }
        : {
          count: 80,
          radiusMin: 0.24,
          radiusMax: 0.78,
          alphaMin: 0.035,
          alphaMax: 0.18,
          drift: 0.012,
          cool: "44,82,180",
          warm: "92,112,160",
          glowCool: "11,49,255",
          glowWarm: "92,112,160",
          crossChance: 0.06,
          shootingChance: reduceMotion ? 0 : 0.00018,
          canvasOpacity: 0.34,
        };
    }

    function buildStars() {
      resetSeed();
      const palette = currentPalette();
      const density = Math.min(1.2, Math.max(0.6, (w * h) / (1440 * 900)));
      const n = Math.floor(palette.count * density);
      stars = [];
      for (let i = 0; i < n; i++) {
        stars.push({
          x: srand() * w, y: srand() * h, z: srand(),
          r: palette.radiusMin + srand() * palette.radiusMax,
          baseA: palette.alphaMin + srand() * palette.alphaMax,
          tw: srand() * Math.PI * 2,
          twSpeed: theme === "dark" ? 1.15 + srand() * 2.45 : 0.08 + srand() * 0.22,
          hueShift: srand() < (theme === "dark" ? 0.16 : 0.08),
          cross: srand() < palette.crossChance,
        });
      }
    }

    function resize() {
      if (!canvas || !ctx) return;
      w = window.innerWidth;
      h = window.innerHeight;
      canvas.width = w * dpr;
      canvas.height = h * dpr;
      canvas.style.width = w + "px";
      canvas.style.height = h + "px";
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      buildStars();
    }

    function spawnShootingStar() {
      if (theme === "dark") return;
      const palette = currentPalette();
      if (Math.random() > palette.shootingChance) return;
      shootingStars.push({
        x: Math.random() * w * 0.7 + w * 0.15,
        y: Math.random() < 0.5 ? -20 : Math.random() * h * 0.3,
        vx: 1.2 + Math.random() * 0.8,
        vy: 0.24 + Math.random() * 0.35,
        life: 0,
        maxLife: 110 + Math.random() * 50,
      });
    }

    function drawCross(x: number, y: number, r: number, a: number, rgb: string) {
      const arm = theme === "dark" ? r * 7.2 : r * 3.2;
      ctx.strokeStyle = `rgba(${rgb},${a})`;
      ctx.lineWidth = theme === "dark" ? 0.9 : 0.38;
      ctx.beginPath();
      ctx.moveTo(x - arm, y);
      ctx.lineTo(x + arm, y);
      ctx.moveTo(x, y - arm);
      ctx.lineTo(x, y + arm);
      ctx.stroke();
      if (theme === "dark") {
        ctx.strokeStyle = `rgba(255,255,255,${a * 0.44})`;
        ctx.lineWidth = 0.45;
        ctx.beginPath();
        ctx.moveTo(x - arm * 0.48, y - arm * 0.48);
        ctx.lineTo(x + arm * 0.48, y + arm * 0.48);
        ctx.moveTo(x + arm * 0.48, y - arm * 0.48);
        ctx.lineTo(x - arm * 0.48, y + arm * 0.48);
        ctx.stroke();
      }
    }

    function drawCelestialBody(now: number) {
      if (theme === "light") {
        const x = w * 0.82;
        const y = h * 0.16;
        const r = Math.max(78, Math.min(w, h) * 0.12);
        const pulse = reduceMotion ? 1 : 0.94 + 0.06 * Math.sin(now / 1400);
        const glow = ctx.createRadialGradient(x, y, r * 0.04, x, y, r * 1.8 * pulse);
        glow.addColorStop(0, "rgba(255,255,255,0.58)");
        glow.addColorStop(0.22, "rgba(255,236,170,0.28)");
        glow.addColorStop(0.58, "rgba(11,49,255,0.055)");
        glow.addColorStop(1, "rgba(255,255,255,0)");
        ctx.fillStyle = glow;
        ctx.beginPath();
        ctx.arc(x, y, r * 1.8 * pulse, 0, Math.PI * 2);
        ctx.fill();

        const disk = ctx.createRadialGradient(x - r * 0.22, y - r * 0.26, 0, x, y, r);
        disk.addColorStop(0, "rgba(255,255,255,0.82)");
        disk.addColorStop(0.54, "rgba(255,244,190,0.24)");
        disk.addColorStop(1, "rgba(255,255,255,0)");
        ctx.fillStyle = disk;
        ctx.beginPath();
        ctx.arc(x, y, r, 0, Math.PI * 2);
        ctx.fill();
        return;
      }

      // dark mode: no celestial body drawn
    }

    let t0 = performance.now();
    function tick(now: number) {
      const dt = (now - t0) / 1000;
      t0 = now;
      const palette = currentPalette();
      canvas!.style.opacity = String(palette.canvasOpacity);
      ctx.clearRect(0, 0, w, h);
      drawCelestialBody(now);

      for (const s of stars) {
        s.tw += reduceMotion ? 0 : dt * s.twSpeed;
        const pulse = theme === "dark"
          ? 0.16 + 0.84 * Math.pow(0.5 + 0.5 * Math.sin(s.tw), 2.2)
          : 0.86 + 0.14 * Math.sin(s.tw);
        const occasionalFlash = theme === "dark" && Math.sin(s.tw * 0.43 + s.z * 19) > 0.92 ? 1.45 : 1;
        const a = Math.min(1, s.baseA * pulse * occasionalFlash);
        s.x += reduceMotion ? 0 : (s.z - 0.5) * palette.drift;
        if (s.x > w + 4) s.x = -4;
        if (s.x < -4) s.x = w + 4;

        const rgb = s.hueShift ? palette.warm : palette.cool;
        ctx.beginPath();
        ctx.fillStyle = `rgba(${rgb},${a})`;
        ctx.arc(s.x, s.y, s.r, 0, Math.PI * 2);
        ctx.fill();

        if (s.r > (theme === "dark" ? 0.82 : 0.68)) {
          const glowRgb = s.hueShift ? palette.glowWarm : palette.glowCool;
          ctx.beginPath();
          ctx.fillStyle = `rgba(${glowRgb},${a * (theme === "dark" ? 0.28 : 0.05)})`;
          ctx.arc(s.x, s.y, s.r * (theme === "dark" ? 6.5 : 4.2), 0, Math.PI * 2);
          ctx.fill();
        }

        if (s.cross && s.r > (theme === "dark" ? 0.7 : 0.72)) {
          drawCross(s.x, s.y, s.r, a * (theme === "dark" ? 0.58 : 0.12), rgb);
        }
      }

      spawnShootingStar();
      for (let i = shootingStars.length - 1; i >= 0; i--) {
        const ss = shootingStars[i];
        ss.x += ss.vx; ss.y += ss.vy; ss.life++;
        const a = Math.sin(Math.PI * (ss.life / ss.maxLife));
        const grad = ctx.createLinearGradient(ss.x - ss.vx * 20, ss.y - ss.vy * 20, ss.x, ss.y);
        grad.addColorStop(0, "rgba(180,210,255,0)");
        grad.addColorStop(1, theme === "dark" ? `rgba(220,235,255,${a * 0.9})` : `rgba(11,49,255,${a * 0.32})`);
        ctx.strokeStyle = grad;
        ctx.lineWidth = theme === "dark" ? 1.4 : 0.9;
        ctx.beginPath();
        ctx.moveTo(ss.x - ss.vx * 20, ss.y - ss.vy * 20);
        ctx.lineTo(ss.x, ss.y);
        ctx.stroke();
        ctx.beginPath();
        ctx.fillStyle = theme === "dark" ? `rgba(255,255,255,${a})` : `rgba(11,49,255,${a * 0.54})`;
        ctx.arc(ss.x, ss.y, theme === "dark" ? 1.6 : 1.0, 0, Math.PI * 2);
        ctx.fill();
        if (ss.life >= ss.maxLife || ss.x > w + 50 || ss.y > h + 50) shootingStars.splice(i, 1);
      }

      rafId = requestAnimationFrame(tick);
    }

    const observer = new MutationObserver(() => {
      const nextTheme = document.documentElement.getAttribute("data-theme") === "light" ? "light" : "dark";
      if (nextTheme !== theme) {
        theme = nextTheme;
        shootingStars.splice(0);
        buildStars();
      }
    });

    window.addEventListener("resize", resize);
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    resize();
    rafId = requestAnimationFrame(tick);

    return () => {
      cancelAnimationFrame(rafId);
      window.removeEventListener("resize", resize);
      observer.disconnect();
    };
  }, []);

  return (
    <canvas
      aria-hidden="true"
      ref={canvasRef}
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 1,
        pointerEvents: "none",
        display: "block",
        mixBlendMode: "normal",
      }}
    />
  );
}
