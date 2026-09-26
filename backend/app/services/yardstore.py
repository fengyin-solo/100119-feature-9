"""堆存记录业务规则：状态流转、字段校验与筛选口径都收在这里。

与堆场管理的联动口径：
- 保存堆存单即占用箱区一个箱位，确认提离、撤销堆存时释放（slot_held 记录占用状态，防止重复占用/释放）；
- 保存前按堆场管理的判定口径校验：箱区已封闭、箱位数据缺失、再堆会超上限的，一律不允许保存并说明原因；
- 箱区接近满载的提醒由堆场管理统一发，且同一箱区只提醒一次。
"""
from __future__ import annotations

from typing import Any

from app.services.yard import yard_service
from app.store import store

MODULE = "yardstore"
REQUIRED_FIELDS = ["堆存单号", "关联箱号", "箱区编号"]
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
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("堆存单号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, f"缺少必填字段：{'、'.join(missing)}"
        block_no = str(values.get("箱区编号") or "").strip()
        _, reason = yard_service.check_accept(block_no)
        if reason:
            return None, reason
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        entry["slot_held"] = True
        rows.append(entry)
        warning = yard_service.occupy(block_no)
        message = "堆存单已登记"
        if warning:
            message = f"{message}；{warning}"
        return entry, message

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"堆存单 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于堆存记录可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        block_no = str(entry.get("箱区编号") or "").strip()
        warning: str | None = None
        if action == "确认进场" and not entry.get("slot_held"):
            # 撤销后重新进场：重新过一遍箱区判定并占位
            _, reason = yard_service.check_accept(block_no)
            if reason:
                return None, reason
            warning = yard_service.occupy(block_no)
            entry["slot_held"] = True
        if action in ("确认提离", "撤销堆存") and entry.get("slot_held"):
            yard_service.release(block_no)
            entry["slot_held"] = False
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        message = f"堆存单已{action}"
        if warning:
            message = f"{message}；{warning}"
        return entry, message
