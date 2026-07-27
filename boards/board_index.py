"""Board Index 分派上下文组装。

按 BOARD_INDEX_BACKEND_GUIDE.md §2.3，单个 `boards` app 内用 `Board.slug` 分派
三板（skateboard / music / coding）内容与模板。`ASSEMBLERS` 是 dict 分派表，
避免 `if/elif` 硬编码 slug 字符串散落各处；`BOARD_TEMPLATES` 给出每板模板。

内容仅由 superuser 在 Admin 维护（决策 5）；本模块只读取，不写入、不鉴权。
公开过滤（如 `SkateClip.is_public`）在查询层完成，避免泄露非公开内容。
"""

from django.urls import reverse

from boards.models import (
    AppleSnapshot,
    CodingExperiment,
    CodingPrinciple,
    CodingProject,
    SkateClip,
    SkateHomie,
    SpotifySnapshot,
)

__all__ = ["ASSEMBLERS", "BOARD_TEMPLATES", "assemble_context"]


BOARD_TEMPLATES = {
    "skateboard": "pages/boards/skateboard/index.html",
    "music": "pages/music/index.html",
    "coding": "pages/coding/index.html",
}


def _format_duration(duration):
    """DurationField → mm:ss；空值返回空串（与 mock 契约 duration='00:04' 一致）。"""
    if not duration:
        return ""
    total = int(duration.total_seconds())
    minutes, seconds = divmod(total, 60)
    return f"{minutes:02d}:{seconds:02d}"


def _homie_line_url(board_slug, node_index):
    """单个 Homie 的 htmx 端点（返回 Selected Line 片段）。"""
    return reverse("boards:homie-line", args=[board_slug, node_index])


def assemble_skateboard(board):
    """组装 Skateboard Index 上下文：成员节点 + 当前选中成员的公开片段。"""
    homies = list(SkateHomie.objects.filter(board=board).select_related("board"))
    for homie in homies:
        # 模板只读取这些属性，分派层附加，避免污染模型字段
        homie.state = "active" if homie.is_active else ""
        homie.avatar_url = homie.avatar.url if homie.avatar else ""
        homie.line_url = _homie_line_url(board.slug, homie.node_index)

    selected = next((h for h in homies if h.is_active), None)
    if selected is None and homies:
        selected = homies[0]

    clip_list = []
    if selected is not None:
        clip_list = list(
            SkateClip.objects.filter(homie=selected, is_public=True)
            .select_related("homie")
            .order_by("order", "pk")
        )
        for clip in clip_list:
            clip.duration_display = _format_duration(clip.duration)

    return {
        "homies": homies,
        "selected_homie": selected,
        "clip_list": clip_list,
        # open_node_url 保持占位（决策 5：无公开投稿），模板据此禁用按钮
        "open_node_url": None,
    }


def _archive_rows(snapshots):
    """将快照序列化为 archive 行（label / value / tags / period），供模板遍历。

    value 优先取 kind='total' 的条目，否则取 display_order 最小者；
    tags 取 kind='tag' 的条目 label 拼接。空快照给出安全空值。
    """
    rows = []
    for snap in snapshots:
        entries = list(snap.entries.all())
        primary = next((e for e in entries if e.kind == "total"), None)
        if primary is None and entries:
            primary = entries[0]
        value = f"{primary.value} {primary.unit}".strip() if primary else ""
        tags = " / ".join(e.label for e in entries if e.kind == "tag") if entries else ""
        label = f"{snap.year}.{snap.month:02d}" if snap.month else str(snap.year)
        rows.append({"label": label, "value": value, "tags": tags, "period": label})
    return rows


def _safe_int(text):
    """从可能含逗号/单位的文本提取整数（如 '32,481 MIN' → 32481）。"""
    if not text:
        return 0
    digits = "".join(ch for ch in str(text) if ch.isdigit())
    return int(digits) if digits else 0


_MONTH_ABBR = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN",
               "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]


def _month_label(snapshot):
    """快照 → 月度缩写（有 month）或年份标签。"""
    if snapshot.month:
        idx = snapshot.month - 1
        if 0 <= idx < len(_MONTH_ABBR):
            return _MONTH_ABBR[idx]
    return str(snapshot.year)


def _entries_by_kind(snapshots, kind):
    """收集若干快照内指定 kind 的条目（保持各自 display_order 顺序）。"""
    out = []
    for snap in snapshots:
        out.extend(e for e in snap.entries.all() if e.kind == kind)
    return out


def _latest(snapshots):
    """取最新快照（Meta 已 -year,-month 排序，首项即最新）。"""
    return snapshots[0] if snapshots else None


