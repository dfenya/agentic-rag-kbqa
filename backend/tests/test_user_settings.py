import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.core import config
from app.core.config import Settings


class UserSettingsIsolationTests(unittest.TestCase):
    def test_user_override_does_not_mutate_process_defaults(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base_path = Path(temp_dir) / "settings.json"
            (Path(temp_dir) / "settings_user-a.json").write_text(
                json.dumps({"llm": {"model": "user-model"}}), encoding="utf-8"
            )
            defaults = Settings()
            default_model = defaults.llm.model
            with patch.object(config, "_USER_SETTINGS_PATH", base_path), patch.object(
                config, "_settings", defaults
            ):
                user_settings = config.get_user_settings("user-a")

                self.assertEqual(user_settings.llm.model, "user-model")
                self.assertEqual(config.get_settings().llm.model, default_model)


if __name__ == "__main__":
    unittest.main()
