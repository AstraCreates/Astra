"use client";

import { forwardRef } from "react";
import type { CSSProperties, ReactNode } from "react";

export interface LiquidGlassProps {
  children?: ReactNode;
  className?: string;
  style?: CSSProperties;
  contentStyle?: CSSProperties;
  borderRadius?: number | string;
  displacementScale?: number;
  tint?: string;
}

const LiquidGlass = forwardRef<HTMLDivElement, LiquidGlassProps>(
  ({ children, className, style, contentStyle, borderRadius = 24 }, ref) => {
    const resolvedRadius =
      typeof borderRadius === "number" ? `${borderRadius}px` : borderRadius;

    return (
      <div
        ref={ref}
        className={["liquid-glass astra-convergence-glass", className].filter(Boolean).join(" ")}
        style={{
          position: "relative",
          borderRadius: resolvedRadius,
          overflow: "hidden",
          isolation: "isolate",
          ...style,
        }}
      >
        <div className="astra-convergence-glass__grid" aria-hidden="true" />
        <div className="astra-convergence-glass__stars" aria-hidden="true" />
        <div className="astra-convergence-glass__core" aria-hidden="true" />
        <div className="astra-convergence-glass__orbit" aria-hidden="true" />
        <div className="astra-convergence-glass__orbit astra-convergence-glass__orbit--blue" aria-hidden="true" />
        <div className="astra-convergence-glass__spark" aria-hidden="true" />
        <div className="astra-convergence-glass__spark astra-convergence-glass__spark--blue" aria-hidden="true" />
        <div data-lg-content="true" style={{ position: "relative", zIndex: 3, ...contentStyle }}>
          {children}
        </div>
      </div>
    );
  },
);

LiquidGlass.displayName = "LiquidGlass";
export default LiquidGlass;
