// Mirrors backend/app/ai/orchestrator.py (SynthesisEvent)
export const SYNTHESIS_AGENTS = [
  "orchestrator",
  "excel_parser",
  "tag_namer",
  "standards_retriever",
  "logic_drafter",
  "hmi_layouter",
  "uir_merge",
  "safety_auditor",
  "vendor_compiler",
  "diff_engine",
] as const;
export type SynthesisAgent = (typeof SYNTHESIS_AGENTS)[number];

export const SYNTHESIS_STATUSES = ["connected", "started", "completed", "retry", "failed"] as const;
export type SynthesisStatus = (typeof SYNTHESIS_STATUSES)[number];

export interface SynthesisEvent {
  agent: SynthesisAgent;
  status: SynthesisStatus;
  message: string;
  attempt: number | null;
  data: Record<string, unknown> | null;
  timestamp: string;
}

export interface SynthesisRequest {
  prompt: string;
  file_id?: string | null;
}