def assemble_music(board):
    """组装 Music Index 上下文：全部叙事区数据驱动。

    编辑性条目（core_artist / period_artist / cross_scale / companion /
    gravity）仅挂在各 provider 的最新快照上，assembler 只读取最新快照。
    """
    spotify = list(
        SpotifySnapshot.objects.filter(board=board).prefetch_related("entries")
    )
    apple = list(
        AppleSnapshot.objects.filter(board=board).prefetch_related("entries")
    )

    updated = None
    for snap in spotify + apple:
        if updated is None or snap.updated_at > updated:
            updated = snap.updated_at

    latest_spotify = _latest(spotify)
    latest_apple = _latest(apple)

    # 当前周期（hero + monthly current）：来自最新 Apple 月度快照
    current_period_label = None
    current_period_artists = []
    if latest_apple is not None:
        current_period_label = f"{latest_apple.year}.{latest_apple.month:02d}"
        current_period_artists = [
            {"name": e.label, "tag": e.value}
            for e in _entries_by_kind([latest_apple], "period_artist")
        ]

    # 年度概览：来自最新 Spotify 年度快照
    yearly = None
    if latest_spotify is not None:
        entries = list(latest_spotify.entries.all())
        total = next((e for e in entries if e.kind == "total"), None)
        total_str = f"{total.value} {total.unit}".strip() if total else ""
        core = sorted(
            (e for e in entries if e.kind == "core_artist"),
            key=lambda e: _safe_int(e.value),
        )
        core_artists = [{"rank": i + 1, "name": e.label}
                        for i, e in enumerate(core)]
        tags = " / ".join(e.label for e in entries if e.kind == "tag")
        yearly = {
            "year": latest_spotify.year,
            "total": total_str,
            "core_artists": core_artists,
            "tags": tags,
        }

    # 月度柱状：来自 Apple 月度快照（按时间升序，pct 相对最高）
    monthly_bars = []
    monthly_current = None
    if apple:
        ordered = sorted(apple, key=lambda s: (s.year, s.month or 0))
        minutes = []
        for s in ordered:
            t = next((e for e in s.entries.all() if e.kind == "total"), None)
            minutes.append(_safe_int(t.value) if t else 0)
        max_min = max(minutes) if minutes else 1
        for s, m in zip(ordered, minutes):
            monthly_bars.append({
                "month_label": _month_label(s),
                "minutes": m,
                "minutes_display": "{:,}".format(m),
                "pct": round(m / max_min * 100) if max_min else 0,
                "is_current": s is latest_apple,
            })
        if latest_apple is not None:
            cur = next((e for e in latest_apple.entries.all()
                        if e.kind == "total"), None)
            monthly_current = {
                "label": current_period_label,
                "minutes_display": (
                    "{:,}".format(_safe_int(cur.value)) if cur else "0"),
            }

    # 跨尺度关系：来自 Spotify 快照
    cross_scale = [
        {"name": e.label, "yearly": e.value, "monthly": e.value2}
        for e in _entries_by_kind(spotify, "cross_scale")
    ]

    companion_entry = next(iter(_entries_by_kind(spotify, "companion")), None)
    gravity_entry = next(iter(_entries_by_kind(apple, "gravity")), None)
    companion = (
        {"name": companion_entry.label, "since": companion_entry.value,
         "stat": companion_entry.value2, "note": companion_entry.note}
        if companion_entry is not None else None
    )
    gravity = (
        {"name": gravity_entry.label, "since": gravity_entry.value,
         "stat": gravity_entry.value2, "note": gravity_entry.note}
        if gravity_entry is not None else None
    )

    return {
        "current_period_label": current_period_label,
        "current_period_artists": current_period_artists,
        "yearly": yearly,
        "monthly_bars": monthly_bars,
        "monthly_current": monthly_current,
        "cross_scale": cross_scale,
        "companion": companion,
        "gravity": gravity,
        "spotify_archive": _archive_rows(spotify),
        "apple_archive": _archive_rows(apple),
        "music_updated": updated.strftime("%Y.%m.%d") if updated else "",
    }


def assemble_coding(board):
    """组装 Coding Index 上下文：项目 / 原则 / 实验。"""
    projects = list(
        CodingProject.objects.filter(board=board, is_active=True).order_by("order", "pk")
    )
    principles = list(
        CodingPrinciple.objects.filter(board=board).order_by("order", "pk")
    )
    experiments = list(
        CodingExperiment.objects.filter(board=board).order_by("-date", "pk")
    )
    return {
        "projects": projects,
        "principles": principles,
        "experiments": experiments,
    }


ASSEMBLERS = {
    "skateboard": assemble_skateboard,
    "music": assemble_music,
    "coding": assemble_coding,
}


def assemble_context(board):
    """按 board.slug 分派对应 assembler；未知 slug 直接 KeyError（调用方已 404）。"""
    return ASSEMBLERS[board.slug](board)
