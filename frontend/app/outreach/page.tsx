import { Suspense } from "react";
import OutreachPage from "@/components/OutreachPage";

export default function OutreachRoute() {
  return (
    <Suspense>
      <OutreachPage />
    </Suspense>
  );
}
