"""Run one configured deployment script for authorized Telegram users."""

import argparse
import asyncio
from dataclasses import dataclass
import json
import logging
from pathlib import Path


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Config:
    bot_token: str
    operator_ids: frozenset[int]
    script: Path
    shell: tuple[str, ...]
    working_directory: Path


def load_config(path: Path) -> Config:
    path = Path(path).resolve()
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Config must be a JSON object")
    token = data.get("bot_token")
    if not isinstance(token, str) or not token.strip():
        raise ValueError("bot_token must be a nonempty string")
    operators = data.get("operator_ids")
    if (not isinstance(operators, list) or not operators
            or any(type(user_id) is not int or user_id <= 0 for user_id in operators)):
        raise ValueError("operator_ids must be a nonempty list of positive integer user IDs")
    script_name = data.get("script")
    if not isinstance(script_name, str) or not script_name.strip():
        raise ValueError("script must be a path to a script file")
    script = (path.parent / script_name).resolve()
    if not script.is_file():
        raise ValueError("Configured script does not exist or is not a file")
    shell = data.get("shell", ["/bin/bash"])
    if (not isinstance(shell, list) or not shell
            or any(not isinstance(arg, str) or not arg.strip() for arg in shell)):
        raise ValueError("shell must be a nonempty list of executable and optional flags")
    directory = data.get("working_directory")
    if directory is not None and (not isinstance(directory, str) or not directory.strip()):
        raise ValueError("working_directory must be a directory path")
    working_directory = (path.parent / directory).resolve() if directory else script.parent
    if not working_directory.is_dir():
        raise ValueError("working_directory does not exist")
    return Config(token.strip(), frozenset(operators), script, tuple(shell), working_directory)


class Deployer:
    def __init__(self, config: Config):
        self.config = config
        self.lock = asyncio.Lock()

    async def deploy(self, update, context):
        # Accept new messages only; channel/anonymous senders have no trusted user identity.
        message = update.message
        if message is None:
            return
        user = update.effective_user
        if (message.sender_chat is not None or user is None
                or user.id not in self.config.operator_ids):
            await message.reply_text("You are not authorized to deploy.")
            return
        if context.args:
            await message.reply_text("Usage: /deploy (no arguments)")
            return
        if self.lock.locked():
            await message.reply_text("A deployment is already running.")
            return
        async with self.lock:
            await message.reply_text("Deployment started.")
            logger.info("Deployment requested by user %s", user.id)
            try:
                # Explicit argv avoids shell interpolation; Telegram text is never executed.
                process = await asyncio.create_subprocess_exec(
                    *self.config.shell,
                    str(self.config.script),
                    cwd=self.config.working_directory,
                    stdin=asyncio.subprocess.DEVNULL,
                )
            except OSError:
                logger.exception("Could not start deployment script")
                await message.reply_text("Deployment could not start. Check the bot's server logs.")
                return
            try:
                exit_code = await process.wait()
            except asyncio.CancelledError:
                if process.returncode is None:
                    try:
                        process.terminate()
                    except ProcessLookupError:
                        pass
                    await process.wait()
                raise
            logger.info("Deployment for user %s exited with code %s", user.id, exit_code)
            if exit_code == 0:
                await message.reply_text("Deployment completed successfully.")
            else:
                await message.reply_text(f"Deployment failed (exit code {exit_code}). Check the bot's server logs.")


async def on_error(update, context):
    # Exception messages from HTTP clients can contain URLs with the bot token.
    logger.error("Telegram update failed (%s)", type(context.error).__name__)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path(__file__).with_name("config.json"))
    args = parser.parse_args()
    try:
        config = load_config(args.config)
    except (OSError, ValueError) as error:
        parser.error(str(error))

    from telegram.ext import Application, CommandHandler, filters

    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s %(message)s")
    logger.setLevel(logging.INFO)
    deployer = Deployer(config)
    app = Application.builder().token(config.bot_token).build()
    # Nonblocking callbacks let a second request receive the 'already running' reply.
    app.add_handler(CommandHandler("deploy", deployer.deploy, filters=filters.UpdateType.MESSAGE, block=False))
    app.add_error_handler(on_error)
    app.run_polling(allowed_updates=["message"], drop_pending_updates=True)


if __name__ == "__main__":
    main()
