export const zh = {
  nav: {
    overview: "总览",
    drillControl: "演练控制",
    subscriptionHealth: "订阅健康",
    auditTimeline: "审计时间线",
  },
  sections: {
    overview: "运维概览",
    metrics: "实时指标",
    actions: "Runbook 操作",
    drill: "故障演练",
    health: "订阅健康",
    audit: "审计日志",
  },
} as const;

export type ZhTranslations = typeof zh;
