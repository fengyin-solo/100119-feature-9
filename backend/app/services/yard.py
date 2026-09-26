"""堆场管理业务规则：状态流转、字段校验与筛选口径都收在这里。

容量判定口径：
- 容量上限 = 堆放层数 × 可用箱位（每层可堆箱位数），任一缺失或不是正整数即视为箱位数据缺失；
- 已用箱位 ÷ 容量上限 ≥ NEAR_FULL_RATIO 判「接近满载」，再堆一箱会超过容量上限则不允许保存；
- 箱区状态随占用实时推导（待启用、已封闭保留人工流转结果），保证刷新后状态与箱位占用一致；
- 「接近满载」提醒按箱区编号只发一次，重复触及上限不再打扰。
"""
from __future__ import annotations

from typing import Any

from app.store import store

MODULE = "yard"
REQUIRED_FIELDS = ["箱区编号", "箱区名称", "堆放层数"]
OPTIONAL_FIELDS = ["可用箱位", "已用箱位", "所属堆场", "责任人"]
STATUS_ORDER = ["待启用", "正常堆放", "接近满载", "已封闭"]
ACTION_RULES = {"启用箱区": "正常堆放", "封闭箱区": "已封闭", "腾空箱区": "待启用"}
NEGATIVE_ACTIONS = []
MANUAL_STATUSES = {"待启用", "已封闭"}  # 人工流转状态，不参与占用派生
NEAR_FULL_RATIO = 0.9  # 已用箱位达到容量上限的 90% 即视为接近满载


def _to_int(value: Any) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def capacity_of(entry: dict[str, Any]) -> int | None:
    """容量上限 = 堆放层数 × 每层可用箱位；数据缺失或非法时返回 None。"""
    tiers = _to_int(entry.get("堆放层数"))
    per_tier = _to_int(entry.get("可用箱位"))
    if tiers is None or per_tier is None or tiers <= 0 or per_tier <= 0:
        return None
    return tiers * per_tier


def used_of(entry: dict[str, Any]) -> int:
    return max(_to_int(entry.get("已用箱位")) or 0, 0)


def slot_data_missing(entry: dict[str, Any]) -> bool:
    """堆放层数或可用箱位缺失/非法，无法算出容量上限。"""
    return capacity_of(entry) is None


def derive_status(entry: dict[str, Any]) -> str:
    """按当前占用推导箱区状态；人工状态（待启用、已封闭）保持原样。"""
    stored = str(entry.get("status") or "")
    if stored in MANUAL_STATUSES:
        return stored
    capacity = capacity_of(entry)
    if capacity is None:
        return stored if stored in STATUS_ORDER else STATUS_ORDER[0]
    if used_of(entry) / capacity >= NEAR_FULL_RATIO:
        return "接近满载"
    return "正常堆放"


def decorate(entry: dict[str, Any]) -> dict[str, Any]:
    """读取出口：补上容量上限、占用率等派生字段，状态以当前占用为准。"""
    row = dict(entry)
    capacity = capacity_of(entry)
    used = used_of(entry)
    status = derive_status(entry)
    row["已用箱位"] = used
    row["容量上限"] = capacity
    row["占用率"] = round(used / capacity * 100, 1) if capacity else None
    row["箱位数据缺失"] = capacity is None
    row["status"] = status
    row["箱区状态"] = status
    row["可继续堆放"] = capacity is not None and used < capacity and status != "已封闭"
    return row


class YardService:
    def __init__(self) -> None:
        # 已发过「接近满载」提醒的箱区编号：同一箱区重复触及上限只提醒一次
        self._near_full_warned: set[str] = set()

    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        slot_missing: bool = False,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = [decorate(row) for row in store.rows(MODULE)]
        if slot_missing:
            rows = [row for row in rows if row["箱位数据缺失"]]
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("箱区编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        entry = store.find(MODULE, entry_id)
        return decorate(entry) if entry is not None else None

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, f"缺少必填字段：{'、'.join(missing)}"
        block_no = str(values.get("箱区编号") or "").strip()
        if self.find_by_block(block_no) is not None:
            return None, f"箱区编号 {block_no} 已存在，请更换编号后再登记"
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS + OPTIONAL_FIELDS})
        entry["已用箱位"] = used_of(entry)
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return decorate(entry), "箱区已登记"

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"箱区 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于堆场管理可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        if action == "腾空箱区":
            entry["已用箱位"] = 0
        return decorate(entry), f"箱区已{action}"

    # ---- 以下判定口径同时供堆存记录模块调用 ----

    def find_by_block(self, block_no: str) -> dict[str, Any] | None:
        for row in store.rows(MODULE):
            if str(row.get("箱区编号", "")) == block_no:
                return row
        return None

    def check_accept(self, block_no: str) -> tuple[dict[str, Any] | None, str]:
        """判定箱区还能不能继续接收堆存单；不能时返回原因。"""
        block = self.find_by_block(block_no)
        if block is None:
            return None, f"箱区 {block_no} 不存在，无法接收堆存单"
        if block.get("status") == "已封闭":
            return None, f"箱区 {block_no} 已封闭，不能再接收堆存单"
        capacity = capacity_of(block)
        if capacity is None:
            return None, f"箱区 {block_no} 的箱位数据缺失（堆放层数/可用箱位），无法判定容量上限，请先补全箱区资料"
        used = used_of(block)
        if used + 1 > capacity:
            return None, f"箱区 {block_no} 容量上限 {capacity}、已用箱位 {used}，再堆 1 箱将超堆，不允许保存"
        return block, ""

    def occupy(self, block_no: str) -> str | None:
        """占用一个箱位；触及接近满载线时返回提醒语，同一箱区只提醒一次。"""
        block = self.find_by_block(block_no)
        if block is None:
            return None
        block["已用箱位"] = used_of(block) + 1
        capacity = capacity_of(block)
        used = used_of(block)
        if capacity and used / capacity >= NEAR_FULL_RATIO and block_no not in self._near_full_warned:
            self._near_full_warned.add(block_no)
            return f"提醒：箱区 {block_no} 已用箱位 {used}/{capacity}，已接近满载，请合理安排后续堆放"
        return None

    def release(self, block_no: str) -> None:
        """释放一个箱位（提离或撤销堆存时调用），已用箱位不为负。"""
        block = self.find_by_block(block_no)
        if block is not None:
            block["已用箱位"] = max(used_of(block) - 1, 0)


yard_service = YardService()
