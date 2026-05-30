import { Suspense } from "react";
import OutreachPage from "@/components/OutreachPage";

export default function OutreachRoute() {
  return (
    <div className="site-shell" style={{ paddingTop: 48, paddingBottom: 88 }}>
      <Suspense>
        <OutreachPage />
      </Suspense>
    </div>
  );
}
