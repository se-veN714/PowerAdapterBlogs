"""Create local manual-test users for each BoardMembership role."""

import secrets

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from boards.models import Board, BoardMembership

TEST_USERS = (
    ("perm_contributor", BoardMembership.Role.CONTRIBUTOR),
    ("perm_editor", BoardMembership.Role.EDITOR),
    ("perm_reviewer", BoardMembership.Role.REVIEWER),
    ("perm_manager", BoardMembership.Role.MANAGER),
)


class Command(BaseCommand):
    help = "创建 Board 权限手动测试账号（仅用于本地开发）"

    def add_arguments(self, parser):
        parser.add_argument(
            "--board",
            default="coding",
            help="目标 Board slug，默认 coding",
        )
        parser.add_argument(
            "--password",
            help="所有测试账号共用密码；不传则生成随机密码",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("This command is only available when DEBUG=True.")

        board_slug = options["board"]
        password = options["password"] or secrets.token_urlsafe(12)
        try:
            board = Board.objects.get(slug=board_slug, is_active=True)
        except Board.DoesNotExist as exc:
            raise CommandError(f"找不到启用的 Board: {board_slug}") from exc

        if board.category_id is None:
            raise CommandError(f"Board {board_slug} 未绑定 Category，无法测试文章权限")

        user_model = get_user_model()
        for username, role in TEST_USERS:
            user, created = user_model.objects.get_or_create(
                username=username,
                defaults={"email": f"{username}@example.test"},
            )
            user.email = f"{username}@example.test"
            user.is_active = True
            user.is_dashboard_user = True
            user.is_staff = False
            user.is_superuser = False
            user.set_password(password)
            user.save()
            BoardMembership.objects.update_or_create(
                board=board,
                user=user,
                defaults={"role": role, "is_active": True},
            )
            BoardMembership.objects.filter(user=user).exclude(board=board).update(
                is_active=False,
            )
            action = "创建" if created else "更新"
            self.stdout.write(f"{action}: {username} -> {board.slug}/{role}")

        no_board_user, created = user_model.objects.get_or_create(
            username="perm_no_board",
            defaults={"email": "perm_no_board@example.test"},
        )
        no_board_user.email = "perm_no_board@example.test"
        no_board_user.is_active = True
        no_board_user.is_dashboard_user = True
        no_board_user.is_staff = False
        no_board_user.is_superuser = False
        no_board_user.set_password(password)
        no_board_user.save()
        BoardMembership.objects.filter(user=no_board_user).update(is_active=False)
        action = "创建" if created else "更新"
        self.stdout.write(f"{action}: perm_no_board -> 无有效 Membership")

        self.stdout.write(self.style.SUCCESS(f"测试 Board: {board.slug}"))
        self.stdout.write(self.style.SUCCESS(f"统一密码: {password}"))
        self.stdout.write(
            self.style.WARNING("这些账号仅供本地测试，禁止在生产环境运行此命令。")
        )
