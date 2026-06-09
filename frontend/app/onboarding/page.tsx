import { Suspense } from "react";
import OnboardingWizard from "@/components/OnboardingWizard";
import WordsPreloader from "@/components/WordsPreloader";

export default function OnboardingPage() {
  return (
    <WordsPreloader>
      <Suspense>
        <OnboardingWizard />
      </Suspense>
    </WordsPreloader>
  );
}
