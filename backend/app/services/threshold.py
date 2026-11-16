"""阈值管理业务规则：状态流转、字段校验与筛选口径都收在这里。

口径链上线后，阈值规则与指标定义版本的绑定边界也在本模块收口：
- 规则只能绑定「已上线且未失效」的定义版本，绑定时记录版本指纹保证可追溯；
- 定义版本下线时由口径链服务把关联规则标记为「版本失效」，不再产生新命中；
- 阈值清单随指标版本变化同步更新（绑定状态、同步版本、同步时间）。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.store import store

MODULE = "threshold"
REQUIRED_FIELDS = ["规则编号", "关联指标", "阈值下限"]
STATUS_ORDER = ["草稿", "规则评审中", "已生效", "已关闭"]
ACTION_RULES = {"提交规则评审": "规则评审中", "生效规则": "已生效", "关闭规则": "已关闭"}
NEGATIVE_ACTIONS = []


def _now() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


class ThresholdService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("规则编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": store.next_id(MODULE)}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        # 口径链字段：新规则默认未绑定，必须显式绑定到已上线版本才能参与判定。
        entry.setdefault("绑定版本编号", None)
        entry.setdefault("绑定状态", "未绑定")
        rows.append(entry)
        return entry, []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"阈值规则 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于阈值管理可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return entry, f"阈值规则已{action}"

    # ------------------------------------------------------- 口径链：版本绑定边界
    def bind_version(self, rule_id: int, version_code: str) -> tuple[dict[str, Any] | None, str]:
        """把阈值规则绑定到某个指标定义版本；只接受已上线且未失效的版本。"""
        rule = store.find(MODULE, rule_id)
        if rule is None:
            return None, f"阈值规则 {rule_id} 不存在或已归档"

        # 延迟导入避免与 metric_chain 形成模块加载环。
        from app.services.metric_chain import STATUS_ONLINE, metric_chain_service

        version = metric_chain_service.get_version(version_code)
        if version is None:
            return None, f"定义版本 {version_code} 不存在，无法绑定"
        if version["状态"] != STATUS_ONLINE:
            return None, (
                f"定义版本 {version_code} 当前为「{version['状态']}」，"
                "阈值规则只能引用已上线且未失效的版本"
            )
        if rule.get("关联指标") and rule["关联指标"] != version["指标编号"]:
            return None, (
                f"规则关联指标为 {rule['关联指标']}，与版本 {version_code} "
                f"所属指标 {version['指标编号']} 不一致"
            )
        rule["关联指标"] = version["指标编号"]
        rule["绑定版本编号"] = version_code
        rule["绑定版本哈希"] = version["内容哈希"]
        rule["绑定状态"] = "版本有效"
        rule["绑定时间"] = _now()
        rule["abnormal"] = False
        return rule, f"规则 {rule['规则编号']} 已绑定版本 {version_code}（指纹 {version['内容哈希']}）"

    def mark_synced(self, version_code: str) -> None:
        """结果数据集被消费后，回写同步标记，供阈值清单展示同步状态。"""
        for row in store.rows(MODULE):
            if row.get("绑定版本编号") == version_code:
                row["最近同步版本"] = version_code
                row["最近同步时间"] = _now()

    def version_bindings(self) -> list[dict[str, Any]]:
        """阈值清单随指标版本变化同步更新的视图：每条规则的版本绑定与同步情况。"""
        from app.services.metric_chain import metric_chain_service

        view = []
        for rule in store.rows(MODULE):
            version_code = rule.get("绑定版本编号")
            version = metric_chain_service.get_version(version_code) if version_code else None
            view.append({
                "规则编号": rule.get("规则编号"),
                "关联指标": rule.get("关联指标"),
                "绑定版本编号": version_code,
                "绑定状态": rule.get("绑定状态", "未绑定"),
                "绑定版本哈希": rule.get("绑定版本哈希"),
                "版本当前状态": version.get("状态") if version else None,
                "阈值下限": rule.get("阈值下限"),
                "阈值上限": rule.get("阈值上限"),
                "规则状态": rule.get("status"),
                "最近同步版本": rule.get("最近同步版本"),
                "最近同步时间": rule.get("最近同步时间"),
            })
        return view


threshold_service = ThresholdService()
