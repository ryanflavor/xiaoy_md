# QA Operational Risk Note — start_live_env.sh Health Checks (2025-09-22)

## Summary
- 在 Story 3.1 复检过程中，运行 `./scripts/operations/start_live_env.sh` 出现 `Health check failed after 20s`，即便本地 `docker compose ps` 显示 NATS 容器处于 `Up ... (healthy)`。
- 原因：脚本 `start_nats()` 的探活命令为 `docker compose ps nats | grep -q running`，而新版 Docker Compose Status 列显示 `Up ... (healthy)`，不包含 `running` 字符串，导致探活永远失败。

## Impact
- **谁会受影响？** 运维脚本使用者（包括 CI、运维人员）会在实际服务正常时被迫看到超时错误，脚本立即退出，后续 market-data-service 及订阅进程也不会启动。
- **风险等级：高** — 运行脚本的环境可能并未真正故障，但运维人员会因为“假阳性”中断操作，造成全流程延迟，也可能在紧急切换时误判为系统宕机。

## Reproduction
1. 启动 docker compose profile 使 `nats` 容器进入 `Up ... (healthy)` 状态。
2. 运行 `./scripts/operations/start_live_env.sh --window day --profile live --log-dir logs/runbooks`。
3. 即使容器健康，也会输出 `Component: NATS, Status: TIMEOUT, Details: Health check failed after 20s`。

## Technical Detail
- 代码位置：`scripts/operations/start_live_env.sh:104-137`
  ```bash
  docker compose --profile "${PROFILE}" up -d nats
  if check_readiness "NATS" "docker compose ps nats | grep -q running" 20; then
      ...
  ```
- `check_readiness` 循环本身正常，但 `grep -q running` 在当前 compose 版本中永远返回非 0。

## Suggested Fix
- 将探活命令调整为匹配 `Up` 或使用格式化输出，例如：
  ```bash
  check_readiness "NATS" "docker compose ps --format '{{.State}}' nats | grep -q Up"
  ```
- 同时检查市场数据服务的健康检查是否需要类似调整（当前依赖 HTTP health endpoint，影响较小）。
- 更新 Runbook 说明，并在开发修复后安排回归测试。

## Follow-up
- 2025-09-22: 修改 `start_nats()`，采用 `docker compose ps --status running --services | grep -qx nats` 判断健康，脚本现已正确检测既有 NATS 实例。
- 后续回归时确认其他服务健康检查是否也需要相同处理。
