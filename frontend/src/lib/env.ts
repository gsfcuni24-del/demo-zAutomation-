function stripTrailingSlash(url: string): string {
  return url.replace(/\/+$/, "");
}

export const env = {
  apiUrl: stripTrailingSlash(process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"),
  wsUrl: stripTrailingSlash(process.env.NEXT_PUBLIC_WS_URL ?? "ws://localhost:8000"),
} as const;
