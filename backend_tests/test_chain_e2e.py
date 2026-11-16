"""口径链端到端验证：通过 HTTP 跑通完整业务链路，断言每条硬性要求。

运行：python3 -I /workspace/backend_tests/test_chain_e2e.py
仅依赖标准库，服务地址默认 http://127.0.0.1:8000。
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8000"
PASS = 0
FAILURES: list[str] = []


def call(method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        BASE + path, data=data, method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8")
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, {"ok": False, "message": f"HTTP {exc.code}: {raw[:200]}"}


def check(name: str, condition: bool, detail: str = "") -> None:
    global PASS
    if condition:
        PASS += 1
        print(f"  ✓ {name}")
    else:
        FAILURES.append(f"{name} {detail}")
        print(f"  ✗ {name} {detail}")


def section(title: str) -> None:
    print(f"\n== {title} ==")


# 1. 数据源流与不可变版本
section("数据源流与不可变定义版本")
_, streams = call("GET", "/api/realtimemetric/chain/streams")
check("读取数据源流记录", streams["total"] >= 2)
_, versions_page = call("GET", "/api/realtimemetric/chain/versions")
versions = versions_page["items"]
check("存在 4 个定义版本", len(versions) == 4, str(len(versions)))
online = [v for v in versions if v["状态"] == "已上线"]
check("已上线版本标记不可变且带内容哈希", all(v["不可变"] and v["内容哈希"] for v in online))

# 2. 生命周期单向相邻、不可倒回
section("生命周期单向流转")
status, result = call("POST", "/api/realtimemetric/chain/versions/MDV-0001/actions", {"values": {"action": "提交评审"}})
check("已上线版本不能倒回评审", result["ok"] is False and "单向" in result["message"], result.get("message", ""))
status, result = call("POST", "/api/realtimemetric/chain/versions/MDV-0002/actions", {"values": {"action": "下线指标"}})
check("草稿不能跳步下线", result["ok"] is False and "单向" in result["message"], result.get("message", ""))
status, result = call("POST", "/api/realtimemetric/chain/versions/MDV-0002/actions", {"values": {"action": "发布上线"}})
check("草稿不能跳步上线", result["ok"] is False)

# 3. 草稿 -> 评审（冻结）-> 上线（发布校验 + 旧版本失效）
section("发布校验与新旧版本冲突取舍")
status, result = call("POST", "/api/realtimemetric/chain/versions/MDV-0002/actions", {"values": {"action": "提交评审"}})
check("草稿提交评审成功并冻结", result["ok"] and result["entry"]["不可变"] is True, result.get("message", ""))
status, result = call("POST", "/api/realtimemetric/chain/versions/MDV-0002/actions", {"values": {"action": "发布上线"}})
check("评审版本发布上线通过校验", result["ok"], result.get("message", ""))
_, page = call("GET", "/api/realtimemetric/chain/versions?metric_code=REAL-1001")
v1 = next(v for v in page["items"] if v["版本编号"] == "MDV-0001")
v2 = next(v for v in page["items"] if v["版本编号"] == "MDV-0002")
check("旧上线版本同步置为已下线且带失效时间", v1["状态"] == "已下线" and v1["失效时间"], json.dumps(v1, ensure_ascii=False))
check("新版本处于已上线", v2["状态"] == "已上线" and v2["上线时间"])
check("旧版本历史记录未被改写（哈希保留）", bool(v1["内容哈希"]))

# 4. 新建草稿的发布校验失败路径
section("发布校验拦截非法口径")
status, result = call("POST", "/api/realtimemetric/chain/versions", {"values": {
    "指标编号": "REAL-BAD", "指标名称": "坏口径", "计算窗口秒": 0,
    "聚合函数": "median", "数据源流": "STREAM-PAY",
    "维度字段组": ["not_exist"], "精度位数": 3,
}})
check("非法窗口/聚合/维度在登记阶段被拦", result["ok"] is False, result.get("message", ""))
status, result = call("POST", "/api/realtimemetric/chain/versions", {"values": {
    "指标编号": "REAL-1004", "指标名称": "支付总额", "计算窗口秒": 60,
    "聚合函数": "sum", "数据源流": "STREAM-PAY",
    "维度字段组": ["channel"], "精度位数": 2, "度量字段": "success_ratio",
}})
check("合法草稿登记成功", result["ok"], result.get("message", ""))
bad_code = result["entry"]["版本编号"]
call("POST", f"/api/realtimemetric/chain/versions/{bad_code}/actions", {"values": {"action": "提交评审"}})
# 人为构造口径冲突：相同口径重复发布（直接再登记一份同口径草稿再推到上线）
status, dup = call("POST", "/api/realtimemetric/chain/versions", {"values": {
    "指标编号": "REAL-1004", "指标名称": "支付总额", "计算窗口秒": 60,
    "聚合函数": "sum", "数据源流": "STREAM-PAY",
    "维度字段组": ["channel"], "精度位数": 2, "度量字段": "success_ratio",
}})
dup_code = dup["entry"]["版本编号"]
call("POST", f"/api/realtimemetric/chain/versions/{dup_code}/actions", {"values": {"action": "提交评审"}})
status, first_pub = call("POST", f"/api/realtimemetric/chain/versions/{bad_code}/actions", {"values": {"action": "发布上线"}})
check("首份同口径版本可上线", first_pub["ok"], first_pub.get("message", ""))
status, second_pub = call("POST", f"/api/realtimemetric/chain/versions/{dup_code}/actions", {"values": {"action": "发布上线"}})
check("相同口径指纹重复发布被拦截", second_pub["ok"] is False and "指纹" in second_pub["message"], second_pub.get("message", ""))

# 5. 窗口计算：数据集、新鲜度、覆盖率
section("窗口计算与结果数据集")
status, compute1 = call("POST", "/api/realtimemetric/chain/compute", {"values": {"版本编号": "MDV-0002"}})
check("已上线版本驱动计算成功", compute1["ok"], compute1.get("message", ""))
entry1 = compute1["entry"]
# 30 秒窗口下事件只落在整分钟：约一半完整窗口有数据，覆盖率如实呈现缺口且可追溯。
check("结果携带窗口覆盖率（整分钟事件对 30 秒窗口呈现缺口）", 0 < entry1["窗口覆盖率"] <= 1.0, str(entry1))
check("结果携带数据新鲜度（非负整数秒）", isinstance(entry1["数据新鲜度秒"], int) and entry1["数据新鲜度秒"] >= 0)
check("本次新增窗口数大于 0", entry1["本次新增窗口"] > 0)
_, dataset1 = call("GET", "/api/realtimemetric/chain/dataset?version_code=MDV-0002&size=10000")
check("数据集每行带新鲜度/覆盖率/定义哈希", all(
    row["数据新鲜度秒"] is not None and "窗口覆盖率" in row and row["定义内容哈希"] == v2["内容哈希"]
    for row in dataset1["items"]
))
check("覆盖率缺口可追溯（覆盖窗口数小于应覆盖窗口数）", dataset1["items"] and all(
    row["覆盖窗口数"] < row["应覆盖窗口数"] for row in dataset1["items"]
))
first_rows = {row["id"]: dict(row) for row in dataset1["items"]}

# 6. 中断恢复：再次计算只能追加/跳过，不覆盖已可用数据集
section("中断恢复与只追加数据集")
status, compute2 = call("POST", "/api/realtimemetric/chain/compute", {"values": {"版本编号": "MDV-0002"}})
entry2 = compute2["entry"]
check("二次计算新增窗口为 0（从上一完整窗口继续）", entry2["本次新增窗口"] == 0, str(entry2))
check("二次计算跳过已存在窗口", entry2["跳过已存在窗口"] > 0)
_, dataset2 = call("GET", "/api/realtimemetric/chain/dataset?version_code=MDV-0002&size=10000")
check("数据集总量不变且旧行内容未被改写", dataset2["total"] == dataset1["total"] and all(
    first_rows[row["id"]]["指标值"] == row["指标值"]
    and first_rows[row["id"]]["写入时间"] == row["写入时间"]
    for row in dataset2["items"]
))

# 非上线版本不能计算
status, result = call("POST", "/api/realtimemetric/chain/compute", {"values": {"版本编号": "MDV-0004"}})
check("已下线版本不能驱动计算", result["ok"] is False and "已上线" in result["message"], result.get("message", ""))

# 7. 阈值版本绑定边界
section("阈值规则版本绑定边界")
status, result = call("POST", "/api/threshold/1003/bind-version", {"values": {"版本编号": "MDV-0004"}})
check("不能绑定已下线版本", result["ok"] is False and "已上线" in result["message"], result.get("message", ""))
status, result = call("POST", "/api/threshold/1003/bind-version", {"values": {"版本编号": "MDV-0002"}})
check("跨指标绑定被拒绝（REAL-1002 规则不能绑 REAL-1001 版本）", result["ok"] is False and "不一致" in result["message"], result.get("message", ""))
status, result = call("POST", "/api/threshold/1003/bind-version", {"values": {"版本编号": "MDV-0003"}})
check("可绑定同指标已上线版本并记录指纹", result["ok"] and result["entry"]["绑定版本哈希"], result.get("message", ""))
# 规则走完自身审批流后才参与阈值判定。
call("POST", "/api/threshold/1003/actions", {"values": {"action": "提交规则评审"}})
call("POST", "/api/threshold/1003/actions", {"values": {"action": "生效规则"}})

# 8. 阈值同步消费数据集 + 命中只追加
section("阈值管理同步消费与命中")
status, compute3 = call("POST", "/api/realtimemetric/chain/compute", {"values": {"版本编号": "MDV-0003"}})
check("订单指标计算成功", compute3["ok"], compute3.get("message", ""))
check("120 秒窗口对齐整分钟事件，覆盖率为 1.0", compute3["entry"]["窗口覆盖率"] == 1.0, str(compute3["entry"]))
_, bindings = call("GET", "/api/threshold/bindings")
synced = {b["规则编号"]: b for b in bindings["items"]}
check("阈值清单随版本同步更新（回写同步标记）", synced["THRE-1003"]["最近同步版本"] == "MDV-0003", json.dumps(synced["THRE-1003"], ensure_ascii=False))
check("失效绑定在清单中可追溯", synced["THRE-1002"]["绑定状态"] == "版本失效" and synced["THRE-1002"]["版本当前状态"] == "已下线")
_, hits1 = call("GET", "/api/realtimemetric/chain/hits?size=10000")
check("已产生阈值命中且携带版本与新鲜度", hits1["total"] > 0 and all(
    h["绑定版本编号"] and h["数据新鲜度秒"] is not None for h in hits1["items"]
))
check("失效版本规则未产生新命中", all(h["绑定版本编号"] != "MDV-0004" for h in hits1["items"]))
call("POST", "/api/realtimemetric/chain/compute", {"values": {"版本编号": "MDV-0003"}})
_, hits2 = call("GET", "/api/realtimemetric/chain/hits?size=10000")
check("命中表只追加（重算不重复生成）", hits2["total"] == hits1["total"])

# 9. 下线联动：关联告警停止产生新命中，旧命中保留
section("指标下线联动告警停止")
call("POST", "/api/realtimemetric/chain/versions/MDV-0002/actions", {"values": {"action": "下线指标"}})
_, v2_after = call("GET", "/api/realtimemetric/chain/versions/MDV-0002")
check("版本已下线且不可变", v2_after["状态"] == "已下线" and v2_after["不可变"] is True)
_, bindings_after = call("GET", "/api/threshold/bindings")
b1001 = next(b for b in bindings_after["items"] if b["规则编号"] == "THRE-1001")
check("关联阈值规则标记版本失效", b1001["绑定状态"] == "版本失效")
_, hits3 = call("GET", "/api/realtimemetric/chain/hits?size=10000")
check("旧阈值命中保留不被改写", hits3["total"] == hits1["total"])
status, result = call("POST", "/api/realtimemetric/chain/compute", {"values": {"版本编号": "MDV-0002"}})
check("下线后计算链路拒绝执行", result["ok"] is False)

# 10. 大盘刷新显示版本与新鲜度
section("大盘刷新版本与新鲜度")
_, refresh = call("GET", "/api/realtimemetric/chain/dashboard-refresh")
check("大盘卡片显式携带所用指标版本", all(c["所用指标版本"] for c in refresh["卡片"]))
check("大盘卡片显式携带数据新鲜度", all("数据新鲜度秒" in c for c in refresh["卡片"]))
check("大盘只呈现已上线版本", all(c["所用指标版本"] != "MDV-0002" for c in refresh["卡片"]))

# 11. 发布详情与并排差异
section("发布详情与并排差异视图")
_, detail = call("GET", "/api/realtimemetric/chain/versions/MDV-0002/publish-detail")
check("发布详情列出版本/窗口/新鲜度/覆盖率", all(
    key in detail for key in ("版本编号", "计算窗口秒", "数据新鲜度", "窗口覆盖率", "内容哈希")
))
_, diff = call("GET", "/api/realtimemetric/chain/diff?left=MDV-0001&right=MDV-0002")
check("并排差异列出窗口与精度变化", any(
    d["字段"] == "计算窗口秒" and d["旧版本"] == 60 and d["新版本"] == 30 for d in diff["差异项"]
) and any(d["字段"] == "精度位数" for d in diff["差异项"]))

# 12. 旧模块状态机收紧 + export 路由修复
section("旧实时指标模块单向状态机与导出")
status, result = call("POST", "/api/realtimemetric/1/actions", {"values": {"action": "上线指标"}})
check("旧模块草稿不能跳步上线", result["ok"] is False and "单向" in result["message"], result.get("message", ""))
status, legacy_export = call("GET", "/api/realtimemetric/export")
check("实时指标导出路由可用", status == 200 and legacy_export["total"] >= 3)
status, threshold_export = call("GET", "/api/threshold/export")
check("阈值导出路由可用", status == 200 and threshold_export["total"] >= 3)

print(f"\n通过 {PASS} 项，失败 {len(FAILURES)} 项")
if FAILURES:
    print("\n失败明细：")
    for item in FAILURES:
        print(" -", item)
    sys.exit(1)
print("全部口径链验证通过")
