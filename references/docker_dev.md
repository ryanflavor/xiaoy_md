  清理并重启集群

  在192.168.10.68上：
  # 停止并删除容器
  docker stop nats-node1
  docker rm nats-node1

  # 重新启动，明确指定单个路由
  docker run -d \
    --name nats-node1 \
    --restart always \
    -p 4222:4222 \
    -p 6222:6222 \
    -p 8222:8222 \
    nats:latest \
    -s -p 4222 \
    --cluster_name my_cluster \
    --cluster nats://0.0.0.0:6222 \
    --http_port 8222

  在192.168.10.238上：
  # 停止并删除容器
  docker stop nats-node2
  docker rm nats-node2

  # 重新启动，明确连接到node1
  docker run -d \
    --name nats-node2 \
    --restart always \
    -p 4222:4222 \
    -p 6222:6222 \
    -p 8222:8222 \
    nats:latest \
    -s -p 4222 \
    --cluster_name my_cluster \
    --cluster nats://0.0.0.0:6222 \
    --routes nats://192.168.10.68:6222 \
    --http_port 8222