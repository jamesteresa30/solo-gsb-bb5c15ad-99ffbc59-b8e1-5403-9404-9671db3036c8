"""事件窗口冲突分析（sweep-line）。

每个事件按服务端 UTC 拆成两个半开区间（与 app.main 的生命周期判定一致）：
  commit 阶段: [created_at, commit_deadline)
  reveal 阶段: [commit_deadline, reveal_deadline)

sweep-line 扫描所有区间端点：相邻端点之间活跃事件集合恒定，输出活跃事件数
≥ 2 的极大片段（冲突片段）。半开边界保证仅在端点处相接的区间不构成冲突。
"""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

PHASES = ("commit", "reveal")


@dataclass(frozen=True)
class PhaseWindow:
    """单个事件在单个阶段上的半开时间窗口 [start, end)。"""

    event_id: UUID
    phase: str  # commit | reveal
    start: datetime
    end: datetime


@dataclass(frozen=True)
class ConflictSegment:
    """极大冲突片段：[start, end) 内这些事件同时处于同一阶段。"""

    phase: str  # commit | reveal
    start: datetime
    end: datetime
    event_ids: tuple[UUID, ...]


def event_windows(
    event_id: UUID,
    created_at: datetime,
    commit_deadline: datetime,
    reveal_deadline: datetime,
) -> list[PhaseWindow]:
    """把事件生命周期拆成 commit / reveal 两个半开窗口（调用方负责转为 UTC）。"""
    return [
        PhaseWindow(event_id, "commit", created_at, commit_deadline),
        PhaseWindow(event_id, "reveal", commit_deadline, reveal_deadline),
    ]


def sweep_conflicts(windows: list[PhaseWindow]) -> list[ConflictSegment]:
    """sweep-line：按阶段分别扫描端点，返回活跃事件数 ≥ 2 的极大半开片段。

    结果按 (start, end, phase, event_ids) 排序，片段内事件 ID 按字典序排列，
    保证输出稳定（空输入稳定返回空列表）。
    """
    segments: list[ConflictSegment] = []
    for phase in PHASES:
        starts: dict[datetime, list[UUID]] = {}
        ends: dict[datetime, list[UUID]] = {}
        for w in windows:
            if w.phase != phase or not w.start < w.end:
                continue
            starts.setdefault(w.start, []).append(w.event_id)
            ends.setdefault(w.end, []).append(w.event_id)

        active: set[UUID] = set()
        prev: datetime | None = None
        for t in sorted(set(starts) | set(ends)):
            # [prev, t) 内活跃集合恒定；≥ 2 个事件即构成冲突片段
            if prev is not None and len(active) >= 2:
                segments.append(
                    ConflictSegment(phase, prev, t, tuple(sorted(active, key=str)))
                )
            prev = t
            # 半开区间：在 t 结束的窗口先离场，在 t 开始的窗口再入场
            for event_id in ends.get(t, ()):
                active.discard(event_id)
            for event_id in starts.get(t, ()):
                active.add(event_id)

    segments.sort(
        key=lambda s: (s.start, s.end, s.phase, tuple(str(i) for i in s.event_ids))
    )
    return segments
