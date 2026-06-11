"use client";

import { forwardRef } from "react";
import type { CSSProperties, ReactNode } from "react";

export interface LiquidGlassProps {
  children?: ReactNode;
  className?: string;
  style?: CSSProperties;
  contentStyle?: CSSProperties;
  borderRadius?: number | string;
  tintOpacity?: number;
}

const LiquidGlass = forwardRef<HTMLDivElement, LiquidGlassProps>(
  ({ children, className, style, contentStyle, borderRadius = 12, tintOpacity = 0.15 }, ref) => {
    const r = typeof borderRadius === "number" ? `${borderRadius}px` : borderRadius;

    return (
      <div
        ref={ref}
        className={["lg-panel", className].filter(Boolean).join(" ")}
        style={{
          position: "relative",
          borderRadius: r,
          isolation: "isolate",
          overflow: "hidden",
          border: "1px solid rgba(255,255,255,0.55)",
          boxShadow: "0 6px 24px rgba(0,0,0,0.10), 0 1px 3px rgba(0,0,0,0.05)",
          ...style,
        }}
      >
        {/* Refraction layer: blurs backdrop + SVG distortion warp */}
        <div
          aria-hidden="true"
          style={{
            position: "absolute", inset: 0,
            borderRadius: "inherit",
            backdropFilter: "blur(8px) saturate(1.5)",
            WebkitBackdropFilter: "blur(8px) saturate(1.5)",
            filter: "url(#glass-distortion)",
            zIndex: 0,
          }}
        />
        {/* Frosted white tint */}
        <div
          aria-hidden="true"
          style={{
            position: "absolute", inset: 0,
            borderRadius: "inherit",
            background: `rgba(255,255,255,${tintOpacity})`,
            zIndex: 1,
            pointerEvents: "none",
          }}
        />
        {/* Specular edge highlights */}
        <div
          aria-hidden="true"
          style={{
            position: "absolute", inset: 0,
            borderRadius: "inherit",
            boxShadow:
              "inset 0 1.5px 0 rgba(255,255,255,0.95), " +
              "inset 2px 0 0 rgba(255,255,255,0.4), " +
              "inset 0 -1px 0 rgba(0,0,0,0.04)",
            zIndex: 2,
            pointerEvents: "none",
          }}
        />
        <div style={{ position: "relative", zIndex: 3, ...contentStyle }}>
          {children}
        </div>
      </div>
    );
  }
);

LiquidGlass.displayName = "LiquidGlass";
export default LiquidGlass;
