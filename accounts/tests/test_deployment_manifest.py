import json
import shutil
from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase

from deploy import manifest


class DeploymentManifestTests(SimpleTestCase):
    def setUp(self):
        self.root = Path("manifest_test_tmp")
        if self.root.exists():
            shutil.rmtree(self.root)
        self.root.mkdir()
        (self.root / "config").mkdir()
        (self.root / "manage.py").write_text("initial\n", encoding="utf-8")
        (self.root / "config" / "urls.py").write_text("urlpatterns = []\n", encoding="utf-8")
        self.manifest_path = self.root / "production-manifest.json"

    def tearDown(self):
        if self.root.exists():
            shutil.rmtree(self.root)

    def _write_manifest(self):
        with patch.object(manifest, "DEFAULT_ROOTS", ("manage.py", "config")):
            payload = manifest.build_manifest(self.root)
        self.manifest_path.write_text(json.dumps(payload), encoding="utf-8")

    def test_complete_tree_matches_manifest(self):
        self._write_manifest()
        with patch.object(manifest, "DEFAULT_ROOTS", ("manage.py", "config")):
            self.assertEqual(manifest.verify_manifest(self.root, self.manifest_path), ([], []))

    def test_missing_file_fails_verification(self):
        self._write_manifest()
        (self.root / "config" / "urls.py").unlink()
        with patch.object(manifest, "DEFAULT_ROOTS", ("manage.py", "config")):
            problems, _unexpected = manifest.verify_manifest(self.root, self.manifest_path)
        self.assertEqual(problems, ["missing: config/urls.py"])

    def test_changed_file_fails_verification(self):
        self._write_manifest()
        (self.root / "manage.py").write_text("changed\n", encoding="utf-8")
        with patch.object(manifest, "DEFAULT_ROOTS", ("manage.py", "config")):
            problems, _unexpected = manifest.verify_manifest(self.root, self.manifest_path)
        self.assertEqual(problems, ["changed: manage.py"])
