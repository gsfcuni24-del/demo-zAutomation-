"use client";

import { useQuery } from "@tanstack/react-query";
import { Activity, Cpu } from "lucide-react";

import { Button } from "@/components/ui/button";
import { fetchHealth } from "@/lib/api";
import type { HealthResponse } from "@/types/api";

export default function HomePage() {
  const { data, isError, isLoading } = useQuery<HealthResponse>({
    queryKey: ["health"],
    queryFn: fetchHealth,
    refetchInterval: 10_000,
  });

  const statusLabel = isLoading ? "CONNECTING" : isError ? "OFFLINE" : "ONLINE";
  const statusColor = isLoading
    ? "bg-status-warn"
    : isError
      ? "bg-status-fault"
      : "bg-status-ok";

  return (
    <main className="relative flex min-h-screen items-center justify-center overflow-hidden bg-industrial-grid bg-grid">
      <div className="pointer-events-none absolute inset-0 bg-gradient-to-b from-background/40 via-background/80 to-background" />
      <section className="relative w-full max-w-xl rounded-lg border bg-card/80 p-8 shadow-2xl backdrop-blur">
        <div className="mb-6 flex items-center gap-3">
          <Cpu className="h-8 w-8 text-primary" />
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">zAutomation Helper AI</h1>
            <p className="font-mono text-xs uppercase tracking-widest text-muted-foreground">
              {"// system foundation · phase 1"}
            </p>
          </div>
        </div>
        <div className="mb-6 flex items-center justify-between rounded-md border bg-background/60 px-4 py-3 font-mono text-sm">
          <span className="flex items-center gap-2 text-muted-foreground">
            <Activity className="h-4 w-4" /> API LINK
          </span>
          <span className="flex items-center gap-2">
            <span className={`h-2 w-2 rounded-full ${statusColor}`} />
            {statusLabel}
            {data ? ` · v${data.version} · ${data.environment}` : null}
          </span>
        </div>
        <Button className="w-full font-mono uppercase tracking-wider" disabled>
          System access — coming in Phase 6
        </Button>
      </section>
    </main>
  );
}
