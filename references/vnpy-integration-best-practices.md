# vnpy 集成最佳实践

## 问题背景
vnpy 是完整的交易系统，非异步库设计：
- 自有事件循环 (EventEngine)
- 同步架构，独立线程运行
- 事件直接发布，绕过适配器层

## 解决方案：run_in_executor 模式

### 架构设计
```python
class BaseGatewayAdapterAsync:
    def __init__(self):
        # 线程池运行 vnpy
        self.executor = ThreadPoolExecutor(max_workers=4)
        self._main_loop = None  # 存储主循环引用

    async def connect(self):
        # 在 executor 中初始化
        self.event_engine = await loop.run_in_executor(
            self.executor, self._init_event_engine_sync
        )

    def _handle_event_sync(self, event):
        # 线程安全传递到异步队列
        asyncio.run_coroutine_threadsafe(
            self.queue.put(event.data),
            self._main_loop
        )
```

### 关键配置
```python
# 正确的字段映射
setting = {
    "产品名称": config.app_id,      # "client_vntech_2.0"
    "授权编码": config.auth_code,   # "52TMMTN41F3KFR83"
}
```

### 实现要点
1. **线程隔离**：vnpy 在 ThreadPoolExecutor 中运行
2. **事件桥接**：用 `run_coroutine_threadsafe()` 跨线程通信
3. **循环引用**：保存主事件循环到 `_main_loop`
4. **Timer验证**：非交易时间用 Timer 事件验证连接

### 成果
- 代码减少 75% (2159→546行)
- 完整功能保留
- 异步接口 + 同步vnpy 完美结合

## 文件结构
```
infra/gateway/
├── base_gateway_adapter_async.py  # 异步基类
├── ctp_adapter_async.py          # CTP实现
└── tests/integration/
    └── test_async_adapter.py      # 集成测试
```

## 测试验证
```bash
cd apps/market-service
uv run python tests/integration/test_async_adapter.py
```

交易时间验证：
- ✅ 登录成功
- ✅ 接收19,882个合约
- ✅ 接收rb2510行情
- ✅ 账户查询正常
