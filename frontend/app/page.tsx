"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { signIn } from "next-auth/react";
import SpaceEnv from "@/components/SpaceEnv";
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
    <>
      <SpaceEnv />
      <div className="sp-page">
        <div className="sp-content">
          <div className="sp-mark">
            <div className="sp-logo-img" role="img" aria-label="Astra logo" />
            <span className="sp-wordmark">ASTRA</span>
          </div>

          <h1 className="sp-headline">
            Launch the company,<br />not just the copy.
          </h1>

          <p className="sp-sub">
            One goal. Twelve specialist agents. Research, legal, product, deploys,
            and ops in a single coordinated run.
          </p>

          <button className="sp-cta" onClick={handleCta}>
            {readySignedIn ? "Open dashboard" : "Start a run"} →
          </button>
        </div>
      </div>
    </>
  );
}
