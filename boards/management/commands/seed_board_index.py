"""种子数据：填充 Board Index 三块内容模型（Skateboard / Music / Coding）。

本命令只写内容模型，不写 `Board` 行（由 `seed_boards` 负责）。内容模型的
`board` 由模型类型固定（见 boards.models），此处显式传入对应 Board 即可。

用法：
    python manage.py seed_board_index              # 幂等填充（已存在则跳过对应板块）
    python manage.py seed_board_index --reset       # 清空三块内容后重建
    python manage.py seed_board_index --dry-run     # 预览将要写入的数量，不落库
"""

from datetime import timedelta

from django.core.management.base import BaseCommand
from faker import Faker

from boards.models import (
    AppleRecord,
    CodingExperiment,
    CodingPrinciple,
    CodingProject,
    ClipCategory,
    ClipStatus,
    HudType,
    SkateClip,
    SkateHomie,
    SpotifyRecord,
    Board,
)

FAKE = Faker("en_US")

SKATE_TRICKS = [
    "FAKIE FS HEEL", "BS FLIP", "OLLIE", "TRE FLIP", "KICKFLIP",
    "HEELFLIP", "HARDLLIP", "360 FLIP", "NOSE SLIDE", "TAIL SLIDE",
    "CROOKED GRIND", "SMITH GRIND", "BLUNT SLIDE", "LASER FLIP",
]
SKATE_SPOTS = ["VENICE BOWL", "SF EMBARCADERO", "L.A. STREET LEDGE",
               "BROOKLYN BANKS", "MACBA", "LEVIS PLAZA", "THE BERMS"]
HUD_LABELS = {
    HudType.ARC: "ANGLE {:.0f}°",
    HudType.SPEED: "SPD {:.1f}M/S",
    HudType.MEASURE: "HEIGHT {:.2f}M",
    HudType.RING: "ROTATION {:.0f}°",
}

CODING_PROJECTS = [
    ("MONITOR", "Remote training log viewer", "PYTHON / SSE", "IN USE"),
    ("POWERADAPTER", "Personal publishing and archive system", "DJANGO / MONGO", "ACTIVE"),
    ("CREDITS", "AI tool usage dashboard", "HTML / API", "ACTIVE"),
    ("SECURITY LOG", "Operational audit trail", "MONGO / HMAC", "STABLE"),
    ("GLITCH UI", "Visual noise and scramble toolkit", "JS / CANVAS", "WIP"),
    ("TAILSCALE VPN", "Private admin access bridge", "LINUX / TS", "STABLE"),
]
CODING_PRINCIPLES = [
    ("NEED BEFORE FRAMEWORK",
     "Start from the problem.\nLet the structure emerge from use."),
    ("FIRST WORKING, THEN CLEAR",
     "Build a form that moves.\nRefine until the relations become readable."),
    ("SMALL TOOLS, LONG LIFE",
     "Keep the scope open enough to evolve,\nand small enough to stay useful."),
]
CODING_EXPERIMENTS = [
    "HTMX partial refresh experiment",
    "MongoDB logging migration",
    "Private admin access with Tailscale",
    "Unity IL2CPP mod research",
]


def _get_board(slug):
    """按 slug 取固定归属 Board（内容模型创建前需先跑 seed_boards）。"""
    return Board.objects.get(slug=slug)


