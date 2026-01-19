import argparse
import asyncio
import getpass
import logging
import os
import signal
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from nio import AsyncClient  # pyright: ignore
from nio.responses import ErrorResponse  # type: ignore

from paca_matrix.bot import PacaBot

log = logging.getLogger(__name__)

_bot_instance: PacaBot | None = None


def _signal_handler(signum: int, frame: Any) -> None:
    log.info("Received signal %s, shutting down...", signum)
    if _bot_instance:
        loop = asyncio.get_event_loop()
        loop.create_task(_bot_instance.stop())
    signal.signal(signum, signal.SIG_DFL)
    os.kill(os.getpid(), signum)


def main() -> None:
    signal.signal(signal.SIGTERM, _signal_handler)

    load_dotenv()

    opts = CliOpts.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if opts.verbose else logging.INFO,
        format="%(name)s %(message)s",
    )

    # Gets printed every tick, always disable
    logging.getLogger("nio.responses").setLevel(logging.INFO)

    if opts.login:
        asyncio.run(handle_login())
    else:
        try:
            asyncio.run(run_bot(opts))
        except KeyboardInterrupt:
            pass


async def handle_login() -> None:
    homeserver = input("Homeserver URL (press Enter for https://matrix.org): ").strip()
    if not homeserver:
        homeserver = "https://matrix.org"

    username = input("Username: ").strip()
    if not username:
        log.error("Username is required")
        return

    password = getpass.getpass("Password: ")
    if not password:
        log.error("Password is required")
        return

    device_name = input("Device name (optional, press Enter for 'paca-bot'): ").strip()
    device_name = device_name or "paca-bot"

    log.info("Logging in to %s...", homeserver)
    client = AsyncClient(homeserver, user=username)

    try:
        response = await client.login(password=password, device_name=device_name)

        if isinstance(response, ErrorResponse):
            log.error("Login failed: %s", response.message)
            return

        env_path = Path(".env")
        env_content = f"""
PACAMATRIX_HOMESERVER={homeserver}
PACAMATRIX_USER_ID={response.user_id}
PACAMATRIX_DEVICE_ID={response.device_id}
PACAMATRIX_ACCESS_TOKEN={response.access_token}
"""

        env_path.write_text(env_content)
        os.chmod(env_path, 0o600)
        log.info("Login successful!")
        log.info("Credentials saved to %s", env_path)
        log.info("You can now run bot with: paca")
    finally:
        await client.close()


async def run_bot(opts: "CliOpts") -> None:
    if (
        not opts.homeserver
        or not opts.user_id
        or not opts.access_token
        or not opts.device_id
        or not opts.opencode_server_url
    ):
        log.error(
            "Bot requires --homeserver, --user-id, --device-id, --access-token, and --opencode-server-url"
        )
        log.info("Or use --login to set up credentials")
        return

    global _bot_instance
    bot = PacaBot(
        homeserver=opts.homeserver,
        user_id=opts.user_id,
        device_id=opts.device_id,
        access_token=opts.access_token,
        opencode_server_url=opts.opencode_server_url,
        session_name=opts.session_name,
    )
    _bot_instance = bot

    try:
        await bot.run_forever()
    except KeyboardInterrupt:
        log.info("Received interrupt signal")
    finally:
        _bot_instance = None
        await bot.stop()


@dataclass(kw_only=True, frozen=True)
class CliOpts:
    verbose: bool
    login: bool
    homeserver: str | None
    user_id: str | None
    device_id: str | None
    access_token: str | None
    opencode_server_url: str | None
    session_name: str | None

    @staticmethod
    def parse_args() -> "CliOpts":
        parser = argparse.ArgumentParser(description="Matrix echo bot")

        parser.add_argument(
            "-v",
            "--verbose",
            action=EnvAction,
            env_var="PACAMATRIX_VERBOSE",
            nargs=0,
            help="show more detailed log messages",
        )
        parser.add_argument(
            "--login",
            action="store_true",
            help="Log in to Matrix homeserver and save credentials to .env",
        )
        parser.add_argument(
            "--homeserver",
            required=False,
            action=EnvAction,
            env_var="PACAMATRIX_HOMESERVER",
            help="Matrix homeserver URL (env: PACAMATRIX_HOMESERVER)",
        )
        parser.add_argument(
            "--user-id",
            required=False,
            action=EnvAction,
            env_var="PACAMATRIX_USER_ID",
            help="Matrix user ID (env: PACAMATRIX_USER_ID)",
        )
        parser.add_argument(
            "--access-token",
            required=False,
            action=EnvAction,
            env_var="PACAMATRIX_ACCESS_TOKEN",
            help="Matrix access token (env: PACAMATRIX_ACCESS_TOKEN)",
        )
        parser.add_argument(
            "--device-id",
            required=False,
            action=EnvAction,
            env_var="PACAMATRIX_DEVICE_ID",
            help="Matrix device ID (env: PACAMATRIX_DEVICE_ID)",
        )
        parser.add_argument(
            "--opencode-server-url",
            required=False,
            action=EnvAction,
            env_var="PACAMATRIX_OPENCODE_SERVER_URL",
            help="OpenCode server URL (env: PACAMATRIX_OPENCODE_SERVER_URL)",
        )
        parser.add_argument(
            "--session",
            required=False,
            action=EnvAction,
            env_var="PACAMATRIX_SESSION",
            help="Session ID to connect to (env: PACAMATRIX_SESSION). If not set, creates a new session",
        )

        args = parser.parse_args()

        if not args.login and not (
            args.homeserver
            and args.user_id
            and args.device_id
            and args.access_token
            and args.opencode_server_url
        ):
            parser.error(
                "--homeserver, --user-id, --device-id, --access-token, and --opencode-server-url are required when not using --login"
            )

        return CliOpts(
            verbose=args.verbose is not None,
            login=args.login,
            homeserver=args.homeserver,
            user_id=args.user_id,
            device_id=args.device_id,
            access_token=args.access_token,
            opencode_server_url=args.opencode_server_url,
            session_name=args.session,
        )


class EnvAction(argparse.Action):
    """ArgumentParser Action for options with an env var fallback"""

    def __init__(
        self,
        help: str,
        env_var: str = "",
        required: bool = True,
        default: Any = None,
        nargs: str | int | None = None,
        **kwargs: Any,
    ) -> None:
        if default is not None and env_var:
            help += f" (default: {default}, env: {env_var})"
        elif default is not None:
            help += f" (default: {default})"
        elif env_var:
            help += f" (env: {env_var})"

        if env_var and env_var in os.environ:
            default = os.environ[env_var]
            if default == "":
                default = None

        if default is not None or nargs == 0:
            required = False

        super(EnvAction, self).__init__(
            help=help,
            default=default,
            required=required,
            nargs=nargs,
            **kwargs,
        )

    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: Any,
        option_string: str | None = None,
    ) -> None:
        _ = parser
        _ = option_string
        if self.nargs == 0:
            setattr(namespace, self.dest, True)
        else:
            setattr(namespace, self.dest, values)
