import { Suspense } from "react";
import AppHome from "@/components/AppHome";

// Covers sidebar during Suspense hydration (useSearchParams causes AppHome to suspend)
const BlankCover = () => (
  <div style={{ position: "fixed", inset: 0, zIndex: 99999, background: "#F3F4F7" }} />
);

export default function HomePage() {
  return (
    <Suspense fallback={<BlankCover />}>
      <AppHome />
    </Suspense>
  );
}
