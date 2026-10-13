#!/bin/bash
# 监控消融实验测试进度

echo "========================================"
echo "XFAgent 消融实验测试监控"
echo "========================================"
echo ""

# 检查进程状态
if ps aux | grep "ablation_test_base64.py 200" | grep -v grep > /dev/null; then
    PID=$(ps aux | grep "ablation_test_base64.py 200" | grep -v grep | awk '{print $2}')
    echo "✓ 测试进程运行中 (PID: $PID)"
else
    echo "✗ 测试进程未运行"
fi

echo ""
echo "----------------------------------------"
echo "测试进度"
echo "----------------------------------------"

# 从日志中统计进度
if [ -f "/tmp/ablation_full_test_output.log" ]; then
    TOTAL=200
    COMPLETED=$(grep -c "场景.*/" /tmp/ablation_full_test_output.log 2>/dev/null || echo 0)
    SUCCESSFUL=$(grep -c "✓ 成功" /tmp/ablation_full_test_output.log 2>/dev/null || echo 0)
    FAILED=$(grep -c "✗ 失败" /tmp/ablation_full_test_output.log 2>/dev/null || echo 0)
    
    PROGRESS=$((COMPLETED * 100 / TOTAL))
    
    echo "总进度: $COMPLETED / $TOTAL ($PROGRESS%)"
    echo "成功: $SUCCESSFUL"
    echo "失败: $FAILED"
    
    # 预估剩余时间
    if [ $COMPLETED -gt 0 ]; then
        # 获取测试运行时间（秒）
        START_TIME=$(stat -c %Y /tmp/ablation_full_test_output.log 2>/dev/null)
        CURRENT_TIME=$(date +%s)
        ELAPSED=$((CURRENT_TIME - START_TIME))
        
        AVG_TIME=$((ELAPSED / COMPLETED))
        REMAINING=$((TOTAL - COMPLETED))
        ETA=$((REMAINING * AVG_TIME))
        ETA_MIN=$((ETA / 60))
        
        echo ""
        echo "平均速度: ${AVG_TIME}s/场景"
        echo "预计剩余时间: ${ETA_MIN} 分钟"
        echo "预计完成时间: $(date -d "+${ETA} seconds" '+%H:%M')"
    fi
else
    echo "日志文件未找到"
fi

echo ""
echo "----------------------------------------"
echo "最新测试结果（最后5条）"
echo "----------------------------------------"
tail -15 /tmp/ablation_full_test_output.log 2>/dev/null | grep -E "场景|✓|✗" | tail -5

echo ""
echo "========================================"
echo "监控命令:"
echo "  实时日志: tail -f /tmp/ablation_full_test_output.log"
echo "  刷新监控: bash tests/ablation/monitor_test.sh"
echo "========================================"
