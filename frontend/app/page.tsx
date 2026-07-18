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
    <AuroraBackground className="bg-zinc-50" data-theme="light">
      <div className="sp-content">
        <div className="sp-mark">
          <div className="sp-logo-img" role="img" aria-label="Astra logo" />
          <span className="sp-wordmark">ASTRA</span>
        </div>

        <h1 className="sp-headline">
          You bring the company,<br />Astra does the rest.
        </h1>

        <p className="sp-sub">
          One permanent Copilot. Named squads coordinate research, product, design,
          and operations around your company.
        </p>

        <button className="sp-cta" onClick={handleCta}>
          {readySignedIn ? "Open Company Home" : "Open your company"} →
        </button>
      </div>
    </AuroraBackground>
  );
}
