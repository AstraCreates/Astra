const ADS_TXT = "google.com, pub-3644250649570397, DIRECT, f08c47fec0942fa0\n";

export const dynamic = "force-static";

export function GET() {
  return new Response(ADS_TXT, {
    headers: {
      "Cache-Control": "public, max-age=0, must-revalidate",
      "Content-Type": "text/plain; charset=utf-8",
    },
  });
}
