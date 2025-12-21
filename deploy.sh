#!/bin/bash

export DOCKER_HOST=ssh://choujs@192.168.1.54

# 部署脚本，包含错误检查机制

echo "开始部署应用..."

# 停止并移除现有的容器
echo "停止并移除现有容器..."
docker compose down
if [ $? -ne 0 ]; then
    echo "错误：停止容器失败"
    exit 1
fi

# 构建并启动新的容器
echo "构建并启动容器..."
docker compose up -d --build
if [ $? -ne 0 ]; then
    echo "错误：启动容器失败"
    exit 1
fi

echo "应用部署成功！"

docker image prune -f