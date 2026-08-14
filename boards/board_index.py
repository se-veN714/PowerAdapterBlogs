"""Board Index 分派上下文组装。

按 BOARD_INDEX_BACKEND_GUIDE.md §2.3，单个 `boards` app 内用 `Board.slug` 分派
三板（skateboard / music / coding）内容与模板。`ASSEMBLERS` 是 dict 分派表，
避免 `if/elif` 硬编码 slug 字符串散落各处；`BOARD_TEMPLATES` 给出每板模板。

内容仅由 superuser 在 Admin 维护（决策 5）；本模块只读取，不写入、不鉴权。
公开过滤（如 `SkateClip.is_public`）在查询层完成，避免泄露非公开内容。
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from django.urls import reverse

from boards.models import (
    AppleRecord,
    CodingExperiment,
    CodingPrinciple,
    CodingProject,
    SkateClip,
    SkateClipMediaState,
    SkateHomie,
    SpotifyRecord,
)

__all__ = [
    "ASSEMBLERS",
    "BOARD_TEMPLATES",
    "assemble_context",
    "prepare_skate_clips",
]


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


def prepare_skate_clips(clips):
    """Decorate clips and group each display cycle as 2 portrait + 3 landscape.

    为每条 clip 附加 ready media 派生 URL（main_url/preview_url/poster_url）；
    media 非 ready 时这些属性为空串，模板回退到旧 video_url/thumbnail_url。
    """
    prepared = list(clips)
    for index, clip in enumerate(prepared, start=1):
        clip.duration_display = _format_duration(clip.duration)
        clip.display_index = f"{index:02d}"
        _attach_media_urls(clip)

    return [
        {
            "vertical": prepared[start : start + 2],
            "horizontal": prepared[start + 2 : start + 5],
        }
        for start in range(0, len(prepared), 5)
    ]


def _attach_media_urls(clip):
    """把 ready SkateClipMedia 的派生资源 URL 附加到 clip 对象上。

    模板优先使用这些属性；为空时回退到旧 video_url/thumbnail_url。
    """
    clip.main_url = ""
    clip.preview_url = ""
    clip.poster_url = ""
    try:
        media = clip.media
    except AttributeError:
        return
    if media is None or media.state != SkateClipMediaState.READY:
        return
    if media.main_file:
        clip.main_url = media.main_file.url
    if media.preview_file:
        clip.preview_url = media.preview_file.url
    if media.poster_file:
        clip.poster_url = media.poster_file.url


def assemble_skateboard(board):
    """组装 Skateboard Index 上下文：成员节点 + 首个成员的公开片段。

    选中状态完全由前端控制（默认首个节点），不依赖数据库 is_active 字段。
    """
    homies = list(SkateHomie.objects.filter(board=board).select_related("board"))
    for homie in homies:
        # 模板只读取这些属性，分派层附加，避免污染模型字段
        homie.state = ""  # active 视觉态由前端 JS 控制
        homie.avatar_url = homie.avatar.url if homie.avatar else ""
        homie.line_url = _homie_line_url(board.slug, homie.node_index)

    selected = homies[0] if homies else None

    clip_list = []
    if selected is not None:
        clip_list = list(
            SkateClip.objects.filter(homie=selected, is_public=True)
            .select_related("homie", "media")
            .order_by("order", "pk")
        )
    clip_groups = prepare_skate_clips(clip_list)

    return {
        "homies": homies,
        "selected_homie": selected,
        "clip_list": clip_list,
        "clip_groups": clip_groups,
        # open_node_url 保持占位（决策 5：无公开投稿），模板据此禁用按钮
        "open_node_url": None,
    }


def _safe_int(text):
    """从可能含逗号/单位的文本提取整数（如 '32,481 MIN' → 32481）。"""
    if not text:
        return 0
    digits = "".join(ch for ch in str(text) if ch.isdigit())
    return int(digits) if digits else 0


_MONTH_ABBR = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN",
               "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]


@dataclass
class _RecordGroup:
    """平铺记录按 (year, month) 分组后的快照视图，保持 assembler 接口兼容。

    records 是同一 (year, month) 内的记录列表（已按 display_order 排序），
    替代旧 Snapshot.entries.all() 的遍历语义。
    """
    title: str
    scope: str
    year: int
    month: int | None
    records: list
    updated_at: datetime


def _group_by_period(records):
    """按 (year, month) 分组，返回按 (-year, -month) 排序的 _RecordGroup 列表。"""
    groups = defaultdict(list)
    for r in records:
        key = (r.year, r.month or 0)
        groups[key].append(r)
    result = []
    for key in sorted(groups.keys(), reverse=True):
        recs = groups[key]
        first = recs[0]
        result.append(_RecordGroup(
            title=first.title,
            scope=first.scope,
            year=first.year,
            month=first.month,
            records=recs,
            updated_at=max(r.updated_at for r in recs),
        ))
    return result


def _group_month_label(group):
    """_RecordGroup → 月度缩写（有 month）或年份标签。"""
    if group.month:
        idx = group.month - 1
        if 0 <= idx < len(_MONTH_ABBR):
            return _MONTH_ABBR[idx]
    return str(group.year)


def _archive_rows(groups):
    """将分组序列化为 archive 行（label / value / tags / period），供模板遍历。

    value 优先取 kind='total' 的条目，否则取 display_order 最小者；
    tags 取 kind='tag' 的条目 label 拼接。空组给出安全空值。
    """
    rows = []
    for g in groups:
        entries = g.records
        primary = next((e for e in entries if e.kind == "total"), None)
        if primary is None and entries:
            primary = entries[0]
        if primary and primary.minutes is not None:
            value = f"{primary.minutes:,} MIN"
        else:
            value = f"{primary.value} {primary.unit}".strip() if primary else ""
        tags = " / ".join(e.label for e in entries if e.kind == "tag") if entries else ""
        label = f"{g.year}.{g.month:02d}" if g.month else str(g.year)
        rows.append({"label": label, "value": value, "tags": tags, "period": label})
    return rows


def _cover_url(record):
    return record.cover.url if record.cover else ""


def _minutes(record):
    if record.minutes is not None:
        return record.minutes
    return _safe_int(record.value)


def _artist_rows(records, *kinds):
    selected = [record for record in records if record.kind in kinds]
    selected.sort(key=lambda record: (record.rank or record.display_order, record.pk))
    return [
        {
            "rank": record.rank or index,
            "name": record.label,
            "minutes_display": f"{_minutes(record):,}" if _minutes(record) else "",
            "plays": record.play_count,
            "tag": record.value2 or (record.value if record.kind == "period_artist" else ""),
            "cover_url": _cover_url(record),
            "external_url": record.external_url,
        }
        for index, record in enumerate(selected, start=1)
    ]


def _track_rows(records):
    selected = [record for record in records if record.kind == "top_track"]
    selected.sort(key=lambda record: (record.rank or record.display_order, record.pk))
    return [
        {
            "rank": record.rank or index,
            "title": record.label,
            "artist": record.value,
            "plays": record.play_count,
            "minutes_display": f"{_minutes(record):,}" if _minutes(record) else "",
            "cover_url": _cover_url(record),
            "external_url": record.external_url,
        }
        for index, record in enumerate(selected, start=1)
    ]


def assemble_music(board):
    """组装 Music Index 上下文：全部叙事区数据驱动。

    平铺 Record 按 (year, month) 分组重建快照视图。编辑性条目（core_artist /
    period_artist / cross_scale / companion / gravity）仅挂在各 provider 的
    最新周期记录上。
    """
    spotify_records = list(
        SpotifyRecord.objects.filter(board=board)
        .order_by("-year", "-month", "display_order", "pk")
    )
    apple_records = list(
        AppleRecord.objects.filter(board=board)
        .order_by("-year", "-month", "display_order", "pk")
    )

    updated = None
    for r in spotify_records + apple_records:
        if updated is None or r.updated_at > updated:
            updated = r.updated_at

    spotify_groups = _group_by_period(spotify_records)
    apple_groups = _group_by_period(apple_records)

    latest_spotify = spotify_groups[0] if spotify_groups else None
    latest_apple = apple_groups[0] if apple_groups else None

    # 当前周期（hero + monthly current）：来自最新 Apple 月度组
    current_period_label = None
    current_period_artists = []
    if latest_apple is not None:
        current_period_label = f"{latest_apple.year}.{latest_apple.month:02d}"
        current_period_artists = [
            {"name": r.label, "tag": r.value}
            for r in latest_apple.records if r.kind == "period_artist"
        ]

    # 年度概览：来自最新 Spotify 年度组
    yearly = None
    if latest_spotify is not None:
        entries = latest_spotify.records
        total = next((e for e in entries if e.kind == "total"), None)
        total_str = (
            f"{_minutes(total):,} MIN" if total and _minutes(total)
            else f"{total.value} {total.unit}".strip() if total else ""
        )
        core = sorted(
            (e for e in entries if e.kind in {"core_artist", "top_artist"}),
            key=lambda e: e.rank or _safe_int(e.value),
        )
        core_artists = [
            {"rank": entry.rank or index, "name": entry.label}
            for index, entry in enumerate(core, start=1)
        ]
        tags = " / ".join(e.label for e in entries if e.kind == "tag")
        yearly = {
            "year": latest_spotify.year,
            "total": total_str,
            "core_artists": core_artists,
            "tags": tags,
        }

    spotify_top_artists = (
        _artist_rows(latest_spotify.records, "top_artist", "core_artist")
        if latest_spotify else []
    )
    spotify_top_tracks = (
        _track_rows(latest_spotify.records) if latest_spotify else []
    )
    spotify_summary = None
    if latest_spotify is not None:
        entries = latest_spotify.records
        total = next((entry for entry in entries if entry.kind == "total"), None)
        unique_artists = next(
            (entry for entry in entries if entry.kind == "unique_artists"), None
        )
        unique_tracks = next(
            (entry for entry in entries if entry.kind == "unique_tracks"), None
        )
        spotify_summary = {
            "year": latest_spotify.year,
            "minutes_display": f"{_minutes(total):,}" if total else "",
            "unique_artists": _safe_int(unique_artists.value) if unique_artists else None,
            "unique_tracks": _safe_int(unique_tracks.value) if unique_tracks else None,
            "tags": " / ".join(
                entry.label for entry in entries if entry.kind == "tag"
            ),
        }

    # 月度柱状：来自 Apple 组（按时间升序，pct 相对最高）
    monthly_bars = []
    monthly_current = None
    if apple_groups:
        ordered = sorted(apple_groups, key=lambda g: (g.year, g.month or 0))
        minutes = []
        for g in ordered:
            t = next((e for e in g.records if e.kind == "total"), None)
            minutes.append(_minutes(t) if t else 0)
        max_min = max(minutes) if minutes else 1
        for g, m in zip(ordered, minutes):
            monthly_bars.append({
                "month_label": _group_month_label(g),
                "minutes": m,
                "minutes_display": "{:,}".format(m),
                "pct": round(m / max_min * 100) if max_min else 0,
                "is_current": g is latest_apple,
            })
        if latest_apple is not None:
            cur = next((e for e in latest_apple.records
                        if e.kind == "total"), None)
            monthly_current = {
                "label": current_period_label,
                "minutes_display": (
                    "{:,}".format(_minutes(cur)) if cur else "0"),
            }


    apple_months = [
        {
            "year": group.year,
            "month": group.month,
            "label": f"{group.year}.{group.month:02d}" if group.month else str(group.year),
            "minutes": next(
                (
                    _minutes(record)
                    for record in group.records
                    if record.kind == "total"
                ),
                0,
            ),
            "minutes_display": "{:,}".format(
                next(
                    (
                        _minutes(record)
                        for record in group.records
                        if record.kind == "total"
                    ),
                    0,
                )
            ),
            "is_current": group is latest_apple,
        }
        for group in sorted(apple_groups, key=lambda item: (item.year, item.month or 0))
    ]
    apple_current = None
    if latest_apple is not None:
        total = next(
            (record for record in latest_apple.records if record.kind == "total"),
            None,
        )
        apple_current = {
            "label": current_period_label,
            "minutes_display": f"{_minutes(total):,}" if total else "0",
            "top_artists": _artist_rows(
                latest_apple.records,
                "top_artist",
                "period_artist",
            ),
            "top_tracks": _track_rows(latest_apple.records),
        }

    # 跨尺度关系 / 常伴 / 近期引力：平铺过滤（编辑性条目仅挂在最新周期）
    cross_scale = [
        {"name": r.label, "yearly": r.value, "monthly": r.value2}
        for r in spotify_records if r.kind == "cross_scale"
    ]

    companion_entry = next(
        (r for r in spotify_records if r.kind == "companion"), None)
    gravity_entry = next(
        (r for r in apple_records if r.kind == "gravity"), None)
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
        "spotify_summary": spotify_summary,
        "spotify_top_artists": spotify_top_artists,
        "spotify_top_tracks": spotify_top_tracks,
        "monthly_bars": monthly_bars,
        "monthly_current": monthly_current,
        "apple_months": apple_months,
        "apple_current": apple_current,
        "cross_scale": cross_scale,
        "companion": companion,
        "gravity": gravity,
        "spotify_archive": _archive_rows(spotify_groups),
        "apple_archive": _archive_rows(apple_groups),
        "music_updated": updated.strftime("%Y.%m.%d") if updated else "",
    }


def assemble_coding(board):
    """组装 Coding Index 上下文：项目 / 原则 / 实验。"""
    project_records = list(
        CodingProject.objects.filter(board=board, is_active=True).order_by("order", "pk")
    )
    projects = []
    for project in project_records:
        repository_url = project.repository_url
        demo_url = project.demo_url
        if project.project_type == CodingProject.ProjectType.GITHUB:
            repository_url = repository_url or project.url
        elif project.project_type == CodingProject.ProjectType.EXTERNAL:
            demo_url = demo_url or project.url
        projects.append(
            {
                "index": project.index,
                "name": project.name,
                "description": project.description,
                "stack": project.stack,
                "year": project.year,
                "status": project.status,
                "project_type": project.project_type,
                "repository_url": repository_url,
                "demo_url": demo_url,
                "cover_url": _cover_url(project),
                "is_featured": project.is_featured,
                "url": repository_url or demo_url,
            }
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
