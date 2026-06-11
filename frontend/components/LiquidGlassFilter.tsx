"use client";

import { useEffect, useRef } from "react";
import {
  SURFACE_FNS,
  calcRefractionProfile,
  genDisplacementMap,
  genSpecularMap,
} from "@/lib/liquidGlass";

// Generates physics-based liquid glass SVG filter and injects it globally.
// One filter (lg-filter) sized at 480x320 with radius=12 covers most card sizes.
export default function LiquidGlassFilter() {
  const defsRef = useRef<SVGDefsElement>(null);

  useEffect(() => {
    const defs = defsRef.current;
    if (!defs) return;

    const W = 480, H = 320, R = 12, BEZEL = 16;
    const glassThickness = 5, ior = 1.65, scaleRatio = 1.2;

    const profile = calcRefractionProfile(glassThickness, BEZEL, SURFACE_FNS.smooth, ior, 128);
    const maxDisp = Math.max(...Array.from(profile).map(Math.abs)) || 1;
    const dispUrl  = genDisplacementMap(W, H, R, BEZEL, profile, maxDisp);
    const specUrl  = genSpecularMap(W, H, R, BEZEL * 2.5, Math.PI / 3);
    const scale    = maxDisp * scaleRatio;

    defs.innerHTML = `
      <filter id="lg-filter" x="-2%" y="-2%" width="104%" height="104%" color-interpolation-filters="sRGB">
        <feGaussianBlur in="SourceGraphic" stdDeviation="3" result="blurred" />
        <feImage href="${dispUrl}" x="0" y="0" width="100%" height="100%"
          preserveAspectRatio="none" result="disp_map" />
        <feDisplacementMap in="blurred" in2="disp_map"
          scale="${scale}" xChannelSelector="R" yChannelSelector="G"
          result="displaced" />
        <feColorMatrix in="displaced" type="saturate" values="1.5" result="sat" />
        <feImage href="${specUrl}" x="0" y="0" width="100%" height="100%"
          preserveAspectRatio="none" result="spec" />
        <feComponentTransfer in="spec" result="spec_faded">
          <feFuncA type="linear" slope="0.45" />
        </feComponentTransfer>
        <feBlend in="spec_faded" in2="sat" mode="normal" />
      </filter>
    `;
  }, []);

  return (
    <svg
      aria-hidden="true"
      style={{ position: "fixed", width: 0, height: 0, overflow: "hidden", pointerEvents: "none" }}
    >
      <defs ref={defsRef} />
    </svg>
  );
}
