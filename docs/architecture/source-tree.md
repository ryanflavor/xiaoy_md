# **10\. Source Tree**

The project directory will be structured to clearly reflect the Hexagonal Architecture.

Plaintext

market-data-service/
├── .github/
│   └── workflows/
│       └── ci.yml
├── docs/
├── src/
│   ├── infrastructure/
│   │   ├── ctp\_adapter.py
│   │   ├── nats\_publisher.py
│   │   └── serializers.py
│   ├── domain/
│   │   ├── models.py
│   │   └── ports.py
│   ├── application/
│   │   └── services.py
│   ├── config.py
│   └── \_\_main\_\_.py
├── ui/
│   └── operations-console/
│       ├── package.json
│       ├── vite.config.ts
│       ├── tsconfig.json
│       ├── src/
│       │   ├── app/
│       │   │   ├── App.tsx
│       │   │   └── routes.tsx
│       │   ├── components/
│       │   │   ├── ActionPanel.tsx
│       │   │   ├── HealthStatCard.tsx
│       │   │   ├── MetricChart.tsx
│       │   │   └── index.ts
│       │   ├── pages/
│       │   │   ├── OverviewPage.tsx
│       │   │   ├── DrillControlPage.tsx
│       │   │   ├── SubscriptionHealthPage.tsx
│       │   │   └── AuditTimelinePage.tsx
│       │   ├── hooks/
│       │   ├── services/
│       │   │   ├── apiClient.ts
│       │   │   └── telemetry.ts
│       │   ├── stores/
│       │   │   └── sessionStore.ts
│       │   ├── styles/
│       │   │   ├── tokens.ts
│       │   │   └── index.css
│       │   └── i18n/
│       │       ├── en.json
│       │       └── zh.json
│       └── tests/
│           ├── components/
│           ├── fixtures/
│           │   ├── metrics-summary.json
│           │   └── runbook-status.json
│           ├── integration/
│           │   └── overview.spec.tsx
│           └── playwright.config.ts
├── tests/
│   ├── integration/
│   └── unit/
├── .dockerignore
├── docker-compose.yml
├── Dockerfile
├── pyproject.toml
└── README.md

---
