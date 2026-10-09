import { create } from "zustand";

import type { ProjectRead } from "@/types/api";

interface ProjectState {
  activeProject: ProjectRead | null;
  setActiveProject: (project: ProjectRead | null) => void;
}

export const useProjectStore = create<ProjectState>()((set) => ({
  activeProject: null,
  setActiveProject: (project) => set({ activeProject: project }),
}));
