#!/bin/bash
# hdl_compare 套件环境: 先 source 主工具链, 再加 HDL 生成语言工具
# 用法: source /fact_home/yiyangyuan/workspace/projects/hdl_compare/env.sh
source /fact_home/yiyangyuan/tools/env.sh

# swim + spade (Spade), scala-cli (Chisel 用系统 JDK 17)
export PATH=/fact_home/yiyangyuan/tools/cargo/bin:$PATH
# scala-cli 的依赖缓存放 ~/tools (登录/计算节点一致, 避免重复下载)
export COURSIER_CACHE=/fact_home/yiyangyuan/tools/coursier-cache
