export const en = {
  nav: {
    overview: "Overview",
    drillControl: "Drill Control",
    subscriptionHealth: "Subscription Health",
    auditTimeline: "Audit Timeline",
  },
  sections: {
    overview: "Operations Overview",
    metrics: "Live Metrics",
    actions: "Runbook Actions",
    drill: "Failover Drill",
    health: "Subscription Health",
    audit: "Audit Ledger",
  },
} as const;

export type EnTranslations = typeof en;
