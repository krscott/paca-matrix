import argparse
import asyncio
import logging
import os
from dataclasses import dataclass
from typing import Any

from dotenv import load_dotenv

from paca_matrix.bot import EchoBot
from paca_matrix.lib import greet

log = logging.getLogger(__name__)


def main() -> None:
    load_dotenv()

    opts = CliOpts.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if opts.verbose else logging.INFO,
        format="%(message)s",
    )

    if opts.mode == "bot":
        asyncio.run(run_bot(opts))
    else:
        greet(opts.name or "World")


async def run_bot(opts: "CliOpts") -> None:
    if not opts.homeserver or not opts.user_id or not opts.access_token:
        log.error("Bot mode requires --homeserver, --user-id, and --access-token")
        return

    bot = EchoBot(opts.homeserver, opts.user_id, opts.access_token)

    try:
        await bot.run_forever()
    except KeyboardInterrupt:
        log.info("Received interrupt signal")
    finally:
        await bot.stop()


@dataclass(kw_only=True, frozen=True)
class CliOpts:
    verbose: bool
    mode: str
    name: str | None
    homeserver: str | None
    user_id: str | None
    access_token: str | None

    @staticmethod
    def parse_args() -> "CliOpts":
        parser = argparse.ArgumentParser()

        parser.add_argument(
            "-v",
            "--verbose",
            action=EnvAction,
            env_var="PACAMATRIX_VERBOSE",
            nargs=0,
            help="show more detailed log messages",
        )
        parser.add_argument(
            "--mode",
            action=EnvAction,
            env_var="PACAMATRIX_MODE",
            default="greet",
            choices=["greet", "bot"],
            help="Run mode: greet or bot (default: greet, env: PACAMATRIX_MODE)",
        )
        parser.add_argument("name", nargs="?", help="Your name (for greet mode)")

        parser.add_argument(
            "--homeserver",
            action=EnvAction,
            env_var="PACAMATRIX_HOMESERVER",
            help="Matrix homeserver URL (env: PACAMATRIX_HOMESERVER)",
        )
        parser.add_argument(
            "--user-id",
            action=EnvAction,
            env_var="PACAMATRIX_USER_ID",
            help="Matrix user ID (env: PACAMATRIX_USER_ID)",
        )
        parser.add_argument(
            "--access-token",
            action=EnvAction,
            env_var="PACAMATRIX_ACCESS_TOKEN",
            help="Matrix access token (env: PACAMATRIX_ACCESS_TOKEN)",
        )

        args = parser.parse_args()

        return CliOpts(
            verbose=args.verbose is not None,
            mode=args.mode,
            name=args.name,
            homeserver=args.homeserver,
            user_id=args.user_id,
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
