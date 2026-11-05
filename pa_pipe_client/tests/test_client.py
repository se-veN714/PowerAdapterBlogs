from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import yaml
from fastapi.testclient import TestClient

from app.config import Settings
from app.generator import generate_profile
from app.main import create_app
from app.services import read_log_tail


class ClientTests(unittest.TestCase):
    def make_settings(self, root: Path, template: Path, secret: Path, log: Path) -> Settings:
        return Settings(
            tunnel_home=root,
            start_script=root / "Start-PA-pipe.ps1",
            log_file=log,
            secret_file=secret,
            clash_exe=root / "Clash Party.exe",
            profile_template=template,
            generated_dir=root / "generated",
        )

    def test_generator_locks_the_local_handoff_and_disables_tun(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            template = root / "profile.yaml"
            template.write_text(yaml.safe_dump({
                "mixed-port": 9999,
                "tun": {"enable": True},
                "proxies": [{"name": "PA-pipe", "type": "wireguard", "private-key": "private", "peers": [{"server": "old", "port": 443, "public-key": "server"}]}],
            }), encoding="utf-8")
            settings = self.make_settings(root, template, root / "secret", root / "log")
            target, contract = generate_profile(settings)
            result = yaml.safe_load(target.read_text(encoding="utf-8"))
            self.assertEqual(result["mixed-port"], 7890)
            self.assertFalse(result["tun"]["enable"])
            self.assertEqual(result["proxies"][0]["peers"][0]["server"], "127.0.0.1")
            self.assertEqual(result["proxies"][0]["peers"][0]["port"], 51821)
            self.assertEqual(contract["wss"], "43.165.174.246:443/TCP")

    def test_log_tail_redacts_secret(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            secret = root / "secret"
            log = root / "log"
            secret.write_text("secret-path", encoding="utf-8")
            log.write_text("connected secret-path\nready\n", encoding="utf-8")
            settings = self.make_settings(root, root / "profile", secret, log)
            self.assertEqual(read_log_tail(settings), ["connected <REDACTED>", "ready"])

    def test_health_and_profile_download(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            template = root / "profile.yaml"
            template.write_text("proxies:\n  - name: PA-pipe\n    type: wireguard\n    private-key: private\n    peers:\n      - server: old\n        port: 443\n", encoding="utf-8")
            settings = self.make_settings(root, template, root / "secret", root / "log")
            client = TestClient(create_app(settings))
            self.assertEqual(client.get("/api/health").json(), {"status": "ok"})
            response = client.post("/api/profile")
            self.assertEqual(response.status_code, 200)
            download = client.get(response.json()["download_url"])
            self.assertEqual(download.status_code, 200)
            self.assertIn(b"127.0.0.1", download.content)


if __name__ == "__main__":
    unittest.main()
