"use client";

import { useEffect, useState } from "react";

/** Auto-detects a phone/small-tablet viewport (defaults to ≤768px) and tracks
 *  resize/orientation changes. SSR-safe: returns false until mounted. */
export function useIsMobile(breakpoint = 768): boolean {
  const [mobile, setMobile] = useState(false);
  useEffect(() => {
    if (typeof window === "undefined") return;
    const mq = window.matchMedia(`(max-width: ${breakpoint}px)`);
    const update = () => setMobile(mq.matches);
    update();
    mq.addEventListener("change", update);
    return () => mq.removeEventListener("change", update);
  }, [breakpoint]);
  return mobile;
}
