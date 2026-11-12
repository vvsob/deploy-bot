import asyncio
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest

import bot


class DeployTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.marker = self.root / "deployed.txt"
        self.script = self.root / "deploy.py"
        self.script.write_text("from pathlib import Path\nPath('deployed.txt').write_text('ok')\n")
        self.config_file = self.root / "config.json"
        self.data = {
            "bot_token": "test-token",
            "operator_ids": [123],
            "script": "deploy.py",
            "shell": [sys.executable],
        }
        self.config_file.write_text(json.dumps(self.data))
        self.deployer = bot.Deployer(bot.load_config(self.config_file))

    def update(self, user_id=123, sender_chat=None):
        replies = []

        async def reply_text(text):
            replies.append(text)

        message = SimpleNamespace(reply_text=reply_text, sender_chat=sender_chat)
        return SimpleNamespace(
            message=message,
            effective_user=SimpleNamespace(id=user_id) if user_id else None,
        ), replies

    async def test_operator_runs_configured_script_in_script_directory(self):
        update, replies = self.update()
        await self.deployer.deploy(update, SimpleNamespace(args=[]))
        self.assertEqual(self.marker.read_text(), "ok")
        self.assertIn("completed", replies[-1].lower())

    async def test_unauthorized_and_anonymous_senders_never_execute(self):
        for user_id, sender_chat in [(456, None), (None, None), (123, object())]:
            with self.subTest(user_id=user_id, sender_chat=sender_chat):
                update, replies = self.update(user_id, sender_chat)
                await self.deployer.deploy(update, SimpleNamespace(args=[]))
                self.assertFalse(self.marker.exists())
                self.assertIn("authorized", replies[-1].lower())

    async def test_command_arguments_are_rejected(self):
        update, replies = self.update()
        await self.deployer.deploy(update, SimpleNamespace(args=["arbitrary-command"]))
        self.assertFalse(self.marker.exists())
        self.assertIn("Usage", replies[-1])

    async def test_overlapping_deploy_is_rejected(self):
        self.script.write_text(
            "import time\nfrom pathlib import Path\n"
            "Path('started').touch()\ntime.sleep(0.4)\n"
            "with Path('deployed.txt').open('a') as f: f.write('ok')\n"
        )
        first, _ = self.update()
        task = asyncio.create_task(self.deployer.deploy(first, SimpleNamespace(args=[])))
        try:
            async with asyncio.timeout(5):
                while not (self.root / "started").exists():
                    await asyncio.sleep(0.01)
            second, replies = self.update()
            await self.deployer.deploy(second, SimpleNamespace(args=[]))
            self.assertIn("already", replies[-1].lower())
        finally:
            await task
        self.assertEqual(self.marker.read_text(), "ok")

    async def test_nonzero_exit_is_reported_and_lock_is_released(self):
        self.script.write_text("raise SystemExit(7)\n")
        update, replies = self.update()
        await self.deployer.deploy(update, SimpleNamespace(args=[]))
        self.assertIn("7", replies[-1])
        self.script.write_text("from pathlib import Path\nPath('deployed.txt').touch()\n")
        await self.deployer.deploy(update, SimpleNamespace(args=[]))
        self.assertTrue(self.marker.exists())

    async def test_missing_interpreter_is_reported_and_lock_is_released(self):
        self.data["shell"] = [str(self.root / "missing-shell")]
        self.config_file.write_text(json.dumps(self.data))
        deployer = bot.Deployer(bot.load_config(self.config_file))
        update, replies = self.update()
        with self.assertLogs("bot", level="ERROR"):
            await deployer.deploy(update, SimpleNamespace(args=[]))
        self.assertIn("could not", replies[-1].lower())
        self.assertFalse(deployer.lock.locked())

    def test_invalid_operator_lists_fail_closed(self):
        for ids in [[], ["123"], [True], [-1], "123"]:
            with self.subTest(ids=ids):
                self.data["operator_ids"] = ids
                self.config_file.write_text(json.dumps(self.data))
                with self.assertRaises(ValueError):
                    bot.load_config(self.config_file)

    def test_missing_script_fails_at_startup(self):
        self.script.unlink()
        with self.assertRaises(ValueError):
            bot.load_config(self.config_file)


if __name__ == "__main__":
    unittest.main()
