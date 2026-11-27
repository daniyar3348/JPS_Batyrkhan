import type { NextConfig } from "next";

const config: NextConfig = {
  // A self-contained server in .next/standalone, for a small Docker image.
  output: "standalone",
  // The monorepo root, so the standalone build includes the shared packages.
  outputFileTracingRoot: new URL("..", import.meta.url).pathname,
  transpilePackages: ["@jps/api-client"],
  poweredByHeader: false,
  reactStrictMode: true,
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "X-Frame-Options", value: "SAMEORIGIN" },
          { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
        ],
      },
    ];
  },
};

export default config;
