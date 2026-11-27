/** Server configuration, from environment variables (read when a page is rendered, not at build time). */

function trim(url: string): string {
  return url.replace(/\/+$/, "");
}

export const config = {
  /** Where the server reaches the platform's API (inside Docker: http://api:8000). */
  get apiUrl(): string {
    return trim(process.env.JPS_API_URL ?? "http://localhost:8000");
  },
  /** Where browsers reach the API; downloads of files that are not in S3 redirect there. */
  get publicApiUrl(): string {
    return trim(process.env.JPS_PUBLIC_API_URL ?? process.env.JPS_API_URL ?? "http://localhost:8000");
  },
  /** This site's own address, for canonical links, the sitemap and feeds. */
  get siteUrl(): string {
    return trim(process.env.JPS_SITE_URL ?? "http://localhost:3000");
  },
  /** The editorial workspace: submitting and signing in. */
  get workspaceUrl(): string {
    return trim(process.env.JPS_WORKSPACE_URL ?? "http://localhost:5173");
  },
  /** Shared with the platform (JPS_SITE_REVALIDATE_SECRET there): signs requests to rebuild pages. */
  get revalidateSecret(): string | undefined {
    return process.env.JPS_REVALIDATE_SECRET || undefined;
  },
};
