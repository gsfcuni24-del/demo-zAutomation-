"use client";

import {
  Bot,
  CheckCircle2,
  CircleDot,
  Loader2,
  RotateCcw,
  SendHorizontal,
  User,
  XCircle,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState, type FormEvent, type KeyboardEvent } from "react";

import { Button } from "@/components/ui/button";
import type { ConnectionState, SynthesisRun } from "@/hooks/use-synthesis";
import { cn } from "@/lib/utils";
import type { SynthesisAgent, SynthesisEvent, SynthesisStatus } from "@/types/synthesis";

export const AGENT_LABELS: Record<SynthesisAgent, string> = {
  orchestrator: "Orchestrator",
  excel_parser: "IO-List Parser",
  tag_namer: "Tag Namer",
  standards_retriever: "IEC 61131-3 RAG",
  logic_drafter: "Logic Drafter",
  hmi_layouter: "HMI Layouter",
  uir_merge: "UIR Merge",
  safety_auditor: "Safety Auditor",
  vendor_compiler: "Vendor Compiler",
  diff_engine: "Diff Engine",
};

const STATUS_STYLE: Record<SynthesisStatus, string> = {
  connected: "text-muted-foreground",
  started: "text-primary",
  completed: "text-status-ok",
  retry: "text-status-warn",
  failed: "text-status-fault",
};

interface TimelineStep {
  key: string;
  event: SynthesisEvent;
}

/** Collapse "started" + matching "completed/failed" into a single step. */
export function buildTimeline(events: SynthesisEvent[]): TimelineStep[] {
  const steps: TimelineStep[] = [];
  events.forEach((event, index) => {
    const last = steps[steps.length - 1];
    if (
      last &&
      last.event.status === "started" &&
      last.event.agent === event.agent &&
      (event.status === "completed" || event.status === "failed") &&
      last.event.attempt === event.attempt
    ) {
      last.event = event;
      return;
    }
    steps.push({ key: `${index}-${event.agent}`, event });
  });
  return steps;
}

function StepIcon({ status, live }: { status: SynthesisStatus; live: boolean }) {
  const className = cn("h-4 w-4 shrink-0", STATUS_STYLE[status]);
  if (status === "started") {
    return live ? <Loader2 className={cn(className, "animate-spin")} /> : <CircleDot className={className} />;
  }
  if (status === "completed") return <CheckCircle2 className={className} />;
  if (status === "retry") return <RotateCcw className={className} />;
  if (status === "failed") return <XCircle className={className} />;
  return <CircleDot className={className} />;
}

function RunTimeline({ run }: { run: SynthesisRun }) {
  const steps = useMemo(() => buildTimeline(run.events), [run.events]);
  return (
    <div className="space-y-2" data-testid="synthesis-run" data-status={run.status}>
      <div className="flex items-start gap-2">
        <User className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
        <p className="whitespace-pre-wrap rounded-md bg-accent px-2 py-1.5 text-xs">{run.prompt}</p>
      </div>
      <div className="flex items-start gap-2">
        <Bot className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
        <ol className="relative min-w-0 flex-1 space-y-1.5 border-l border-border pl-3" data-testid="synthesis-timeline">
          {steps.map(({ key, event }, i) => {
            const live = run.status === "running" && i === steps.length - 1;
            const feedback = Array.isArray(event.data?.feedback) ? (event.data.feedback as string[]) : [];
            return (
              <li
                key={key}
                className="animate-in fade-in slide-in-from-bottom-1 duration-300"
                data-agent={event.agent}
                data-status={event.status}
              >
                <div className="flex items-start gap-1.5">
                  <StepIcon status={event.status} live={live} />
                  <div className="min-w-0">
                    <p className="text-[11px] font-semibold">
                      {AGENT_LABELS[event.agent] ?? event.agent}
                      {event.attempt && event.agent === "logic_drafter" ? (
                        <span className="ml-1 font-mono font-normal text-muted-foreground">#{event.attempt}</span>
                      ) : null}
                    </p>
                    <p className={cn("break-words text-[11px]", event.status === "failed" ? "text-status-fault" : "text-muted-foreground")}>
                      {event.message}
                    </p>
                    {feedback.length && event.status === "retry" ? (
                      <ul className="mt-1 space-y-0.5 font-mono text-[10px] text-status-warn">
                        {feedback.map((f) => (
                          <li key={f} className="break-words">{f}</li>
                        ))}
                      </ul>
                    ) : null}
                  </div>
                </div>
              </li>
            );
          })}
          {run.status === "running" && !steps.length ? (
            <li className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" /> Waiting for pipeline…
            </li>
          ) : null}
        </ol>
      </div>
    </div>
  );
}

const CONNECTION_STYLE: Record<ConnectionState, string> = {
  open: "bg-status-ok",
  connecting: "bg-status-warn animate-pulse",
  closed: "bg-status-fault",
};

interface ChatPromptProps {
  connection: ConnectionState;
  mode: string | null;
  runs: SynthesisRun[];
  busy: boolean;
  onSend: (prompt: string) => boolean;
}

export function ChatPrompt({ connection, mode, runs, busy, onSend }: ChatPromptProps) {
  const [prompt, setPrompt] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);
  const lastRun = runs[runs.length - 1];

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [runs.length, lastRun?.events.length]);

  const submit = (event?: FormEvent) => {
    event?.preventDefault();
    const text = prompt.trim();
    if (text && onSend(text)) setPrompt("");
  };

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey) submit(event);
  };

  const disabled = connection !== "open" || busy;

  return (
    <div className="flex min-h-0 flex-1 flex-col" data-testid="chat-prompt">
      <div className="flex items-center gap-2 border-b px-3 py-2">
        <Bot className="h-4 w-4 text-primary" />
        <span className="text-xs font-semibold">AI Assistant</span>
        <span className="ml-auto flex items-center gap-1.5 font-mono text-[10px] text-muted-foreground" data-testid="ws-status">
          <span className={cn("h-2 w-2 rounded-full", CONNECTION_STYLE[connection])} />
          {connection}
          {mode ? ` · ${mode}` : ""}
        </span>
      </div>
      <div ref={scrollRef} className="min-h-0 flex-1 space-y-4 overflow-auto p-3">
        {runs.length ? (
          runs.map((run) => <RunTimeline key={run.id} run={run} />)
        ) : (
          <p className="text-xs text-muted-foreground">
            Describe a change, e.g. <span className="italic">“Add pump P-101 with start/stop buttons and a run indicator”</span>.
            Uploaded CSV/Excel IO lists are imported on the next request.
          </p>
        )}
      </div>
      <form onSubmit={submit} className="space-y-2 border-t p-3">
        <textarea
          value={prompt}
          onChange={(event) => setPrompt(event.target.value)}
          onKeyDown={onKeyDown}
          placeholder={connection === "open" ? "Ask the copilot…" : "Connecting…"}
          rows={3}
          maxLength={4000}
          aria-label="AI prompt"
          className="w-full resize-none rounded-md border border-input bg-transparent px-3 py-2 text-xs shadow-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
        />
        <Button type="submit" size="sm" className="w-full" disabled={disabled || !prompt.trim()}>
          {busy ? <Loader2 className="animate-spin" /> : <SendHorizontal />}
          {busy ? "Synthesizing…" : "Send"}
        </Button>
      </form>
    </div>
  );
}
