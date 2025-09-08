# NATS 简单认证配置

## 认证方式：用户名/密码

本项目使用最简单的用户名密码认证方式，适合内部使用。

### 配置文件

**NATS服务器配置** (`config/nats-server.conf`)：
```
authorization {
  user: testuser
  password: testpass
  timeout: 1
}

jetstream: enabled
```

### 环境变量

**.env文件**：
```bash
# NATS认证凭证
NATS_USER=testuser
NATS_PASSWORD=testpass

# NATS配置
NATS_URL=nats://nats:4222
NATS_COMMAND=-c /etc/nats/nats-server.conf
```

### 使用方法

**Python客户端连接**：
```python
import nats

# 正确连接方式
nc = await nats.connect(
    "nats://testuser:testpass@localhost:4222"
)

# 或者分开指定
nc = await nats.connect(
    "nats://localhost:4222",
    user="testuser",
    password="testpass"
)
```

### Docker启动

```bash
# 启动服务
docker-compose up

# 检查状态
docker-compose ps
```

### 验证认证

```bash
# 测试连接（从容器内）
docker exec -it market-data-service python -c "
import asyncio, nats
async def test():
    nc = await nats.connect('nats://testuser:testpass@nats:4222')
    print('✅ 认证成功!')
    await nc.close()
asyncio.run(test())
"
```

### 修改认证信息

1. 修改 `config/nats-server.conf` 中的用户名密码
2. 修改 `.env` 文件中的 `NATS_USER` 和 `NATS_PASSWORD`
3. 重启服务：`docker-compose restart`

就这么简单！