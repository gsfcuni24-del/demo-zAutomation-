"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { env } from "@/lib/env";
import type { SynthesisEvent, SynthesisRequest } from "@/types/synthesis";

export type ConnectionState = "connecting" | "open" | "closed";

export interface SynthesisRun {
  id: number;
  prompt: string;
  events: SynthesisEvent[];
  status: "running" | "completed" | "failed";
}

const MAX_BACKOFF_MS = 10_000;

function isFinal(event: SynthesisEvent): boolean {
  return event.agent === "orchestrator" && event.data?.final === true;
}

export function useSynthesis(projectId: string, onCompleted?: (event: SynthesisEvent) => void) {
  const [connection, setConnection] = useState<ConnectionState>("connecting");
  const [mode, setMode] = useState<string | null>(null);
  const [runs, setRuns] = useState<SynthesisRun[]>([]);
  const socketRef = useRef<WebSocket | null>(null);
  const onCompletedRef = useRef(onCompleted);

  useEffect(() => {
    onCompletedRef.current = onCompleted;
  }, [onCompleted]);

  useEffect(() => {
    let disposed = false;
    let attempt = 0;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const connect = () => {
      setConnection("connecting");
      const ws = new WebSocket(`${env.wsUrl}/ws/synthesis/${projectId}`);
      socketRef.current = ws;
      ws.onopen = () => {
        attempt = 0;
        setConnection("open");
      };
      ws.onmessage = (message) => {
        let event: SynthesisEvent;
        try {
          event = JSON.parse(String(message.data)) as SynthesisEvent;
        } catch {
          return;
        }
        if (event.status === "connected") {
          setMode(typeof event.data?.mode === "string" ? event.data.mode : null);
          return;
        }
        setRuns((prev) => {
          const last = prev.at(-1);
          if (!last || last.status !== "running") return prev;
          const final = isFinal(event);
          const status: SynthesisRun["status"] = final
            ? event.status === "completed"
              ? "completed"
              : "failed"
            : "running";
          return [...prev.slice(0, -1), { ...last, status, events: [...last.events, event] }];
        });
        if (isFinal(event) && event.status === "completed") onCompletedRef.current?.(event);
      };
      ws.onclose = () => {
        socketRef.current = null;
        if (disposed) return;
        setConnection("closed");
        setRuns((prev) =>
          prev.map((run) => (run.status === "running" ? { ...run, status: "failed" } : run)),
        );
        timer = setTimeout(connect, Math.min(MAX_BACKOFF_MS, 500 * 2 ** attempt++));
      };
    };

    connect();
    return () => {
      disposed = true;
      clearTimeout(timer);
      socketRef.current?.close();
      socketRef.current = null;
    };
  }, [projectId]);

  const busy = runs.some((run) => run.status === "running");

  const send = useCallback(
    (request: SynthesisRequest): boolean => {
      const ws = socketRef.current;
      if (!ws || ws.readyState !== WebSocket.OPEN || busy) return false;
      setRuns((prev) => [
        ...prev,
        { id: Date.now(), prompt: request.prompt, events: [], status: "running" },
      ]);
      ws.send(JSON.stringify(request));
      return true;
    },
    [busy],
  );

  return { connection, mode, runs, busy, send };
}
