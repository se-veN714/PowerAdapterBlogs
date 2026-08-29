"""Create the minimum Board rows required by a genuinely fresh deployment."""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from Blogs.models import Category
from boards.models import Board


FRESH_BOARDS = (
    {
        "slug": "skateboard",
        "name": "Skateboard",
        "description": "基础、保持与坚持。关于滑板的一切。",
        "glitch_color": "#ff4d5e",
        "keywords": "Ollie,Grind,Flip",
        "sort_order": 1,
    },
    {
        "slug": "music",
        "name": "Music",
        "description": "节律、节奏与共鸣。记录听到的、创作的与打动人的声音。",
        "glitch_color": "#b794f4",
        "keywords": "Melody,Harmony,Noise",
        "sort_order": 2,
    },
    {
        "slug": "coding",
        "name": "Coding",
        "description": "代码、结构与可能性。在逻辑中构建想法。",
        "glitch_color": "#f6ad55",
        "keywords": "Logic,Struct,Create",
        "sort_order": 3,
    },
)


class Command(BaseCommand):
    help = "Create minimum Board/Category rows owned by an explicit superuser."

    def add_arguments(self, parser):
        parser.add_argument("--owner-username", required=True)

    @transaction.atomic
    def handle(self, *args, **options):
        user_model = get_user_model()
        try:
            owner = user_model.objects.get(username=options["owner_username"])
        except user_model.DoesNotExist as exc:
            raise CommandError("Bootstrap owner does not exist") from exc
        if not owner.is_active or not owner.is_superuser:
            raise CommandError("Bootstrap owner must be an active superuser")

        created = 0
        preserved = 0
        for defaults in FRESH_BOARDS:
            category, _ = Category.objects.get_or_create(
                name=defaults["name"],
                defaults={"owner": owner, "is_nav": True},
            )
            category_updates = []
            if category.owner_id != owner.pk:
                category.owner = owner
                category_updates.append("owner")
            if not category.is_nav:
                category.is_nav = True
                category_updates.append("is_nav")
            if category_updates:
                category.save(update_fields=category_updates)
            board_defaults = {**defaults, "category": category}
            board, was_created = Board.objects.get_or_create(
                slug=defaults["slug"],
                defaults=board_defaults,
            )
            if was_created:
                created += 1
            else:
                preserved += 1
                if board.category_id is None:
                    board.category = category
                    board.save(update_fields=["category", "updated_at"])
        self.stdout.write(
            self.style.SUCCESS(
                f"Fresh-site bootstrap complete: {created} created, "
                f"{preserved} existing rows preserved; owner={owner.username}."
            )
        )
