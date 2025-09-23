import { NavLink } from "react-router-dom";
import clsx from "clsx";
import { en } from "@/i18n/en";
import { zh } from "@/i18n/zh";
import { useSessionStore } from "@/stores/sessionStore";

const navigation = [
  { path: "/", key: "overview" },
  { path: "/drill", key: "drillControl" },
  { path: "/health", key: "subscriptionHealth" },
  { path: "/audit", key: "auditTimeline" },
];

export function Layout({ children }: { children: React.ReactNode }) {
  const { sessionWindow, setSessionWindow, environmentMode, activeProfile } =
    useSessionStore();

  return (
    <div className="min-h-screen bg-background text-neutral-100">
      <div className="flex">
        <aside className="hidden min-h-screen w-64 flex-col border-r border-surface bg-surface/80 px-6 py-8 shadow-card md:flex">
          <h1 className="text-xl font-semibold text-neutral-100">Ops Console</h1>
          <p className="mt-1 text-sm text-neutral-400">运维控制台</p>
          <nav className="mt-8 flex flex-col gap-2 text-sm font-medium">
            {navigation.map((item) => (
              <NavLink
                key={item.key}
                to={item.path}
                className={({ isActive }) =>
                  clsx(
                    "rounded-lg px-3 py-2 transition",
                    isActive
                      ? "bg-primary/15 text-primary"
                      : "text-neutral-400 hover:bg-surface hover:text-neutral-100"
                  )
                }
              >
                {en.nav[item.key as keyof typeof en.nav]} / {zh.nav[item.key as keyof typeof zh.nav]}
              </NavLink>
            ))}
          </nav>
        </aside>
        <main className="flex-1">
          <header className="flex flex-wrap items-center justify-between gap-3 border-b border-surface bg-background/80 px-6 py-5">
            <div className="text-sm text-neutral-400">
              Mode: <span className="text-neutral-100">{environmentMode}</span>
              <span className="mx-2">•</span>
              Profile: <span className="text-neutral-100">{activeProfile}</span>
            </div>
            <div className="flex items-center gap-2 text-sm">
              <label htmlFor="session-window" className="text-neutral-300">
                Session Window / 交易时段
              </label>
              <select
                id="session-window"
                className="rounded-md border border-surface bg-surface px-3 py-1 text-neutral-100"
                value={sessionWindow}
                onChange={(event) =>
                  setSessionWindow(event.target.value as "day" | "night")
                }
              >
                <option value="day">Day / 日盘</option>
                <option value="night">Night / 夜盘</option>
              </select>
            </div>
          </header>
          <div className="px-6 py-8">{children}</div>
        </main>
      </div>
    </div>
  );
}
