import argparse
import asyncio
import getpass
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from nio import AsyncClient  # type: ignore
from nio.responses import ErrorResponse  # type: ignore

from paca_matrix.bot import EchoBot

log = logging.getLogger(__name__)


def main() -> None:
    load_dotenv()

    opts = CliOpts.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(message)s",
    )

    if opts.verbose:
        log.setLevel(logging.DEBUG)

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
    ):
        log.error(
            "Bot requires --homeserver, --user-id, --device-id, and --access-token"
        )
        log.info("Or use --login to set up credentials")
        return

    bot = EchoBot(opts.homeserver, opts.user_id, opts.device_id, opts.access_token)

    try:
        await bot.run_forever()
    except KeyboardInterrupt:
        log.info("Received interrupt signal")
    finally:
        await bot.stop()


@dataclass(kw_only=True, frozen=True)
class CliOpts:
    verbose: bool
    login: bool
    homeserver: str | None
    user_id: str | None
    device_id: str | None
    access_token: str | None

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

        args = parser.parse_args()

        if not args.login and not (
            args.homeserver and args.user_id and args.device_id and args.access_token
        ):
            parser.error(
                "--homeserver, --user-id, --device-id, and --access-token are required when not using --login"
            )

        return CliOpts(
            verbose=args.verbose is not None,
            login=args.login,
            homeserver=args.homeserver,
            user_id=args.user_id,
            device_id=args.device_id,
            access_token=args.access_token,
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
