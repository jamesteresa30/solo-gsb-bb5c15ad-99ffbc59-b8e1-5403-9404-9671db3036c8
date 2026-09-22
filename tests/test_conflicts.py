"""sweep-line 冲突分析的纯函数单元测试（不依赖数据库、不依赖时钟）。"""

from datetime import datetime, timedelta, timezone
from uuid import UUID

from app.conflicts import event_windows, sweep_conflicts

T0 = datetime(2030, 1, 1, tzinfo=timezone.utc)
A = UUID("00000000-0000-0000-0000-00000000000a")
B = UUID("00000000-0000-0000-0000-00000000000b")
C = UUID("00000000-0000-0000-0000-00000000000c")


def at(hours: int) -> datetime:
    return T0 + timedelta(hours=hours)


def windows(event_id: UUID, created_h: int, commit_h: int, reveal_h: int):
    return event_windows(event_id, at(created_h), at(commit_h), at(reveal_h))


def summary(segments):
    return [(s.phase, s.start, s.end, s.event_ids) for s in segments]


def test_empty_and_single_event_yield_no_conflicts():
    assert sweep_conflicts([]) == []
    assert sweep_conflicts(windows(A, 0, 1, 2)) == []


def test_touching_intervals_do_not_conflict():
    # 半开边界：A 的 commit [0,1) 与 B 的 commit [1,2) 端点相接，不构成冲突；
    # reveal 同理（[1,2) 与 [2,3)）。
    segs = sweep_conflicts(windows(A, 0, 1, 2) + windows(B, 1, 2, 3))
    assert segs == []


def test_pairwise_overlaps_split_into_maximal_segments():
    # commit: A [0,2) B [1,4) C [3,6)；reveal 互不重叠
    segs = sweep_conflicts(
        windows(A, 0, 2, 3) + windows(B, 1, 4, 5) + windows(C, 3, 6, 7)
    )
    assert summary(segs) == [
        ("commit", at(1), at(2), (A, B)),
        ("commit", at(3), at(4), (B, C)),
    ]


def test_nested_overlap_and_both_phases_sorted():
    # commit: A [0,5) B [1,6) C [2,3)（嵌套三方重叠）
    # reveal: A [5,6) B [6,7) C [3,8)
    segs = sweep_conflicts(
        windows(A, 0, 5, 6) + windows(B, 1, 6, 7) + windows(C, 2, 3, 8)
    )
    assert summary(segs) == [
        ("commit", at(1), at(2), (A, B)),
        ("commit", at(2), at(3), (A, B, C)),
        ("commit", at(3), at(5), (A, B)),
        ("reveal", at(5), at(6), (A, C)),
        ("reveal", at(6), at(7), (B, C)),
    ]


def test_identical_windows_merge_into_single_segment_per_phase():
    segs = sweep_conflicts(windows(A, 0, 1, 2) + windows(B, 0, 1, 2))
    assert summary(segs) == [
        ("commit", at(0), at(1), (A, B)),
        ("reveal", at(1), at(2), (A, B)),
    ]


def test_zero_length_windows_are_ignored():
    # 防御性：start == end 的退化窗口不参与扫描
    segs = sweep_conflicts(
        event_windows(A, at(0), at(1), at(1)) + windows(B, 0, 1, 2)
    )
    assert summary(segs) == [("commit", at(0), at(1), (A, B))]


def test_output_is_deterministic_regardless_of_input_order():
    ws = windows(A, 0, 5, 6) + windows(B, 1, 6, 7) + windows(C, 2, 3, 8)
    assert sweep_conflicts(ws) == sweep_conflicts(list(reversed(ws)))
