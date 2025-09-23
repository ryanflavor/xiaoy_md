# **7\. Core Workflows**

The primary workflow involves processing a market tick. The system is designed to be robust against backpressure (via bounded queues with a drop-and-log policy), serialization errors (via try/except blocks to prevent poison pills), and NATS publish failures (via an exponential backoff retry policy).

## **Workflow: Processing a Market Tick**

Code snippet

sequenceDiagram
    participant CTP_Gateway as vnpy CTP Gateway<br>(Child Process)
    participant CTP_Adapter as CTP Adapter<br>(Supervisor)
    participant Core_Service as Core App Service<br>(Async Loop)
    participant NATS_Adapter as NATS Publisher
    participant NATS_Cluster as NATS JetStream

    CTP_Gateway->>+CTP_Adapter: 1. on_tick(vnpy_tick)
    CTP_Adapter->>CTP_Adapter: 2. Translate to DomainTick
    CTP_Adapter-->>-Core_Service: 3. tick_queue.put(domain_tick)
    Core_Service->>+Core_Service: 4. Validate DomainTick
    Core_Service-->>-Core_Service: Validation OK
    Core_Service->>+NATS_Adapter: 5. publisher.publish(domain_tick)
    NATS_Adapter->>NATS_Adapter: 6. Serialize (JSON/Pickle)
    NATS_Adapter->>+NATS_Cluster: 7. js.publish(subject, data)
    NATS_Cluster-->>-NATS_Adapter: 8. Ack
    NATS_Adapter-->>-Core_Service: 9. Return Success

## **Workflow: Live Environment Orchestration**

Code snippet

sequenceDiagram
    participant Ops as Ops Engineer
    participant Runbook as start_live_env.sh
    participant Compose as Docker Compose
    participant NATS as NATS Cluster
    participant Service as Market Data Service
    participant Subs as Subscription Worker
    participant Prom as Prometheus

    Ops->>+Runbook: 1. Execute runbook (pre-market)
    Runbook->>+Compose: 2. docker compose up --profile live
    Compose->>+NATS: 3. Start NATS live profile
    Compose->>+Service: 4. Start market-data-service
    Runbook->>+Subs: 5. Launch full_feed_subscription.py
    Service->>Runbook: 6. Emit readiness / health log
    Runbook->>Prom: 7. Register job status metrics
    Runbook-->>-Ops: 8. Summarize success / errors

## **Workflow: Subscription Health Check & Recovery**

Code snippet

sequenceDiagram
    participant Scheduler as Cron/Scheduler
    participant Health as check_feed_health.py
    participant Service as Market Data Service
    participant Catalogue as Contract Catalogue
    participant Prom as Prometheus
    participant Ops as Ops Engineer

    Scheduler->>+Health: 1. Invoke health script
    Health->>+Service: 2. Fetch active subscription list
    Health->>Catalogue: 3. Retrieve expected contract universe
    Health->>Health: 4. Compare + detect gaps/latency issues
    Health->>Prom: 5. Push metrics / anomalies
    Prom->>Ops: 6. Fire Grafana alert (if thresholds breached)
    Ops->>Health: 7. Trigger remediation (resubscribe / escalate)
    Health-->>-Scheduler: 8. Exit code reflects status

> Implementation Note: `check_feed_health.py` relies on the control-plane subject `md.subscriptions.active` to obtain a live snapshot of subscription identifiers, last tick timestamps, and activity metadata before computing coverage and remediation actions.

## **Workflow: Feed Failover Drill**

Code snippet

sequenceDiagram
    participant Ops as Ops Engineer
    participant Runbook as start_live_env.sh (failover mode)
    participant Config as Config Registry
    participant Adapter as CTP Adapter
    participant Backup as Backup Feed
    participant Prom as Prometheus
    participant Consumers as Downstream Subscribers

    Ops->>+Runbook: 1. Invoke failover playbook
    Runbook->>Config: 2. Load backup credentials/profile
    Runbook->>Adapter: 3. Restart adapter with backup config
    Adapter->>Backup: 4. Establish new feed session
    Adapter->>Consumers: 5. Maintain outbound tick stream
    Prom->>Ops: 6. Monitor latency / drop indicators
    Ops-->>-Runbook: 7. Confirm stability & log drill outcome

---
