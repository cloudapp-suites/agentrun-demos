#!/bin/bash
# 卸载 Dify
set -e

helm uninstall dify -n dify
echo "Dify 已卸载。PVC 数据保留，如需清理："
echo "  kubectl delete pvc --all -n dify"
echo "  kubectl delete namespace dify"
