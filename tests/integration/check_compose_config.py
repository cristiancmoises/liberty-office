"""Interpret real Compose entrypoints without contacting Docker or starting services.

Run with: python3 tests/integration/check_compose_config.py
Requires the Docker CLI and Compose v2, but not a daemon or its socket.
"""

import json
import os
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from liberty.config import Settings

ROOT = Path(__file__).resolve().parents[2]
ENTRYPOINTS = [
    ("compose.yaml", "office"),
    ("deploy/compose.bluegreen.yaml", "candidate"),
]


def configured_service(filename, service, overrides=None):
    environment = {
        "PATH": os.environ["PATH"],
        "DOCKER_CONFIG": "/nonexistent-liberty-compose-test-config",
        "PUBLIC_ORIGIN": "https://office.example.test",
        "EDITOR_ORIGIN": "https://editoffice.example.test",
        "DEMO_EDITOR_ORIGIN": "https://demo-editoffice.example.test",
        "LIBERTY_QUALIFIED_IMAGE": "sha256:" + "a" * 64,
        "LIBERTY_NEXT_DATA_PATH": "/synthetic/not-created",
    } | (overrides or {})
    command = [
        "docker",
        "compose",
        "--env-file",
        "/dev/null",
        "-f",
        str(ROOT / filename),
        "--profile",
        "accounts",
        "config",
        "--format",
        "json",
    ]
    result = subprocess.run(
        command, env=environment, check=True, capture_output=True, text=True
    )
    return json.loads(result.stdout)["services"][service]


class ComposeAccountConfiguration(unittest.TestCase):
    def test_invitation_and_bootstrap_default_stays_separate_from_public_quota(self):
        for filename, service in ENTRYPOINTS:
            with self.subTest(entrypoint=filename):
                environment = configured_service(filename, service)["environment"]
                with patch.dict(os.environ, environment, clear=True):
                    settings = Settings.from_env()
                self.assertEqual(settings.default_quota, 5368709120)
                self.assertEqual(settings.signup_quota, 100000000)

    def test_tightened_signup_bounds_reach_the_application(self):
        overrides = {
            "PUBLIC_SIGNUP_ENABLED": "true",
            "SIGNUP_ATTEMPTS": "1",
            "SIGNUP_SUCCESSES": "2",
            "SIGNUP_WINDOW_SECONDS": "120",
            "SIGNUP_SLOTS": "100",
            "SIGNUP_PENDING_TTL_SECONDS": "7200",
        }
        for filename, service in ENTRYPOINTS:
            with self.subTest(entrypoint=filename):
                environment = configured_service(filename, service, overrides)[
                    "environment"
                ]
                with patch.dict(os.environ, environment, clear=True):
                    settings = Settings.from_env()
                self.assertTrue(settings.public_signup)
                self.assertEqual(settings.signup_attempts, 1)
                self.assertEqual(settings.signup_successes, 2)
                self.assertEqual(settings.signup_window, 120)
                self.assertEqual(settings.signup_slots, 100)
                self.assertEqual(settings.signup_pending_ttl, 7200)

    def test_operator_selected_previous_image_reaches_the_build(self):
        service = configured_service(
            "compose.yaml",
            "office",
            {"RETAINED_PUBLIC_IMAGE": "liberty-office:verified-previous"},
        )
        self.assertEqual(
            service["build"].get("args", {}).get("RETAINED_PUBLIC_IMAGE"),
            "liberty-office:verified-previous",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