class Command(BaseCommand):
    """填充 Board Index 三块内容模型（Skateboard / Music / Coding）。"""

    help = "填充 Skateboard / Music / Coding 三块 Board Index 内容模型"

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset", action="store_true", default=False,
            help="清空三块内容后重建（默认：已存在则跳过）",
        )
        parser.add_argument(
            "--dry-run", action="store_true", default=False,
            help="预览模式，不实际写入",
        )

    # -- Skateboard ---------------------------------------------------------
    def _seed_skateboard(self, board, dry_run, reset):
        if SkateHomie.objects.filter(board=board).exists():
            if not reset:
                self.stdout.write(self.style.WARNING(
                    "skateboard 已有内容，跳过（使用 --reset 重建）"))
                return
            SkateClip.objects.filter(homie__board=board).delete()
            SkateHomie.objects.filter(board=board).delete()

        count = 7
        for i in range(count):
            node_index = i
            name = FAKE.unique.first_name().upper()
            homie = None
            if not dry_run:
                homie = SkateHomie.objects.create(
                    board=board,
                    node_index=node_index,
                    name=name,
                    call_sign=FAKE.unique.bothify("?#??").upper(),
                    location=FAKE.city().upper(),
                    joined_at=FAKE.date_between(start_date="-6y", end_date="-1y"),
                    role_label=FAKE.random_element(
                        ["HOST", "CREW", "REGULAR", "GUEST"]),
                    is_active=(i == 0),
                )
            else:
                homie = None
            clip_n = FAKE.random_int(min=2, max=4)
            for c in range(clip_n):
                if dry_run:
                    continue
                hud = FAKE.random_element(list(HudType.values))
                SkateClip.objects.create(
                    homie=homie,
                    order=c,
                    title=FAKE.random_element(SKATE_TRICKS),
                    category=FAKE.random_element(list(ClipCategory.values)),
                    spot=FAKE.random_element(SKATE_SPOTS),
                    filmed_at=FAKE.date_between(start_date="-2y", end_date="today"),
                    duration=timedelta(seconds=FAKE.random_int(min=2, max=15)),
                    status=FAKE.random_element(list(ClipStatus.values)),
                    notes=FAKE.sentence(nb_words=4).upper().rstrip("."),
                    hud_type=hud,
                    hud_label=HUD_LABELS[hud].format(FAKE.random_int(min=180, max=360)),
                    timecode="00:00:{:02d}:{:02d}".format(
                        FAKE.random_int(0, 2), FAKE.random_int(0, 20)),
                    is_public=True,
                )
        self.stdout.write(self.style.SUCCESS(
            f"skateboard: {count} homies（每个 2-4 clips），dry_run={dry_run}"))

    # -- Music --------------------------------------------------------------
    def _artist_names(self, n):
        """生成 n 个不重复的艺人名（Faker first_name 大写）。"""
        names = []
        while len(names) < n:
            nm = FAKE.unique.first_name().upper()
            if nm not in names:
                names.append(nm)
        return names

    def _seed_music(self, board, dry_run, reset):
        if dry_run:
            self.stdout.write(self.style.SUCCESS(
                "music: 3 Spotify 年度 + 3 Apple 月度记录（含 core_artist / "
                "period_artist / cross_scale / companion / gravity），dry_run=True"))
            return
        if SpotifyRecord.objects.filter(board=board).exists():
            if not reset:
                self.stdout.write(self.style.WARNING(
                    "music 已有内容，跳过（使用 --reset 重建）"))
                return
            AppleRecord.objects.filter(board=board).delete()
            SpotifyRecord.objects.filter(board=board).delete()

        genres = ["POST-ROCK", "AMBIENT", "EXPERIMENTAL", "NOISE",
                  "ATMOSPHERIC", "EMOTIONAL", "MELODIC", "CINEMATIC"]
        scales_yearly = ["STABLE", "HIGH", "—", "RISING", "CONCENTRATED"]
        scales_monthly = ["CONTINUOUS", "RISING", "CONCENTRATED", "STEADY", "PEAKING"]

        # Spotify 年度记录（yearly）
        for year in (2023, 2024, 2025):
            title = f"Spotify Wrapped {year}"
            SpotifyRecord.objects.create(
                board=board, title=title, scope="yearly", year=year,
                label="TOTAL MINUTES",
                value="{:,}".format(FAKE.random_int(20000, 35000)),
                unit="MIN", kind="total", display_order=0)
            for j, genre in enumerate(
                    FAKE.random_elements(elements=genres, length=3, unique=True)):
                SpotifyRecord.objects.create(
                    board=board, title=title, scope="yearly", year=year,
                    label=genre, value="", unit="", kind="tag",
                    display_order=j + 1)

        # Apple Music 月度记录（monthly）
        for year, month in [(2026, 7), (2026, 6), (2026, 5)]:
            title = f"Apple Music {year}.{month:02d}"
            AppleRecord.objects.create(
                board=board, title=title, scope="monthly", year=year, month=month,
                label="TOTAL MINUTES",
                value="{:,}".format(FAKE.random_int(14000, 23000)),
                unit="MIN", kind="total", display_order=0)
            for j, tag in enumerate(
                    FAKE.random_elements(
                        elements=["LONG FORM", "HIGH REPEAT", "DIVERSE",
                                  "FOCUS", "NEW PATTERNS"], length=2, unique=True)):
                AppleRecord.objects.create(
                    board=board, title=title, scope="monthly", year=year, month=month,
                    label=tag, value="", unit="", kind="tag",
                    display_order=j + 1)

        # 编辑性条目：仅挂在最新周期记录上（assembler 只读取最新周期）
        spotify_title = "Spotify Wrapped 2025"
        apple_title = "Apple Music 2026.07"

        # 年度核心艺人（Top 5，value=排名）
        for rank, name in enumerate(self._artist_names(5), start=1):
            SpotifyRecord.objects.create(
                board=board, title=spotify_title, scope="yearly", year=2025,
                label=name, value=str(rank), kind="core_artist", display_order=rank)
        # 最长常伴
        SpotifyRecord.objects.create(
            board=board, title=spotify_title, scope="yearly", year=2025,
            label=self._artist_names(1)[0],
            value="SINCE 2022",
            value2="{:,} MIN / 3 YEARS".format(FAKE.random_int(5000, 9000)),
            kind="companion",
            note=FAKE.sentence(nb_words=6).upper().rstrip("."),
            display_order=10)
        # 跨尺度关系（3 条：value=年度描述，value2=月度描述）
        for i in range(3):
            SpotifyRecord.objects.create(
                board=board, title=spotify_title, scope="yearly", year=2025,
                label=self._artist_names(1)[0],
                value=FAKE.random_element(elements=scales_yearly),
                value2=FAKE.random_element(elements=scales_monthly),
                kind="cross_scale", display_order=i)

        # 当前周期艺人（hero + monthly current，4 条，value=风格标签）
        for i, name in enumerate(self._artist_names(4), start=1):
            AppleRecord.objects.create(
                board=board, title=apple_title, scope="monthly", year=2026, month=7,
                label=name, value=FAKE.random_element(elements=genres),
                kind="period_artist", display_order=i)
        # 近期引力
        AppleRecord.objects.create(
            board=board, title=apple_title, scope="monthly", year=2026, month=7,
            label=self._artist_names(1)[0],
            value="SINCE 2026.04",
            value2="{:,} MIN / 4 MONTHS".format(FAKE.random_int(4000, 8000)),
            kind="gravity",
            note=FAKE.sentence(nb_words=5).upper().rstrip("."),
            display_order=10)

        self.stdout.write(self.style.SUCCESS(
            "music: 3 Spotify 年度 + 3 Apple 月度记录（含 core_artist / "
            "period_artist / cross_scale / companion / gravity 条目）"))

    # -- Coding -------------------------------------------------------------
    def _seed_coding(self, board, dry_run, reset):
        if CodingProject.objects.filter(board=board).exists():
            if not reset:
                self.stdout.write(self.style.WARNING(
                    "coding 已有内容，跳过（使用 --reset 重建）"))
                return
            CodingExperiment.objects.filter(board=board).delete()
            CodingPrinciple.objects.filter(board=board).delete()
            CodingProject.objects.filter(board=board).delete()

        if not dry_run:
            for i, (pname, desc, stack, status) in enumerate(CODING_PROJECTS[:4]):
                CodingProject.objects.create(
                    board=board, index=i, name=pname, description=desc,
                    stack=stack, year=2026, status=status,
                    url=FAKE.url(), is_active=True, order=i)
            for i, (title, body) in enumerate(CODING_PRINCIPLES):
                CodingPrinciple.objects.create(
                    board=board, index=i, title=title, body=body, order=i)
            for i, title in enumerate(CODING_EXPERIMENTS):
                CodingExperiment.objects.create(
                    board=board,
                    date=FAKE.date_between(start_date="-1y", end_date="today"),
                    title=title, order=i)
        self.stdout.write(self.style.SUCCESS(
            "coding: 4 projects / 3 principles / 4 experiments，dry_run={}".format(
                dry_run)))

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        reset = options["reset"]

        if not dry_run:
            # 内容模型依赖 Board 行存在
            missing = [s for s in ("skateboard", "music", "coding")
                       if not Board.objects.filter(slug=s).exists()]
            if missing:
                self.stderr.write(self.style.ERROR(
                    "缺少 Board 行（slug={}），请先运行 `python manage.py "
                    "seed_boards`".format(missing)))
                return

        targets = [
            ("skateboard", self._seed_skateboard),
            ("music", self._seed_music),
            ("coding", self._seed_coding),
        ]
        for slug, seeder in targets:
            board = _get_board(slug) if not dry_run else None
            seeder(board, dry_run, reset)

        if dry_run:
            self.stdout.write(self.style.WARNING(
                "\n[--dry-run] 以上为预览，未实际写入"))
