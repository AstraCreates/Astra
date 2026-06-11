import { Suspense } from "react";
import AppHome from "@/components/AppHome";

// Covers sidebar during Suspense hydration (useSearchParams causes AppHome to suspend)
const BlankCover = () => (
  <div style={{ position: "fixed", inset: 0, zIndex: 99999, background: "linear-gradient(140deg, #c0d8ff 0%, #a8c4ff 18%, #bde0ff 38%, #c4f0e8 62%, #d4ffe8 80%, #e8fff4 100%)" }} />
);

export default function HomePage() {
  return (
    <Suspense fallback={<BlankCover />}>
      <AppHome />
    </Suspense>
  );
}
