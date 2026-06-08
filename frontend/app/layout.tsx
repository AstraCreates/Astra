import type { Metadata } from "next";
import { Geist, DM_Sans, IBM_Plex_Mono } from "next/font/google";
import ApiAuthBridge from "@/components/ApiAuthBridge";
import CookieNotice from "@/components/CookieNotice";
import SessionWrapper from "@/components/SessionWrapper";
import AppChrome from "@/components/AppChrome";
import StarField from "./components/StarField";
import "./globals.css";
import "./astra-redesign.css";

const geist = Geist({ subsets: ["latin"], variable: "--font-geist-sans" });
const dmSans = DM_Sans({ subsets: ["latin"], weight: ["300", "400", "500", "600", "700"], variable: "--font-dm-sans" });
const ibmPlexMono = IBM_Plex_Mono({ subsets: ["latin"], weight: ["300", "400", "500"], variable: "--font-ibm-mono" });

export const metadata: Metadata = {
  title: "Astra — Your AI Founding Team",
  description: "Launch and operate a company with a coordinated AI founding team.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${geist.variable} ${dmSans.variable} ${ibmPlexMono.variable} antialiased`} data-theme="light" suppressHydrationWarning>
      <head>
        {/* Redesign baseline is light. Honour a saved preference, default light. */}
        <script
          dangerouslySetInnerHTML={{
            __html: `try{var t=localStorage.getItem("astra-theme");if(t!=="dark"&&t!=="light"){t="light"}document.documentElement.setAttribute("data-theme",t)}catch(e){document.documentElement.setAttribute("data-theme","light")}`,
          }}
        />
      </head>
      <body suppressHydrationWarning>
        <StarField />
        <SessionWrapper>
          <ApiAuthBridge />
          <AppChrome>{children}</AppChrome>
          <CookieNotice />
        </SessionWrapper>
      </body>
    </html>
  );
}
