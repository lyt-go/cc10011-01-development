"""实时指标口径链接口。

把「不可变定义版本 + 发布校验 + 窗口计算 + 只追加数据集 + 阈值版本绑定」
组织成一条可发布、可追溯的链，路由层只做参数收发，业务判断全部在 service。
"""
from __future__ import annotations

from fastapi import APIRouter, Query

from app.chain_seed import TABLE_STREAM
from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.metric_chain import ChainError, metric_chain_service
from app.store import store

router = APIRouter(prefix="/api/realtimemetric/chain", tags=["实时指标口径链"])


def _failed(message: str) -> ActionResult:
    return ActionResult(ok=False, message=message)


@router.get("/versions", response_model=PageResult[dict])
def list_versions(
    metric_code: str | None = Query(default=None, description="按指标编号过滤"),
    status: str | None = Query(default=None, description="草稿、评审中、已上线、已下线"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """列出不可变指标定义版本，可按指标编号与生命周期状态过滤。"""
    items, total = metric_chain_service.list_versions(
        metric_code=metric_code, status=status, page=page, size=size
    )
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/versions/{version_code}", response_model=dict)
def get_version(version_code: str) -> dict:
    version = metric_chain_service.get_version(version_code)
    if version is None:
        raise _not_found(version_code)
    return version


@router.post("/versions", response_model=ActionResult)
def create_draft(payload: EntryPayload) -> ActionResult:
    """登记新的草稿定义版本；草稿是唯一允许修改口径的阶段。"""
    try:
        version, missing = metric_chain_service.create_draft(payload.values)
    except ChainError as exc:
        return _failed(str(exc))
    if missing:
        return _failed(f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="草稿定义版本已登记，提交评审后内容冻结", entry=version)


@router.post("/versions/{version_code}/actions", response_model=ActionResult)
def version_action(version_code: str, payload: EntryPayload) -> ActionResult:
    """版本生命周期动作：提交评审 / 发布上线 / 下线指标，单向相邻推进。"""
    action = str(payload.values.get("action") or "").strip()
    try:
        version, message = metric_chain_service.transition(version_code, action)
    except ChainError as exc:
        return _failed(str(exc))
    if version is None:
        return _failed(message)
    return ActionResult(ok=True, message=message, entry=version)


@router.get("/versions/{version_code}/publish-detail", response_model=dict)
def publish_detail(version_code: str) -> dict:
    """发布详情：指标版本、计算窗口、数据新鲜度与数据集落点一屏列出。"""
    try:
        return metric_chain_service.publish_detail(version_code)
    except ChainError as exc:
        raise _not_found(str(exc))


@router.get("/diff", response_model=dict)
def diff_versions(
    left: str = Query(description="左侧版本编号"),
    right: str = Query(description="右侧版本编号"),
) -> dict:
    """两个定义版本的并排差异视图。"""
    try:
        return metric_chain_service.diff_versions(left, right)
    except ChainError as exc:
        raise _not_found(str(exc))


@router.post("/compute", response_model=ActionResult)
def compute(payload: EntryPayload) -> ActionResult:
    """读取定义版本与数据源流记录，校验并计算窗口结果，追加写入结果数据集。

    中断恢复时从上一完整窗口继续，已可用数据集不会被覆盖；
    阈值管理在同一次调用里同步消费数据集并追加阈值命中。
    """
    version_code = str(payload.values.get("版本编号") or "").strip()
    if not version_code:
        return _failed("缺少必填字段：版本编号")
    try:
        result = metric_chain_service.compute(version_code)
    except ChainError as exc:
        return _failed(str(exc))
    return ActionResult(ok=True, message="口径链计算完成，结果数据集已追加", entry=result)


@router.get("/dataset", response_model=PageResult[dict])
def list_dataset(
    version_code: str | None = Query(default=None, description="按定义版本过滤"),
    metric_code: str | None = Query(default=None, description="按指标编号过滤"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """实时指标计算结果数据集（只追加），每行携带新鲜度与窗口覆盖率。"""
    items, total = metric_chain_service.list_dataset(
        version_code=version_code, metric_code=metric_code, page=page, size=size
    )
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/hits", response_model=PageResult[dict])
def list_hits(
    rule_code: str | None = Query(default=None, description="按阈值规则过滤"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """阈值命中结果（只追加）；指标下线后的规则不会再出现新命中。"""
    items, total = metric_chain_service.list_hits(rule_code=rule_code, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/streams", response_model=dict)
def list_streams() -> dict:
    """数据源流记录：口径链读取的上游清单与水位。"""
    rows = store.rows(TABLE_STREAM)
    return {"total": len(rows), "items": rows}


@router.get("/dashboard-refresh", response_model=dict)
def dashboard_refresh(
    metric_codes: str | None = Query(default=None, description="逗号分隔的指标编号；空表示全部已上线指标"),
) -> dict:
    """大盘刷新结果：明确显示所用指标版本与数据新鲜度。"""
    codes = [part.strip() for part in metric_codes.split(",") if part.strip()] if metric_codes else None
    return metric_chain_service.dashboard_refresh(codes)


def _not_found(message: str) -> Exception:
    from fastapi import HTTPException

    return HTTPException(status_code=404, detail=message)
