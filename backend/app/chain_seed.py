"""实时指标口径链演示数据。

口径链是新业务对象，不进 seed.py（那份是十八个旧模块的固定示例），
改为在 main 启动时按表幂等灌入，保证重启后链路上每一环都有数据可看。

表清单：
- metric_stream      数据源流记录（口径链读取的上游）
- stream_event       数据源流上的明细事件（窗口计算的输入）
- metric_version     不可变指标定义版本（草稿/评审中/已上线/已下线）
- metric_dataset     实时指标计算结果数据集（只追加，不覆盖）
- threshold_hit      阈值命中结果（只追加；指标下线后不再产生新命中）
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from app.store import store

# 口径链各表名，service / router 共用，避免字面量散落。
TABLE_STREAM = "metric_stream"
TABLE_EVENT = "stream_event"
TABLE_VERSION = "metric_version"
TABLE_DATASET = "metric_dataset"
TABLE_HIT = "threshold_hit"

# 参与定义指纹的口径要素：任何一项变化都会得到不同哈希。
DEFINITION_FIELDS = [
    "指标编号", "指标名称", "计算窗口秒", "聚合函数", "数据源流",
    "维度字段组", "精度位数", "延迟容忍毫秒", "度量字段",
]


def content_hash(definition: dict[str, Any]) -> str:
    """对口径要素做稳定哈希，作为不可变定义版本的指纹。"""
    payload = {field: definition.get(field) for field in DEFINITION_FIELDS}
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

STREAMS = [
    {
        "id": 1,
        "流编号": "STREAM-PAY",
        "流名称": "支付事件流",
        "事件类型": "payment",
        "维度字段": ["channel", "region"],
        "延迟容忍毫秒": 3000,
        "状态": "在线",
        "最近水位事件时间": "2026-11-16T09:58:00",
    },
    {
        "id": 2,
        "流编号": "STREAM-TRADE",
        "流名称": "订单事件流",
        "事件类型": "order",
        "维度字段": ["channel", "region"],
        "延迟容忍毫秒": 5000,
        "状态": "在线",
        "最近水位事件时间": "2026-11-16T09:58:00",
    },
]

# 指标定义版本：v1/v2 构成同一指标的新旧版本，用于演示并排差异；
# MDV-0004 是一条已下线版本，用来演示阈值版本失效后不再产生命中。
VERSIONS = [
    {
        "id": 1,
        "版本编号": "MDV-0001",
        "指标编号": "REAL-1001",
        "指标名称": "支付成功率",
        "版本序号": 1,
        "状态": "已上线",
        "计算窗口秒": 60,
        "聚合函数": "avg",
        "数据源流": "STREAM-PAY",
        "维度字段组": ["channel", "region"],
        "精度位数": 4,
        "延迟容忍毫秒": 3000,
        "度量字段": "success_ratio",
        "内容哈希": "",
        "上线时间": "2026-11-16T08:00:00",
        "失效时间": None,
        "上一版本编号": None,
        "变更说明": "首个发布版本",
        "校验结论": "计算窗口、数据源流、维度字段组、精度均校验通过",
        "不可变": True,
    },
    {
        "id": 2,
        "版本编号": "MDV-0002",
        "指标编号": "REAL-1001",
        "指标名称": "支付成功率",
        "版本序号": 2,
        "状态": "草稿",
        "计算窗口秒": 30,
        "聚合函数": "avg",
        "数据源流": "STREAM-PAY",
        "维度字段组": ["channel", "region"],
        "精度位数": 6,
        "延迟容忍毫秒": 3000,
        "度量字段": "success_ratio",
        "内容哈希": "",
        "上线时间": None,
        "失效时间": None,
        "上一版本编号": "MDV-0001",
        "变更说明": "窗口从 60 秒收窄到 30 秒，精度提升到 6 位",
        "校验结论": "",
        "不可变": False,
    },
    {
        "id": 3,
        "版本编号": "MDV-0003",
        "指标编号": "REAL-1002",
        "指标名称": "订单金额均值",
        "版本序号": 1,
        "状态": "已上线",
        "计算窗口秒": 120,
        "聚合函数": "avg",
        "数据源流": "STREAM-TRADE",
        "维度字段组": ["channel"],
        "精度位数": 2,
        "延迟容忍毫秒": 5000,
        "度量字段": "order_amount",
        "内容哈希": "",
        "上线时间": "2026-11-16T08:10:00",
        "失效时间": None,
        "上一版本编号": None,
        "变更说明": "首个发布版本",
        "校验结论": "计算窗口、数据源流、维度字段组、精度均校验通过",
        "不可变": True,
    },
    {
        "id": 4,
        "版本编号": "MDV-0004",
        "指标编号": "REAL-1003",
        "指标名称": "支付笔数",
        "版本序号": 1,
        "状态": "已下线",
        "计算窗口秒": 60,
        "聚合函数": "count",
        "数据源流": "STREAM-PAY",
        "维度字段组": ["region"],
        "精度位数": 0,
        "延迟容忍毫秒": 3000,
        "度量字段": "event_id",
        "内容哈希": "",
        "上线时间": "2026-11-16T07:30:00",
        "失效时间": "2026-11-16T08:30:00",
        "上一版本编号": None,
        "变更说明": "口径合并到支付成功率指标，停止独立计算",
        "校验结论": "下线前发布校验通过",
        "不可变": True,
    },
]

# 阈值规则（落在旧模块 threshold 表上）：
# 绑定已上线版本的规则可继续判定；绑定已下线版本的规则被标记为版本失效。
THRESHOLDS = [
    {
        "id": 1001,
        "规则编号": "THRE-1001",
        "关联指标": "REAL-1001",
        "绑定版本编号": "MDV-0001",
        "绑定状态": "版本有效",
        "阈值下限": 0.95,
        "阈值上限": 1.0,
        "触发条件": "当前值低于下限",
        "持续周期": "1个窗口",
        "告警等级": "P1",
        "生效时间范围": "2026-11-16",
        "status": "已生效",
        "pending": False,
        "abnormal": False,
    },
    {
        "id": 1002,
        "规则编号": "THRE-1002",
        "关联指标": "REAL-1003",
        "绑定版本编号": "MDV-0004",
        "绑定状态": "版本失效",
        "阈值下限": 10.0,
        "阈值上限": None,
        "触发条件": "当前值低于下限",
        "持续周期": "1个窗口",
        "告警等级": "P2",
        "生效时间范围": "2026-11-16",
        "status": "已生效",
        "pending": False,
        "abnormal": True,
    },
    {
        "id": 1003,
        "规则编号": "THRE-1003",
        "关联指标": "REAL-1002",
        "绑定版本编号": None,
        "绑定状态": "未绑定",
        "阈值下限": 20.0,
        "阈值上限": 300.0,
        "触发条件": "超出上下限",
        "持续周期": "2个窗口",
        "告警等级": "P3",
        "生效时间范围": "2026-11-16",
        "status": "草稿",
        "pending": True,
        "abnormal": False,
    },
]


def _event_rows() -> list[dict[str, Any]]:
    """按固定规则生成流事件，避免随机数让计算结果每次启动都变。

    每分钟每流每维度组合一条事件，覆盖最近 40 分钟，窗口与覆盖率因此可复算。
    """
    events: list[dict[str, Any]] = []
    base_minute = 9 * 60 + 20  # 09:20 起，到 09:59 共 40 分钟
    for idx, minute in enumerate(range(base_minute, base_minute + 40)):
        hour, minute_of_hour = divmod(minute, 60)
        ts = f"2026-11-16T{hour:02d}:{minute_of_hour:02d}:00"
        for channel in ("app", "web"):
            for region in ("cn", "us"):
                # 支付流：成功率在 0.90~0.999 之间波动，制造少量阈值命中。
                ratio = round(0.90 + ((idx + hash((channel, region))) % 10) / 100.0, 4)
                events.append({
                    "id": len(events) + 1,
                    "流编号": "STREAM-PAY",
                    "事件时间": ts,
                    "维度": {"channel": channel, "region": region},
                    "度量值": {"success_ratio": ratio, "event_id": float(len(events) + 1)},
                })
                # 订单流：金额随维度和分钟变化。
                amount = round(50.0 + ((idx * 7 + hash((channel, region))) % 400) + idx * 0.5, 2)
                events.append({
                    "id": len(events) + 1,
                    "流编号": "STREAM-TRADE",
                    "事件时间": ts,
                    "维度": {"channel": channel, "region": region},
                    "度量值": {"order_amount": amount},
                })
    return events


def seed_chain_tables() -> None:
    """启动时幂等灌入口径链演示数据；已有数据时完全不动，保护只追加数据集。"""
    # 种子版本只声明口径要素，指纹统一按口径哈希回填，避免手写哈希与内容漂移。
    for version in VERSIONS:
        if not version.get("内容哈希"):
            version["内容哈希"] = content_hash(version)
    store.ensure_table(TABLE_STREAM, STREAMS)
    store.ensure_table(TABLE_EVENT, _event_rows())
    store.ensure_table(TABLE_VERSION, VERSIONS)
    store.ensure_table(TABLE_DATASET, [])
    store.ensure_table(TABLE_HIT, [])

    threshold_rows = store.rows("threshold")
    existing_bindings = {row.get("规则编号") for row in threshold_rows}
    version_by_code = {row["版本编号"]: row for row in store.rows(TABLE_VERSION)}
    for row in THRESHOLDS:
        if row["规则编号"] in existing_bindings:
            continue
        bound = version_by_code.get(row["绑定版本编号"]) if row.get("绑定版本编号") else None
        if bound is not None:
            row["绑定版本哈希"] = bound["内容哈希"]
        threshold_rows.append(dict(row))
