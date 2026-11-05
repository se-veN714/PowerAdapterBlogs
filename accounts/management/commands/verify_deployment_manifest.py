from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from deploy.manifest import verify_manifest


class Command(BaseCommand):
    help = "Verify that the runtime source tree matches the release manifest."

    def add_arguments(self, parser):
        parser.add_argument(
            "--manifest",
            default="deploy/production-manifest.json",
            help="Path to the release manifest relative to the project root.",
        )

    def handle(self, *args, **options):
        project_root = Path(__file__).resolve().parents[3]
        manifest_path = project_root / options["manifest"]
        if not manifest_path.is_file():
            raise CommandError(f"deployment manifest not found: {manifest_path}")
        try:
            problems, unexpected = verify_manifest(project_root, manifest_path)
        except (OSError, ValueError) as exc:
            raise CommandError(f"deployment manifest is invalid: {exc}") from exc
        for relative in unexpected:
            self.stdout.write(self.style.WARNING(f"unexpected runtime file: {relative}"))
        if problems:
            for problem in problems:
                self.stderr.write(problem)
            raise CommandError(
                f"deployment manifest mismatch: {len(problems)} missing or changed files"
            )
        self.stdout.write(self.style.SUCCESS("deployment manifest verified"))
