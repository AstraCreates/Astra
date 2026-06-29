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
            <svg viewBox="0 0 320 295" className="sp-logo-svg" aria-hidden="true">
              <ellipse cx="160" cy="110" rx="42" ry="100" stroke="currentColor" strokeWidth="20" fill="none" strokeLinecap="round" transform="rotate(0, 160, 175)" />
              <ellipse cx="160" cy="110" rx="42" ry="100" stroke="currentColor" strokeWidth="20" fill="none" strokeLinecap="round" transform="rotate(120, 160, 175)" />
              <ellipse cx="160" cy="110" rx="42" ry="100" stroke="currentColor" strokeWidth="20" fill="none" strokeLinecap="round" transform="rotate(240, 160, 175)" />
            </svg>
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
