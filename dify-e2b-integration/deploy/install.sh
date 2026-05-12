#!/bin/bash
# Dify Helm 部署脚本
# 使用前请确保 kubectl 和 helm 已配置好集群访问

set -e

# 添加 Helm repo
helm repo add dify https://borispolonsky.github.io/dify-helm
helm repo update

# 创建 namespace
kubectl create namespace dify --dry-run=client -o yaml | kubectl apply -f -

# 部署 Dify
helm install dify dify/dify \
  -n dify \
  -f values.yaml \
  --timeout 10m \
  --wait

echo ""
echo "=== Dify 部署完成 ==="
echo ""
echo "获取访问地址："
echo "  kubectl get svc -n dify dify-proxy"
echo ""
echo "等待所有 Pod 就绪："
echo "  kubectl get pods -n dify -w"
echo ""
echo "首次访问时需要注册管理员账号。"
