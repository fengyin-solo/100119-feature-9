"""箱区容量判定口径：容量上限、占用统计、状态对账与接近满载提醒都收在这里。

口径说明：
- 容量上限 = 堆放层数 × 可用箱位；两者缺一（空值或不是非负整数）视为箱位数据缺失。
- 已用箱位以堆存单为准：状态为「堆存中」「待提离」的箱子仍在场内，占用箱位；
  「待进场」「已提离」不占箱位。任何读取或动作之后都以这份口径对账，
  保证刷新页面后箱区状态与箱位占用一致，而不是各自维护一套对不上的数字。
- 已用箱位达到容量上限的 90% 为「接近满载」；同一箱区在同一轮高位期只提醒一次，
  占用回落到阈值以下后才允许再次提醒。
"""
from __future__ import annotations

from typing import Any

from app.store import store

YARD_MODULE = "yard"
YARDSTORE_MODULE = "yardstore"

# 仍在场内、占用箱位的堆存单状态（待提离的箱子尚未离场）
OCCUPYING_STATUSES = ("堆存中", "待提离")
# 已用箱位达到容量上限的该比例即判定接近满载
NEAR_FULL_RATIO = 0.9

MISSING_CAPACITY_NOTE = "箱位数据缺失"


def parse_count(value: Any) -> int | None:
    """把箱位/层数字段解析为非负整数；空值、非数字、负数一律视为缺失。"""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        number = int(float(text))
    except ValueError:
        return None
    if number < 0:
        return None
    return number


def capacity_limit(yard: dict[str, Any]) -> int | None:
    """容量上限 = 堆放层数 × 可用箱位；任一关键数据缺失返回 None。"""
    layers = parse_count(yard.get("堆放层数"))
    slots = parse_count(yard.get("可用箱位"))
    if layers is None or slots is None:
        return None
    return layers * slots


def find_yard_by_code(code: str) -> dict[str, Any] | None:
    for row in store.rows(YARD_MODULE):
        if str(row.get("箱区编号", "")).strip() == code:
            return row
    return None


def used_slots(yard_code: str) -> int:
    """以堆存单为权威数据源，统计箱区当前实际占用箱位。"""
    return sum(
        1
        for row in store.rows(YARDSTORE_MODULE)
        if str(row.get("箱区编号", "")).strip() == yard_code
        and row.get("status") in OCCUPYING_STATUSES
    )


def is_near_full(used: int, limit: int) -> bool:
    return used >= limit * NEAR_FULL_RATIO


def missing_capacity_yards() -> list[dict[str, Any]]:
    """把箱位数据缺失（堆放层数或可用箱位无法参与容量计算）的箱区单独挑出。"""
    return [row for row in store.rows(YARD_MODULE) if capacity_limit(row) is None]


def _sync_yard(yard: dict[str, Any]) -> None:
    """按当前堆存占用对齐单个箱区的已用箱位、容量提示、异常标记与堆放状态。"""
    code = str(yard.get("箱区编号", ""))
    used = used_slots(code)
    limit = capacity_limit(yard)
    yard["已用箱位"] = used

    if limit is None:
        # 数据缺失：不猜状态，只打标记，交由缺失清单督促补录
        yard["容量上限"] = None
        yard["容量提示"] = MISSING_CAPACITY_NOTE
        yard["abnormal"] = True
        yard["接近满载已提醒"] = False
        return

    yard["容量上限"] = limit
    yard["abnormal"] = used > limit
    if used > limit:
        yard["容量提示"] = f"已超堆：已用 {used} / 上限 {limit}"
    elif is_near_full(used, limit):
        yard["容量提示"] = f"接近满载：已用 {used} / 上限 {limit}"
    else:
        yard["容量提示"] = ""
        # 占用回落到阈值以下，复位提醒标记，允许下一轮高位期重新提醒
        yard["接近满载已提醒"] = False

    # 只有人工生命周期状态（正常堆放/接近满载）随容量自动推导，待启用/已封闭不串改
    if yard.get("status") in ("正常堆放", "接近满载"):
        yard["status"] = "接近满载" if is_near_full(used, limit) else "正常堆放"
        yard["pending"] = True


def reconcile() -> None:
    """全量对账：让每个箱区的已用箱位与箱区状态都反映最新的堆存占用。"""
    for yard in store.rows(YARD_MODULE):
        _sync_yard(yard)


def near_full_notice(yard: dict[str, Any]) -> str | None:
    """取一次接近满载提醒；同一箱区在同一轮高位期只提醒一次。

    占用回落到接近满载阈值以下时重置标记，之后再次触及才会重新提醒。
    """
    limit = yard.get("容量上限")
    if not isinstance(limit, int) or limit <= 0:
        yard["接近满载已提醒"] = False
        return None
    used = parse_count(yard.get("已用箱位")) or 0
    if not is_near_full(used, limit):
        yard["接近满载已提醒"] = False
        return None
    if yard.get("接近满载已提醒"):
        return None
    yard["接近满载已提醒"] = True
    code = yard.get("箱区编号", "")
    return f"箱区 {code} 已接近满载（已用 {used} 箱 / 上限 {limit} 箱），剩余箱位请优先安排"
