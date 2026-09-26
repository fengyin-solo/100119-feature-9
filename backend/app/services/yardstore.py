"""堆存记录业务规则：状态流转、字段校验、箱区容量拦截与筛选口径都收在这里。"""
from __future__ import annotations

from typing import Any

from app.services import yard_capacity as capacity
from app.store import store

MODULE = "yardstore"
REQUIRED_FIELDS = ["堆存单号", "关联箱号", "箱区编号"]
OPTIONAL_FIELDS = ["贝位号"]
STATUS_ORDER = ["待进场", "堆存中", "待提离", "已提离"]
ACTION_RULES = {"确认进场": "堆存中", "确认提离": "已提离", "撤销堆存": "待进场"}
NEGATIVE_ACTIONS = ["撤销堆存"]


class YardstoreService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        # 读取堆存单时顺带对账箱区占用：刷新后两处数据保持一致
        capacity.reconcile()
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("堆存单号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        capacity.reconcile()
        return store.find(MODULE, entry_id)

    def _validate_yard_receivable(self, code: str) -> tuple[dict[str, Any] | None, str | None]:
        """箱区是否还能接收堆存单：存在、未封闭，是开单与进场的共同判定口径。"""
        yard = capacity.find_yard_by_code(code)
        if yard is None:
            return None, f"箱区 {code} 不存在，请先在堆场管理中登记箱区"
        if yard.get("status") == "已封闭":
            return None, f"箱区 {code} 已封闭，不能再接收堆存单"
        return yard, None

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        problems = [f"缺少必填字段：{'、'.join(missing)}"] if missing else []
        code = str(values.get("箱区编号") or "").strip()
        if code:
            capacity.reconcile()
            _yard, reason = self._validate_yard_receivable(code)
            if reason:
                problems.append(reason)
        if problems:
            return None, problems
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        for field in OPTIONAL_FIELDS:
            if str(values.get(field) or "").strip():
                entry[field] = values.get(field)
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"堆存单 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于堆存记录可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"

        code = str(entry.get("箱区编号", "")).strip()
        notice: str | None = None
        # 只有从非占用状态确认进场才会新占箱位；对已在场的单子重复确认是空转，不再扣容量
        if action == "确认进场" and entry.get("status") not in capacity.OCCUPYING_STATUSES:
            yard, reason = self._validate_yard_receivable(code)
            if reason:
                return None, reason
            limit = capacity.capacity_limit(yard)
            if limit is None:
                return None, (
                    f"箱区 {code} 箱位数据缺失（堆放层数或可用箱位未维护），"
                    "无法判定容量上限，请先补全箱区资料"
                )
            used = capacity.used_slots(code)
            if used + 1 > limit:
                return None, (
                    f"箱区 {code} 已超出堆放上限，不能确认进场："
                    f"容量上限 = 堆放层数 × 可用箱位 = {limit} 箱，当前已用 {used} 箱"
                )

        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        # 进场/提离后立即按堆存单重新对账箱区占用与状态
        capacity.reconcile()
        if action == "确认进场":
            yard = capacity.find_yard_by_code(code)
            if yard is not None:
                notice = capacity.near_full_notice(yard)
        message = f"堆存单已{action}"
        if notice:
            message = f"{message}；提醒：{notice}"
        return entry, message
