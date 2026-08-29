from pathlib import Path

from django.test import SimpleTestCase


class ContainerShellScriptContractTests(SimpleTestCase):
    def test_deployment_shell_scripts_are_lf_only(self):
        project_root = Path(__file__).resolve().parents[2]
        scripts = tuple((project_root / "deploy").rglob("*.sh"))

        self.assertTrue(scripts)
        for script in scripts:
            with self.subTest(script=script.relative_to(project_root)):
                self.assertNotIn(b"\r\n", script.read_bytes())

    def test_container_builds_defensively_strip_carriage_returns(self):
        project_root = Path(__file__).resolve().parents[2]
        app_dockerfile = (project_root / "Dockerfile").read_text(encoding="utf-8")
        mongo_dockerfile = (project_root / "deploy/mongo/Dockerfile").read_text(
            encoding="utf-8"
        )

        self.assertIn("sed -i 's/\\r$//'", app_dockerfile)
        self.assertIn("sed -i 's/\\r$//'", mongo_dockerfile)
