"use client";

import { useCallback, useEffect, useId, useRef, useState, forwardRef } from "react";
import type { CSSProperties, ReactNode } from "react";

// ── Shader math (ported from liquid-glass-react) ──────────────────────────────

function smoothStep(a: number, b: number, t: number): number {
  t = Math.max(0, Math.min(1, (t - a) / (b - a)));
  return t * t * (3 - 2 * t);
}

function len(x: number, y: number): number {
  return Math.sqrt(x * x + y * y);
}

function roundedRectSDF(x: number, y: number, w: number, h: number, r: number): number {
  const qx = Math.abs(x) - w + r;
  const qy = Math.abs(y) - h + r;
  return Math.min(Math.max(qx, qy), 0) + len(Math.max(qx, 0), Math.max(qy, 0)) - r;
}

// Generates the displacement map at a capped resolution for performance
function generateDisplacementMap(elemW: number, elemH: number): string {
  const MAX = 256;
  const aspect = elemW / elemH;
  const w = Math.round(Math.min(MAX, elemW));
  const h = Math.round(Math.min(MAX, elemH));

  const canvas = document.createElement("canvas");
  canvas.width = w;
  canvas.height = h;
  const ctx = canvas.getContext("2d")!;

  const rawValues: number[] = [];
  let maxScale = 0;

  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      const ix = x / w - 0.5;
      const iy = y / h - 0.5;

      // Rounded-rect SDF lens: radius 0.6 with half-extents (0.3, 0.2) = near-circle
      const dist = roundedRectSDF(ix, iy, 0.3, 0.2, 0.6);
      const disp = smoothStep(0.8, 0, dist - 0.15);
      const scaled = smoothStep(0, 1, disp);

      const dx = (ix * scaled + 0.5) * w - x;
      const dy = (iy * scaled + 0.5) * h - y;

      maxScale = Math.max(maxScale, Math.abs(dx), Math.abs(dy));
      rawValues.push(dx, dy);
    }
  }

  maxScale = Math.max(maxScale, 1);

  const imageData = ctx.createImageData(w, h);
  const data = imageData.data;
  let ri = 0;

  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      const dx = rawValues[ri++];
      const dy = rawValues[ri++];
      const edge = Math.min(1, Math.min(x, y, w - x - 1, h - y - 1) / 2);
      const r = (dx * edge) / maxScale + 0.5;
      const g = (dy * edge) / maxScale + 0.5;
      const pi = (y * w + x) * 4;
      data[pi]     = Math.max(0, Math.min(255, r * 255));
      data[pi + 1] = Math.max(0, Math.min(255, g * 255));
      data[pi + 2] = Math.max(0, Math.min(255, g * 255));
      data[pi + 3] = 255;
    }
  }

  ctx.putImageData(imageData, 0, 0);
  void aspect; // keep for future anisotropic tuning
  return canvas.toDataURL("image/png");
}

// ── Component ─────────────────────────────────────────────────────────────────

export interface LiquidGlassProps {
  children?: ReactNode;
  className?: string;
  /** Styles for the outer container (position, width, height, etc.) */
  style?: CSSProperties;
  /** Styles for the content wrapper (display, flex, overflow, etc.) */
  contentStyle?: CSSProperties;
  borderRadius?: number | string;
  /** Displacement strength — default 28 */
  displacementScale?: number;
  /** Glass fill tint */
  tint?: string;
}

