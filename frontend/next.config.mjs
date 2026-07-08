const isProd = process.env.NODE_ENV === "production";

const nextConfig = {
  devIndicators: false,
  output: isProd ? "standalone" : undefined,
  turbopack: {
    root: import.meta.dirname,
  },
  async rewrites() {
    const backendUrl = process.env.BACKEND_URL || "http://localhost:8000";
    return [
      // NextAuth routes handled by Next.js — do NOT proxy to backend
      {
        source: "/api/auth/:path*",
        destination: "/api/auth/:path*",
      },
      {
        source: "/api/:path*",
        destination: `${backendUrl}/:path*`,
      },
    ];
  },
};

export default nextConfig;
