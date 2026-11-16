"""实时指标口径链核心业务规则。

一条可发布的口径链：
数据源流记录 -> 不可变指标定义版本 -> 发布校验 -> 窗口计算
-> 只追加的计算结果数据集（携带数据新鲜度与窗口覆盖率）
-> 阈值规则按版本绑定消费 -> 阈值命中（只追加）。

边界约定（业务取舍）：
1. 定义版本一旦进入评审即冻结内容，已上线/已下线版本完全不可变；要改口径只能新建草稿版本。
2. 状态只能沿 草稿 -> 评审中 -> 已上线 -> 已下线 单向相邻推进，不能跳步、不能倒回。
3. 同一指标编号同时只允许一个已上线版本；新版本上线时旧上线版本置为已下线（失效），
   其历史计算结果与已产生的阈值命中保持原样，不被改写。
4. 阈值规则只能绑定「已上线且未失效」的版本；版本下线后关联规则标记版本失效，
   不再产生新的阈值命中，旧命中保留。
5. 结果数据集只追加：恢复计算时从上一完整窗口的下一个窗口继续，已写入数据集不覆盖。
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from app.chain_seed import (
    TABLE_DATASET,
    TABLE_EVENT,
    TABLE_HIT,
    TABLE_STREAM,
    TABLE_VERSION,
    content_hash,
)
from app.store import store

STATUS_DRAFT = "草稿"
STATUS_REVIEW = "评审中"
STATUS_ONLINE = "已上线"
STATUS_OFFLINE = "已下线"
STATUS_ORDER = [STATUS_DRAFT, STATUS_REVIEW, STATUS_ONLINE, STATUS_OFFLINE]
ACTION_RULES = {
    "提交评审": STATUS_REVIEW,
    "发布上线": STATUS_ONLINE,
    "下线指标": STATUS_OFFLINE,
}
SUPPORTED_AGGREGATES = {"sum", "avg", "count", "max", "min"}


class ChainError(Exception):
    """口径链业务校验失败；路由层统一转成 ok=False 的动作结果。"""


def _now() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def _window_buckets(window_seconds: int) -> list[tuple[str, str, int]]:
    """按事件时间对齐窗口桶：返回 (桶起点, 桶终点, 桶序) 列表。"""
    events = sorted(store.rows(TABLE_EVENT), key=lambda row: str(row["事件时间"]))
    if not events:
        return []
    start = datetime.fromisoformat(str(events[0]["事件时间"]))
    end = datetime.fromisoformat(str(events[-1]["事件时间"]))
    span = int((end - start).total_seconds()) + 1
    buckets: list[tuple[str, str, int]] = []
    for index in range(0, span, window_seconds):
        bucket_start = start.timestamp() + index
        bucket_end = bucket_start + window_seconds
        buckets.append((
            datetime.fromtimestamp(bucket_start).isoformat(),
            datetime.fromtimestamp(bucket_end).isoformat(),
            index // window_seconds,
        ))
    return buckets


class MetricChainService:
    # ------------------------------------------------------------------ 版本查询
    def list_versions(
        self,
        *,
        metric_code: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(TABLE_VERSION)
        if metric_code:
            rows = [row for row in rows if metric_code in str(row.get("指标编号", ""))]
        if status:
            rows = [row for row in rows if row.get("状态") == status]
        rows = sorted(rows, key=lambda row: (str(row.get("指标编号")), int(row.get("版本序号", 0))))
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_version(self, version_code: str) -> dict[str, Any] | None:
        for row in store.rows(TABLE_VERSION):
            if row.get("版本编号") == version_code:
                return row
        return None

    def list_streams(self) -> list[dict[str, Any]]:
        return store.rows(TABLE_STREAM)

    # ------------------------------------------------------------------ 草稿与状态机
    def create_draft(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        required = ["指标编号", "指标名称", "计算窗口秒", "聚合函数", "数据源流", "维度字段组", "精度位数"]
        missing = [field for field in required if values.get(field) in (None, "", [])]
        if missing:
            return None, missing
        definition, error = self._normalize_definition(values)
        if error:
            raise ChainError(error)
        rows = store.rows(TABLE_VERSION)
        same_metric = [row for row in rows if row.get("指标编号") == definition["指标编号"]]
        next_seq = max((int(row.get("版本序号", 0)) for row in same_metric), default=0) + 1
        previous = next(
            (row["版本编号"] for row in sorted(same_metric, key=lambda item: int(item["版本序号"]))
             if row.get("状态") in (STATUS_ONLINE, STATUS_REVIEW)),
            None,
        )
        version = {
            "id": store.next_id(TABLE_VERSION),
            "版本编号": f"MDV-{store.next_id(TABLE_VERSION):04d}",
            "指标编号": definition["指标编号"],
            "指标名称": definition["指标名称"],
            "版本序号": next_seq,
            "状态": STATUS_DRAFT,
            "计算窗口秒": definition["计算窗口秒"],
            "聚合函数": definition["聚合函数"],
            "数据源流": definition["数据源流"],
            "维度字段组": definition["维度字段组"],
            "精度位数": definition["精度位数"],
            "延迟容忍毫秒": definition["延迟容忍毫秒"],
            "度量字段": definition["度量字段"],
            "内容哈希": content_hash(definition),
            "上线时间": None,
            "失效时间": None,
            "上一版本编号": previous,
            "变更说明": str(values.get("变更说明") or "新建草稿版本"),
            "校验结论": "",
            "不可变": False,
        }
        rows.append(version)
        return version, []

    def _normalize_definition(self, values: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
        try:
            window = int(values["计算窗口秒"])
            precision = int(values["精度位数"])
            latency = int(values.get("延迟容忍毫秒") or 0)
        except (TypeError, ValueError):
            return {}, "计算窗口秒、精度位数、延迟容忍毫秒必须是整数"
        if window <= 0:
            return {}, "计算窗口秒必须为正整数"
        if not 0 <= precision <= 10:
            return {}, "精度位数需在 0~10 之间"
        aggregate = str(values["聚合函数"]).strip()
        if aggregate not in SUPPORTED_AGGREGATES:
            return {}, f"聚合函数仅支持 {sorted(SUPPORTED_AGGREGATES)}"
        stream_code = str(values["数据源流"]).strip()
        stream = next((item for item in store.rows(TABLE_STREAM) if item["流编号"] == stream_code), None)
        if stream is None:
            return {}, f"数据源流 {stream_code} 不存在，无法发布口径"
        dimensions = values["维度字段组"]
        if isinstance(dimensions, str):
            dimensions = [part.strip() for part in dimensions.split(",") if part.strip()]
        if not isinstance(dimensions, list) or not dimensions:
            return {}, "维度字段组至少包含一个维度"
        unknown = [dim for dim in dimensions if dim not in stream["维度字段"]]
        if unknown:
            return {}, f"维度字段 {unknown} 不在数据源流 {stream_code} 的维度清单内"
        measure = str(values.get("度量字段") or "").strip()
        if not measure:
            # count 类指标允许不显式给度量字段，默认按事件计数。
            measure = "event_id" if aggregate == "count" else ""
            if not measure:
                return {}, "非 count 聚合必须指定度量字段"
        return {
            "指标编号": str(values["指标编号"]).strip(),
            "指标名称": str(values["指标名称"]).strip(),
            "计算窗口秒": window,
            "聚合函数": aggregate,
            "数据源流": stream_code,
            "维度字段组": dimensions,
            "精度位数": precision,
            "延迟容忍毫秒": latency,
            "度量字段": measure,
        }, None

    def transition(self, version_code: str, action: str) -> tuple[dict[str, Any] | None, str]:
        version = self.get_version(version_code)
        if version is None:
            return None, f"定义版本 {version_code} 不存在"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于口径链生命周期动作"
        target = ACTION_RULES[action]
        current_index = STATUS_ORDER.index(version["状态"])
        target_index = STATUS_ORDER.index(target)
        # 单向、相邻、不可倒回。
        if target_index != current_index + 1:
            return None, (
                f"生命周期只能单向逐段推进：当前「{version['状态']}」不能执行「{action}」，"
                f"合法顺序为 {' -> '.join(STATUS_ORDER)}"
            )
        if target == STATUS_REVIEW:
            # 进入评审即冻结：草稿是唯一可改口径的阶段。
            version["状态"] = STATUS_REVIEW
            version["不可变"] = True
            return version, f"版本 {version_code} 已提交评审，定义内容冻结"
        if target == STATUS_ONLINE:
            message = self._publish(version)
            return version, message
        # 下线
        version["状态"] = STATUS_OFFLINE
        version["失效时间"] = _now()
        self._invalidate_thresholds(version_code)
        return version, (
            f"版本 {version_code} 已下线，关联阈值停止产生新命中；"
            "历史告警与旧计算结果保持原样"
        )

    def _publish(self, version: dict[str, Any]) -> str:
        """发布校验：计算窗口、数据源流、维度字段组、精度全部通过才允许上线。"""
        definition, error = self._normalize_definition(version)
        if error:
            raise ChainError(f"发布校验未通过：{error}")
        # 与同指标已上线版本做口径冲突判定：口径完全相同则没有发布新版本的必要。
        for other in store.rows(TABLE_VERSION):
            if (
                other["id"] != version["id"]
                and other.get("指标编号") == version["指标编号"]
                and other.get("状态") == STATUS_ONLINE
            ):
                if other.get("内容哈希") == content_hash(definition):
                    raise ChainError(
                        f"与已上线版本 {other['版本编号']} 口径指纹完全一致，"
                        "请勿重复发布相同定义"
                    )
        version["内容哈希"] = content_hash(definition)
        version["校验结论"] = "计算窗口、数据源流、维度字段组、精度均校验通过"
        version["状态"] = STATUS_ONLINE
        version["上线时间"] = _now()
        version["不可变"] = True
        superseded: list[str] = []
        for other in store.rows(TABLE_VERSION):
            if (
                other["id"] != version["id"]
            and other.get("指标编号") == version["指标编号"]
            and other.get("状态") == STATUS_ONLINE
            ):
                # 新旧定义版本冲突时的取舍：同一指标只保留一个在线版本，
                # 旧版本置失效但记录保留，阈值仍可追溯到它所绑定的完整定义版本。
                other["状态"] = STATUS_OFFLINE
                other["失效时间"] = _now()
                superseded.append(str(other["版本编号"]))
                self._invalidate_thresholds(str(other["版本编号"]))
        if superseded:
            return (
                f"版本 {version['版本编号']} 已上线并通过发布校验；旧版本 {('、'.join(superseded))} "
                "同步失效，其阈值绑定保留可追溯但不再产生新命中"
            )
        return f"版本 {version['版本编号']} 已上线并通过发布校验，口径链可发布"

    def _invalidate_thresholds(self, version_code: str) -> None:
        for row in store.rows("threshold"):
            if row.get("绑定版本编号") == version_code and row.get("status") != "已关闭":
                row["绑定状态"] = "版本失效"
                row["abnormal"] = True

    # ------------------------------------------------------------------ 差异与发布详情
    def diff_versions(self, left_code: str, right_code: str) -> dict[str, Any]:
        left = self.get_version(left_code)
        right = self.get_version(right_code)
        if left is None or right is None:
            raise ChainError("并排差异需要两个都存在的定义版本")
        compare_fields = [
            "指标名称", "计算窗口秒", "聚合函数", "数据源流",
            "维度字段组", "精度位数", "延迟容忍毫秒", "度量字段", "状态", "内容哈希",
        ]
        changes = []
        for field in compare_fields:
            old_value = left.get(field)
            new_value = right.get(field)
            if old_value != new_value:
                changes.append({"字段": field, "旧版本": old_value, "新版本": new_value})
        return {
            "左版本": left,
            "右版本": right,
            "差异项": changes,
            "一致": len(changes) == 0,
        }

    def publish_detail(self, version_code: str) -> dict[str, Any]:
        version = self.get_version(version_code)
        if version is None:
            raise ChainError(f"定义版本 {version_code} 不存在")
        dataset = [
            row for row in store.rows(TABLE_DATASET)
            if row.get("版本编号") == version_code
        ]
        latest = dataset[-1] if dataset else None
        return {
            "版本编号": version["版本编号"],
            "指标编号": version["指标编号"],
            "指标名称": version["指标名称"],
            "状态": version["状态"],
            "计算窗口秒": version["计算窗口秒"],
            "聚合函数": version["聚合函数"],
            "数据源流": version["数据源流"],
            "维度字段组": version["维度字段组"],
            "精度位数": version["精度位数"],
            "内容哈希": version["内容哈希"],
            "上线时间": version["上线时间"],
            "失效时间": version["失效时间"],
            "校验结论": version["校验结论"],
            "数据新鲜度": latest.get("数据新鲜度秒") if latest else None,
            "最近窗口起点": latest.get("窗口起点") if latest else None,
            "数据集版本号": latest.get("数据集版本号") if latest else None,
            "窗口覆盖率": latest.get("窗口覆盖率") if latest else None,
            "已写入窗口数": len(dataset),
        }

    # ------------------------------------------------------------------ 窗口计算与数据集
    def compute(self, version_code: str) -> dict[str, Any]:
        version = self.get_version(version_code)
        if version is None:
            raise ChainError(f"定义版本 {version_code} 不存在")
        if version["状态"] != STATUS_ONLINE:
            raise ChainError(
                f"版本 {version_code} 当前为「{version['状态']}」，"
                "只有已上线版本才能驱动口径链计算"
            )
        stream_code = str(version["数据源流"])
        stream = next((item for item in store.rows(TABLE_STREAM) if item["流编号"] == stream_code), None)
        if stream is None:
            raise ChainError(f"数据源流 {stream_code} 已不存在，口径链中断")
        events = [
            row for row in store.rows(TABLE_EVENT)
            if row.get("流编号") == stream_code
        ]
        if not events:
            raise ChainError(f"数据源流 {stream_code} 暂无事件记录，无法计算窗口")

        dimensions = list(version["维度字段组"])
        measure = str(version["度量字段"])
        aggregate = str(version["聚合函数"])
        precision = int(version["精度位数"])
        window_seconds = int(version["计算窗口秒"])
        dataset_rows = store.rows(TABLE_DATASET)

        # 恢复点：上一完整窗口。重算时跳过已存在窗口，绝不覆盖已可用数据集。
        existing_keys = {
            (row["窗口起点"], json.dumps(row["维度组合"], ensure_ascii=False, sort_keys=True))
            for row in dataset_rows if row.get("版本编号") == version_code
        }
        last_window_index = max(
            (int(row["窗口序号"]) for row in dataset_rows if row.get("版本编号") == version_code),
            default=-1,
        )
        watermark = max(str(row["事件时间"]) for row in events)

        grouped: dict[tuple[str, str, int, str], list[dict[str, Any]]] = {}
        buckets = _window_buckets(window_seconds)
        for event in events:
            event_time = datetime.fromisoformat(str(event["事件时间"]))
            for bucket_start, bucket_end, index in buckets:
                start_dt = datetime.fromisoformat(bucket_start)
                end_dt = datetime.fromisoformat(bucket_end)
                if start_dt <= event_time < end_dt:
                    dim_combo = {dim: event["维度"].get(dim) for dim in dimensions}
                    key = (bucket_start, bucket_end, index, json.dumps(dim_combo, ensure_ascii=False, sort_keys=True))
                    grouped.setdefault(key, []).append(event)
                    break

        # 新鲜度：流水位（最新事件时间）滞后最近窗口终点的秒数，越大代表数据越旧。
        watermark_dt = datetime.fromisoformat(watermark)
        latest_bucket_end = datetime.fromisoformat(buckets[-1][1]) if buckets else None
        freshness_seconds = (
            max(int((latest_bucket_end - watermark_dt).total_seconds()), 0)
            if latest_bucket_end is not None
            else None
        )

        # 覆盖率按整次计算统一落印：有事件落入的完整窗口 / 应覆盖的完整窗口。
        # 应覆盖窗口取首窗口到水位之间、终点不晚于水位的窗口；
        # 水位所在的未闭合窗口不计入，流中断造成的完整空窗口会如实拉低覆盖率。
        covered_bucket_indexes = {index for _, _, index, _ in grouped}
        expected_bucket_indexes = {
            index
            for _, bucket_end, index in buckets
            if datetime.fromisoformat(bucket_end) <= watermark_dt
        }
        coverage_rate = round(
            len(covered_bucket_indexes & expected_bucket_indexes)
            / max(len(expected_bucket_indexes), 1),
            4,
        )

        appended = 0
        skipped = 0
        for (bucket_start, bucket_end, index, dim_key), bucket_events in sorted(
            grouped.items(), key=lambda item: (item[0][2], item[0][3])
        ):
            dim_combo = json.loads(dim_key)
            if index <= last_window_index or (bucket_start, dim_key) in existing_keys:
                skipped += 1
                continue
            value = round(self._aggregate(aggregate, bucket_events, measure), precision)
            dataset_rows.append({
                "id": store.next_id(TABLE_DATASET),
                "数据集版本号": f"DS-{version_code}-{index:04d}",
                "版本编号": version_code,
                "指标编号": version["指标编号"],
                "指标名称": version["指标名称"],
                "定义内容哈希": version["内容哈希"],
                "窗口起点": bucket_start,
                "窗口终点": bucket_end,
                "窗口序号": index,
                "维度组合": dim_combo,
                "聚合函数": aggregate,
                "指标值": value,
                "精度位数": precision,
                "事件数": len(bucket_events),
                "数据新鲜度秒": freshness_seconds,
                "水位事件时间": watermark,
                "窗口覆盖率": coverage_rate,
                "覆盖窗口数": len(covered_bucket_indexes),
                "应覆盖窗口数": len(expected_bucket_indexes),
                "写入时间": _now(),
                "是否完整窗口": True,
            })
            appended += 1

        # 阈值管理沿现有调用链同步消费本数据集，并把命中追加到只追加的命中表。
        hits = self._evaluate_thresholds(version, dataset_rows, watermark)
        return {
            "版本编号": version_code,
            "本次新增窗口": appended,
            "跳过已存在窗口": skipped,
            "数据集总窗口": sum(1 for row in dataset_rows if row.get("版本编号") == version_code),
            "窗口覆盖率": coverage_rate,
            "数据新鲜度秒": freshness_seconds,
            "恢复点窗口序号": last_window_index,
            "阈值命中新增": hits,
        }

    @staticmethod
    def _aggregate(aggregate: str, events: list[dict[str, Any]], measure: str) -> float:
        values = [float(event["度量值"].get(measure, 0)) for event in events]
        if aggregate == "sum":
            return sum(values)
        if aggregate == "avg":
            return sum(values) / len(values)
        if aggregate == "count":
            return float(len(events))
        if aggregate == "max":
            return max(values)
        if aggregate == "min":
            return min(values)
        raise ChainError(f"不支持的聚合函数 {aggregate}")

    def _evaluate_thresholds(
        self,
        version: dict[str, Any],
        dataset_rows: list[dict[str, Any]],
        watermark: str,
    ) -> int:
        """阈值管理模块同步消费结果数据集；版本失效的规则不参与，命中只追加。"""
        from app.services.threshold import threshold_service

        hits = store.rows(TABLE_HIT)
        existing = {
            (row["规则编号"], row["窗口起点"], json.dumps(row["维度组合"], ensure_ascii=False, sort_keys=True))
            for row in hits
        }
        version_rows = [row for row in dataset_rows if row.get("版本编号") == version["版本编号"]]
        created = 0
        for rule in store.rows("threshold"):
            if rule.get("绑定版本编号") != version["版本编号"]:
                continue
            if rule.get("绑定状态") != "版本有效" or rule.get("status") != "已生效":
                continue
            lower = rule.get("阈值下限")
            upper = rule.get("阈值上限")
            for row in version_rows:
                key = (rule["规则编号"], row["窗口起点"], json.dumps(row["维度组合"], ensure_ascii=False, sort_keys=True))
                if key in existing:
                    continue
                value = float(row["指标值"])
                breached = (lower is not None and value < float(lower)) or (
                    upper is not None and value > float(upper)
                )
                if not breached:
                    continue
                hits.append({
                    "id": store.next_id(TABLE_HIT),
                    "命中编号": f"HIT-{len(hits) + 1:05d}",
                    "规则编号": rule["规则编号"],
                    "绑定版本编号": version["版本编号"],
                    "指标编号": version["指标编号"],
                    "窗口起点": row["窗口起点"],
                    "窗口终点": row["窗口终点"],
                    "维度组合": row["维度组合"],
                    "指标值": value,
                    "阈值下限": lower,
                    "阈值上限": upper,
                    "数据新鲜度秒": row["数据新鲜度秒"],
                    "水位事件时间": watermark,
                    "命中时间": _now(),
                    "处置状态": "待确认",
                })
                existing.add(key)
                created += 1
        threshold_service.mark_synced(version["版本编号"])
        return created

    def list_dataset(
        self,
        *,
        version_code: str | None = None,
        metric_code: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(TABLE_DATASET)
        if version_code:
            rows = [row for row in rows if row.get("版本编号") == version_code]
        if metric_code:
            rows = [row for row in rows if metric_code in str(row.get("指标编号", ""))]
        rows = sorted(rows, key=lambda row: (str(row.get("版本编号")), int(row.get("窗口序号", 0))))
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def list_hits(self, *, rule_code: str | None = None, page: int = 1, size: int = 20) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(TABLE_HIT)
        if rule_code:
            rows = [row for row in rows if rule_code in str(row.get("规则编号", ""))]
        rows = sorted(rows, key=lambda row: str(row.get("命中时间", "")), reverse=True)
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    # ------------------------------------------------------------------ 大盘刷新
    def dashboard_refresh(self, metric_codes: list[str] | None = None) -> dict[str, Any]:
        """大盘刷新结果：每张卡片显式携带指标版本与数据新鲜度。"""
        online_versions = [
            row for row in store.rows(TABLE_VERSION)
            if row.get("状态") == STATUS_ONLINE and (not metric_codes or row.get("指标编号") in metric_codes)
        ]
        cards = []
        for version in sorted(online_versions, key=lambda row: str(row["指标编号"])):
            rows = [
                item for item in store.rows(TABLE_DATASET)
                if item.get("版本编号") == version["版本编号"]
            ]
            latest = rows[-1] if rows else None
            cards.append({
                "指标编号": version["指标编号"],
                "指标名称": version["指标名称"],
                "所用指标版本": version["版本编号"],
                "定义内容哈希": version["内容哈希"],
                "计算窗口秒": version["计算窗口秒"],
                "最新指标值": latest.get("指标值") if latest else None,
                "最新窗口起点": latest.get("窗口起点") if latest else None,
                "数据新鲜度秒": latest.get("数据新鲜度秒") if latest else None,
                "窗口覆盖率": latest.get("窗口覆盖率") if latest else None,
                "刷新时间": _now(),
            })
        return {"刷新时间": _now(), "卡片数": len(cards), "卡片": cards}


metric_chain_service = MetricChainService()
