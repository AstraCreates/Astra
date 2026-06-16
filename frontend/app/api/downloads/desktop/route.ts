import { access } from "node:fs/promises";
import { createReadStream } from "node:fs";
import path from "node:path";
import { Readable } from "node:stream";

export const runtime = "nodejs";

const DEFAULT_DMG_PATH = path.resolve(
  process.cwd(),
  "..",
  "desktop",
  "src-tauri",
  "target",
  "release",
  "bundle",
  "dmg",
  "Astra Desktop_0.1.0_aarch64.dmg"
);

function getDmgPath() {
  return process.env.DESKTOP_DMG_PATH || DEFAULT_DMG_PATH;
}

export async function GET() {
  const externalUrl = process.env.DESKTOP_DOWNLOAD_URL;
  if (externalUrl) {
    return Response.redirect(externalUrl, 302);
  }

  const filePath = getDmgPath();

  try {
    await access(filePath);
  } catch {
    return Response.json(
      {
        error: "desktop_download_unavailable",
        message:
          "The Astra Desktop installer is not available on this server yet. Set DESKTOP_DOWNLOAD_URL or place the built DMG at the configured path.",
      },
      { status: 404 }
    );
  }

  const fileName = path.basename(filePath);
  const stream = createReadStream(filePath);

  return new Response(Readable.toWeb(stream) as ReadableStream, {
    headers: {
      "Content-Type": "application/x-apple-diskimage",
      "Content-Disposition": `attachment; filename="${fileName}"`,
      "Cache-Control": "no-store",
    },
  });
}
