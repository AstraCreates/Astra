import { Suspense } from "react";
import OnboardingWizard from "@/components/OnboardingWizard";

export default function OnboardingPage() {
  return (
    <Suspense>
      <OnboardingWizard />
    </Suspense>
  );
}
