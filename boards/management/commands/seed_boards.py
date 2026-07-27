"""种子数据：初始化 3 个首页板块。

用法：
    python manage.py seed_boards              # 创建默认 3 板块
    python manage.py seed_boards --dry-run    # 预览模式
"""

from django.core.management.base import BaseCommand

from Blogs.models import Category
from boards.models import Board

SEED_BOARDS = [
    {
        'slug': 'skateboard',
        'name': 'Skateboard',
        'description': (
            '基础、保持与坚持。<br>'
            '关于滑板的一切：关于平衡、起跳<br>'
            '以及反复摔倒的瞬间。'
        ),
        'glitch_color': '#ff4d5e',
        'keywords': 'Ollie,Grind,Flip',
        'sort_order': 1,
        'category_index': 1,
    },
    {
        'slug': 'music',
        'name': 'Music',
        'description': (
            '节律、节奏与共鸣。<br>'
            '记录我听到的、创作的，<br>'
            '以及那些打动我的声音。'
        ),
        'glitch_color': '#b794f4',
        'keywords': 'Melody,Harmony,Noise',
        'sort_order': 2,
        'category_index': 2,
    },
    {
        'slug': 'coding',
        'name': 'Coding',
        'description': (
            '代码、结构与可能性的<br>'
            '在逻辑中构建想法，<br>'
            '在系统中寻找自由。'
        ),
        'glitch_color': '#f6ad55',
        'keywords': 'Logic,Struct,Create',
        'sort_order': 3,
        'category_index': 3,
    },
]


class Command(BaseCommand):
    """初始化首页板块种子数据。"""

    help = "创建默认的 3 个首页 Editorial 板块"

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run', action='store_true', default=False,
            help='预览模式，不实际写入',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']

        for board_data in SEED_BOARDS:
            board_data = board_data.copy()
            cat_idx = board_data.pop('category_index')
            try:
                board_data['category'] = Category.objects.get(id=cat_idx)
            except Category.DoesNotExist:
                self.stdout.write(
                    self.style.WARNING(
                        f"Category id={cat_idx} 不存在，"
                        f"跳过 {board_data['name']}"
                    )
                )
                continue

            obj, created = Board.objects.update_or_create(
                slug=board_data['slug'],
                defaults=board_data,
            )
            action = '创建' if created else '更新'
            self.stdout.write(
                self.style.SUCCESS(
                    f"{action}: [{board_data['sort_order']:02d}] "
                    f"{board_data['name']} "
                    f"(color={board_data['glitch_color']}, "
                    f"keywords={board_data['keywords']})"
                )
            )

        if dry_run:
            self.stdout.write(
                self.style.WARNING('\n[--dry-run] 以上为预览，未实际写入')
            )
