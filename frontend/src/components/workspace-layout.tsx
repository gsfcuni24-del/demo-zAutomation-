import type { ReactNode } from "react";

interface WorkspaceLayoutProps {
  header: ReactNode;
  left: ReactNode;
  center: ReactNode;
  right: ReactNode;
}

export function WorkspaceLayout({ header, left, center, right }: WorkspaceLayoutProps) {
  return (
    <div className="flex h-screen flex-col overflow-hidden">
      <header className="shrink-0 border-b bg-card/60 px-4 py-2">{header}</header>
      <div className="grid min-h-0 flex-1 grid-cols-[minmax(280px,22rem)_1fr_minmax(260px,20rem)]">
        <aside aria-label="Tag explorer" className="flex min-h-0 flex-col border-r bg-card/40">
          {left}
        </aside>
        <main aria-label="Canvas" className="min-h-0 overflow-auto">
          {center}
        </main>
        <aside aria-label="AI assistant" className="flex min-h-0 flex-col border-l bg-card/40">
          {right}
        </aside>
      </div>
    </div>
  );
}

interface PanelPlaceholderProps {
  title: string;
  subtitle: string;
  icon: ReactNode;
}

export function PanelPlaceholder({ title, subtitle, icon }: PanelPlaceholderProps) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-3 p-6 text-center text-muted-foreground">
      <div className="rounded-full border border-dashed p-4">{icon}</div>
      <p className="text-sm font-medium text-foreground/80">{title}</p>
      <p className="font-mono text-xs uppercase tracking-widest">{subtitle}</p>
    </div>
  );
}
