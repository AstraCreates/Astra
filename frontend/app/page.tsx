"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { signIn } from "next-auth/react";
import { AuroraBackground } from "@/components/ui/aurora-background";
import { useDevUser } from "@/lib/use-dev-user";

export default function Home() {
  const { isSignedIn } = useDevUser();
  const router = useRouter();
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    setHydrated(true);
  }, []);


  const readySignedIn = hydrated && isSignedIn;

  const handleCta = () => {
    if (readySignedIn) {
      router.push("/dashboard");
      return;
    }
    signIn("google", { callbackUrl: "/dashboard" });
  };

  return (
    <AuroraBackground className="bg-zinc-900 dark:bg-zinc-900">
      <div className="sp-content">
        <div className="sp-mark">
          <div className="sp-logo-img" role="img" aria-label="Astra logo" />
          <span className="sp-wordmark">ASTRA</span>
        </div>

        <h1 className="sp-headline">
          You bring the company,<br />Astra brings the rest.
        </h1>

        <p className="sp-sub">
          One goal. Twelve specialist agents. Research, legal, product, deploys,
          and ops in a single coordinated run.
        </p>

        <button className="sp-cta" onClick={handleCta}>
          {readySignedIn ? "Open dashboard" : "Start a run"} →
        </button>
      </div>
    </AuroraBackground>
  );
}
