"""堆场管理业务规则：状态流转、字段校验、容量对账与筛选口径都收在这里。"""
from __future__ import annotations

from typing import Any

from app.services import yard_capacity as capacity
from app.store import store

MODULE = "yard"
REQUIRED_FIELDS = ["箱区编号", "箱区名称", "堆放层数"]
NUMERIC_FIELDS = ["堆放层数", "可用箱位"]
OPTIONAL_FIELDS = ["可用箱位", "所属堆场", "责任人"]
STATUS_ORDER = ["待启用", "正常堆放", "接近满载", "已封闭"]
ACTION_RULES = {"启用箱区": "正常堆放", "封闭箱区": "已封闭", "腾空箱区": "待启用"}
NEGATIVE_ACTIONS = []


class YardService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        # 读取即对账：刷新后箱区状态与箱位占用一定一致
        capacity.reconcile()
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("箱区编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        capacity.reconcile()
        return store.find(MODULE, entry_id)

    def missing_capacity(self) -> list[dict[str, Any]]:
        """箱位数据缺失的箱区单独挑出，供前端整出一块整改清单。"""
        return capacity.missing_capacity_yards()

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        problems: list[str] = []
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            problems.append(f"缺少必填字段：{'、'.join(missing)}")
        for field in NUMERIC_FIELDS:
            raw = str(values.get(field) or "").strip()
            if raw and capacity.parse_count(raw) is None:
                problems.append(f"{field}需为非负整数，当前值「{raw}」无法参与容量计算")
        if problems:
            return None, problems
        rows = store.rows(MODULE)
        code = str(values.get("箱区编号")).strip()
        if any(str(row.get("箱区编号", "")).strip() == code for row in rows):
            return None, [f"箱区编号 {code} 已存在，不能重复登记"]
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        for field in OPTIONAL_FIELDS:
            if str(values.get(field) or "").strip():
                entry[field] = values.get(field)
        # 箱位字段统一存整数，避免后续再被当成缺失数据
        for field in NUMERIC_FIELDS:
            if field in entry:
                entry[field] = capacity.parse_count(entry[field])
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        capacity.reconcile()
        return entry, []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"箱区 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于堆场管理可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        code = str(entry.get("箱区编号", ""))
        if action == "腾空箱区":
            occupying = capacity.used_slots(code)
            if occupying > 0:
                return None, f"箱区 {code} 仍有 {occupying} 箱在场内（堆存中/待提离），不能腾空"
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        # 启用后按实际占用落到「正常堆放/接近满载」，而不是无条件写成正常堆放
        capacity.reconcile()
        return entry, f"箱区已{action}"