const LiquidGlass = forwardRef<HTMLDivElement, LiquidGlassProps>(
  (
    {
      children,
      className,
      style,
      contentStyle,
      borderRadius = 28,
      displacementScale = 28,
      tint = "rgba(118,122,128,0.22)",
    },
    ref,
  ) => {
    const rawId = useId();
    const uid = rawId.replace(/:/g, "");
    const containerRef = useRef<HTMLDivElement | null>(null);
    const [dispMap, setDispMap] = useState<string | null>(null);

    const generate = useCallback(() => {
      const el = containerRef.current;
      if (!el) return;
      const { offsetWidth: w, offsetHeight: h } = el;
      if (w > 0 && h > 0) setDispMap(generateDisplacementMap(w, h));
    }, []);

    useEffect(() => {
      generate();
      const ro = new ResizeObserver(generate);
      if (containerRef.current) ro.observe(containerRef.current);
      return () => ro.disconnect();
    }, [generate]);

    const filterId = `lgf-${uid}`;
    const resolvedRadius =
      borderRadius === 0
        ? 0
        : typeof borderRadius === "number"
          ? `${borderRadius + 10}px ${borderRadius + 2}px ${borderRadius + 16}px ${borderRadius + 6}px / ${borderRadius + 4}px ${borderRadius - 2}px ${borderRadius + 12}px ${borderRadius + 2}px`
          : borderRadius;

    return (
      <div
        ref={(el) => {
          containerRef.current = el;
          if (typeof ref === "function") ref(el);
          else if (ref) (ref as React.MutableRefObject<HTMLDivElement | null>).current = el;
        }}
        className={className}
        style={{ position: "relative", borderRadius: resolvedRadius, overflow: "hidden", isolation: "isolate", ...style }}
      >
        {/* Filter definition */}
        {dispMap && (
          <svg
            style={{ position: "absolute", width: 0, height: 0, overflow: "hidden" }}
            aria-hidden="true"
          >
            <defs>
              <filter
                id={filterId}
                x="0%"
                y="0%"
                width="100%"
                height="100%"
                colorInterpolationFilters="sRGB"
              >
                <feImage href={dispMap} result="dispMap" preserveAspectRatio="none" />
                <feDisplacementMap
                  in="SourceGraphic"
                  in2="dispMap"
                  scale={displacementScale}
                  xChannelSelector="R"
                  yChannelSelector="G"
                  result="displaced"
                />
              </filter>
            </defs>
          </svg>
        )}

        {/* Backdrop blur + distortion layer */}
        <div
          style={{
            position: "absolute",
            inset: 0,
            backdropFilter: "blur(30px) saturate(200%) brightness(0.98)",
            WebkitBackdropFilter: "blur(30px) saturate(200%) brightness(0.98)",
            ...(dispMap ? { filter: `url(#${filterId})` } : {}),
            zIndex: 0,
          }}
        />

        {/* Glass tint + border */}
        <div
          style={{
            position: "absolute",
            inset: 0,
            background:
              `linear-gradient(135deg, var(--glass-edge-1, rgba(255,255,255,0.06)) 0%, ${tint ?? "var(--glass)"} 44%, var(--glass-edge-2, rgba(84,88,94,0.08)) 100%)`,
            border: "1px solid rgba(176,180,186,0.18)",
            boxShadow:
              "inset 0 1.5px 0 var(--glass-inset-top, rgba(255,255,255,0.16)), inset 0 -1px 0 var(--glass-inset-bottom, rgba(84,88,94,0.14)), 0 1px 3px rgba(0,0,0,0.32), 0 20px 54px rgba(0,0,0,0.46)",
            borderRadius: resolvedRadius,
            zIndex: 1,
            pointerEvents: "none",
          }}
        />

        {/* Organic glow pockets */}
        <div
          style={{
            position: "absolute",
            inset: "-12% -16% auto auto",
            width: "58%",
            height: "58%",
            background: "radial-gradient(circle at 30% 30%, var(--glass-glow-1, rgba(255,255,255,0.12)), var(--glass-glow-2, rgba(118,122,128,0.08)) 35%, transparent 72%)",
            filter: "blur(18px)",
            mixBlendMode: "screen",
            pointerEvents: "none",
            zIndex: 1,
          }}
        />
        <div
          style={{
            position: "absolute",
            inset: "auto auto -20% -18%",
            width: "64%",
            height: "64%",
            background: "radial-gradient(circle at 50% 50%, var(--glass-edge-2, rgba(84,88,94,0.14)), var(--glass-glow-2, rgba(118,122,128,0.06)) 40%, transparent 72%)",
            filter: "blur(24px)",
            mixBlendMode: "screen",
            pointerEvents: "none",
            zIndex: 1,
          }}
        />

        {/* Top specular sheen */}
        <div
          style={{
            position: "absolute",
            top: 0,
            left: 0,
            right: 0,
            height: "52%",
            background:
              "linear-gradient(180deg, var(--glass-sheen-1, rgba(255,255,255,0.16)) 0%, var(--glass-sheen-2, rgba(224,226,230,0.06)) 34%, var(--glass-sheen-3, rgba(118,122,128,0.03)) 72%, transparent 100%)",
            borderRadius: typeof resolvedRadius === "string" ? resolvedRadius : `${resolvedRadius}px`,
            pointerEvents: "none",
            zIndex: 2,
          }}
        />

        {/* Content */}
        <div style={{ position: "relative", zIndex: 3, ...contentStyle }}>
          {children}
        </div>
      </div>
    );
  },
);

LiquidGlass.displayName = "LiquidGlass";
export default LiquidGlass;
