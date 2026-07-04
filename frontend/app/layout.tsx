import type { Metadata } from "next";
import { Geist, Geist_Mono, DM_Sans, IBM_Plex_Mono, JetBrains_Mono, Pixelify_Sans, Instrument_Sans } from "next/font/google";
import ApiAuthBridge from "@/components/ApiAuthBridge";
import CookieNotice from "@/components/CookieNotice";
import SessionWrapper from "@/components/SessionWrapper";
import AppChrome from "@/components/AppChrome";
import { CompanyProvider } from "@/lib/company-context";
import "./globals.css";
import "./astra-redesign.css";

const geist = Geist({ subsets: ["latin"], variable: "--font-geist-sans" });
const geistMono = Geist_Mono({ subsets: ["latin"], variable: "--font-geist-mono" });
const dmSans = DM_Sans({ subsets: ["latin"], weight: ["300", "400", "500", "600", "700"], variable: "--font-dm-sans" });
const ibmPlexMono = IBM_Plex_Mono({ subsets: ["latin"], weight: ["300", "400", "500"], variable: "--font-ibm-mono" });
const jetbrainsMono = JetBrains_Mono({ subsets: ["latin"], weight: ["400", "500", "700"], variable: "--font-jetbrains-mono" });
const pixelifySans = Pixelify_Sans({ subsets: ["latin"], weight: ["400", "500", "600", "700"], variable: "--font-pixel" });
const instrumentSans = Instrument_Sans({ subsets: ["latin"], weight: ["400", "500", "600", "700"], variable: "--font-instrument" });

export const metadata: Metadata = {
  title: "Astra — Your AI Founding Team",
  description: "Launch and operate a company with a coordinated AI founding team.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${geist.variable} ${geistMono.variable} ${dmSans.variable} ${ibmPlexMono.variable} ${jetbrainsMono.variable} ${pixelifySans.variable} ${instrumentSans.variable} antialiased`} data-theme="light" suppressHydrationWarning>
      <body suppressHydrationWarning>
        <SessionWrapper>
          <ApiAuthBridge />
          <CompanyProvider>
            <AppChrome>{children}</AppChrome>
          </CompanyProvider>
          <CookieNotice />
        </SessionWrapper>
      </body>
    </html>
  );
}
