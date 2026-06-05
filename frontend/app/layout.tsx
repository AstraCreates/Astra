import type { Metadata } from "next";
import { Geist, JetBrains_Mono } from "next/font/google";
import ApiAuthBridge from "@/components/ApiAuthBridge";
import CookieNotice from "@/components/CookieNotice";
import SessionWrapper from "@/components/SessionWrapper";
import SiteNav from "./site-nav";
import StarField from "./components/StarField";
import "./globals.css";

const geist = Geist({ subsets: ["latin"], variable: "--font-geist-sans" });
const jetBrainsMono = JetBrains_Mono({ subsets: ["latin"], variable: "--font-jetbrains-mono" });

export const metadata: Metadata = {
  title: "Astra — Your AI Founding Team",
  description: "Launch and operate a company with a coordinated AI founding team.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${geist.variable} ${jetBrainsMono.variable} antialiased`} data-theme="dark" suppressHydrationWarning>
      <head>
        <script
          dangerouslySetInnerHTML={{
            __html: `try{var t=localStorage.getItem("astra-theme");if(t!=="dark"&&t!=="light"){t=matchMedia("(prefers-color-scheme: dark)").matches?"dark":"light"}document.documentElement.setAttribute("data-theme",t)}catch(e){document.documentElement.setAttribute("data-theme","dark")}`,
          }}
        />
      </head>
      <body suppressHydrationWarning>
        <StarField />
        <SessionWrapper>
          <ApiAuthBridge />
          <SiteNav />
          <main>{children}</main>
          <CookieNotice />
        </SessionWrapper>
      </body>
    </html>
  );
}
