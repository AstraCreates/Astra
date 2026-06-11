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
  ({ children, className, style, contentStyle, borderRadius = 12, tintOpacity = 0.05 }, ref) => {
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
          ...style,
        }}
      >
        {/* Refraction layer */}
        <div
          aria-hidden="true"
          style={{
            position: "absolute", inset: 0,
            borderRadius: "inherit",
            backdropFilter: "url(#lg-filter) blur(1px)",
            WebkitBackdropFilter: "url(#lg-filter) blur(1px)",
            zIndex: 0,
          }}
        />
        {/* Tint + specular inset shadow */}
        <div
          aria-hidden="true"
          style={{
            position: "absolute", inset: 0,
            borderRadius: "inherit",
            background: `rgba(255,255,255,${tintOpacity})`,
            boxShadow: "inset 0 1px 0 rgba(255,255,255,0.9), inset 0 -1px 0 rgba(0,0,0,0.04)",
            zIndex: 1,
            pointerEvents: "none",
          }}
        />
        <div style={{ position: "relative", zIndex: 2, ...contentStyle }}>
          {children}
        </div>
      </div>
    );
  }
);

LiquidGlass.displayName = "LiquidGlass";
export default LiquidGlass;
