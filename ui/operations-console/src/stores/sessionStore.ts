import { create } from "zustand";

type SessionWindow = "day" | "night";

type EnvironmentMode = "live" | "mock" | "unknown";

type Profile = "primary" | "backup" | "unknown";

type SessionState = {
  sessionWindow: SessionWindow;
  environmentMode: EnvironmentMode;
  activeProfile: Profile;
  setSessionWindow: (window: SessionWindow) => void;
  setEnvironmentMode: (mode: EnvironmentMode) => void;
  setActiveProfile: (profile: Profile) => void;
};

export const useSessionStore = create<SessionState>((set) => ({
  sessionWindow: "day",
  environmentMode: "unknown",
  activeProfile: "unknown",
  setSessionWindow: (sessionWindow) => set({ sessionWindow }),
  setEnvironmentMode: (environmentMode) => set({ environmentMode }),
  setActiveProfile: (activeProfile) => set({ activeProfile }),
}));
