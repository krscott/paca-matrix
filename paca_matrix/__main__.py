import argparse
import asyncio
import getpass
import logging
import os
import re
import signal
import subprocess
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import find_dotenv, load_dotenv
from nio import AsyncClient  # pyright: ignore
from nio.responses import ErrorResponse  # type: ignore
from setproctitle import setproctitle

from paca_matrix.bot import PacaBot

DEFAULT_MATRIX_HOMESERVER = "https://matrix.org"
DEFAULT_BOT_NAME = "paca-bot"
DEFAULT_PORT = 4096

log = logging.getLogger(__name__)

# Global reference for use by _signal_handler
_bot_instance: PacaBot | None = None
_opencode_process: asyncio.subprocess.Process | None = None


def _signal_handler(signum: int, frame: Any) -> None:
    log.info("Received signal %s, shutting down...", signum)
    if _bot_instance:
        loop = asyncio.get_event_loop()
        loop.create_task(_bot_instance.stop())
    signal.signal(signum, signal.SIG_DFL)
    os.kill(os.getpid(), signum)


def main() -> None:
    setproctitle("paca")

    signal.signal(signal.SIGTERM, _signal_handler)

    load_dotenv(find_dotenv(usecwd=True))

    opts = CliOpts.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if opts.verbose else logging.INFO,
        format="%(name)s %(levelname)s %(message)s",
    )

    # INFO is still too verbose
    logging.getLogger("nio").setLevel(
        logging.DEBUG if opts.verbose else logging.WARNING
    )

    # DEBUG gets printed every tick, always disable
    logging.getLogger("nio.responses").setLevel(logging.INFO)

    if opts.login:
        asyncio.run(matrix_login())
    elif opts.opencode_client:
        setproctitle("pacacode")
        run_opencode_attach(opts)
    elif opts.opencode_web:
        run_opencode_web(opts)
    else:
        try:
            asyncio.run(run_bot(opts))
        except KeyboardInterrupt:
            pass


async def start_opencode_server(port: int) -> tuple[str, asyncio.subprocess.Process]:
    """Start an opencode server subprocess and return the server URL and process."""
    log.info("Starting opencode server on port %s...", port)

    process = await asyncio.create_subprocess_exec(
        "opencode",
        "serve",
        "--port",
        str(port),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    assert process.stdout is not None

    url_pattern = re.compile(r"opencode server listening on (http://127\.0\.0\.1:\d+)")

    while True:
        line = await process.stdout.readline()
        if not line:
            raise RuntimeError("opencode server process terminated unexpectedly")
        decoded = line.decode("utf-8").strip()
        match = url_pattern.search(decoded)
        if match:
            url = match.group(1)
            log.info("opencode server started at %s", url)
            return url, process

        log.debug("opencode server output: %s", decoded)


async def stop_opencode_server(process: asyncio.subprocess.Process) -> None:
    """Stop the opencode server subprocess."""
    log.info("Stopping opencode server...")
    process.terminate()
    try:
        await asyncio.wait_for(process.wait(), timeout=5.0)
        log.info("opencode server stopped")
    except asyncio.TimeoutError:
        log.warning("opencode server did not stop gracefully, killing...")
        process.kill()
        await process.wait()


def run_opencode_attach(opts: "CliOpts") -> None:
    """Run opencode attach command to connect to the opencode server."""
    port = opts.opencode_port or 0
    url = f"http://127.0.0.1:{port}"
    log.info("Attaching to opencode server at %s", url)
    
    cmd = ["opencode", "attach", url]
    
    session_id = opts.session_name
    if not session_id and Path(".paca_session").exists():
        try:
            session_id = Path(".paca_session").read_text().strip()
        except Exception:
            pass
            
    if session_id:
        cmd.extend(["-s", session_id])
        
    subprocess.run(cmd)


def run_opencode_web(opts: "CliOpts") -> None:
    """Open the web view for the opencode server."""
    port = opts.opencode_port or 0
    url = f"http://127.0.0.1:{port}"
    
    session_id = opts.session_name
    if not session_id and Path(".paca_session").exists():
        try:
            session_id = Path(".paca_session").read_text().strip()
        except Exception:
            pass

    if session_id:
        url = f"{url}/?session={session_id}"

    log.info("Opening opencode web view at %s", url)
    webbrowser.open(url)


async def matrix_login() -> None:
    homeserver = input(
        f"Homeserver URL (default: '{DEFAULT_MATRIX_HOMESERVER}'): "
    ).strip()
    if not homeserver:
        homeserver = DEFAULT_MATRIX_HOMESERVER

    username = input("Username: ").strip()
    if not username:
        log.error("Username is required")
        return

    password = getpass.getpass("Password: ")
    if not password:
        log.error("Password is required")
        return

    device_name = input(f"Device name (default: '{DEFAULT_BOT_NAME}'): ").strip()
    if not device_name:
        device_name = DEFAULT_BOT_NAME

    log.info("Logging in to %s...", homeserver)
    client = AsyncClient(homeserver, user=username)

    try:
        response = await client.login(password=password, device_name=device_name)

        if isinstance(response, ErrorResponse):
            log.error("Login failed: %s", response.message)
            return

        # Validate credentials before writing to prevent injection
        # Check for newlines or null bytes that could corrupt the .env file
        for field_name, field_value in [
            ("homeserver", homeserver),
            ("user_id", response.user_id),
            ("device_id", response.device_id),
            ("access_token", response.access_token),
        ]:
            if (
                "\n" in str(field_value)
                or "\r" in str(field_value)
                or "\0" in str(field_value)
            ):
                log.error(
                    "Invalid %s contains newline or null byte, refusing to write .env",
                    field_name,
                )
                return

        env_path = Path(".env")
        # Use individual lines to avoid f-string injection issues
        env_lines = [
            f"PACAMATRIX_HOMESERVER={homeserver}",
            f"PACAMATRIX_USER_ID={response.user_id}",
            f"PACAMATRIX_DEVICE_ID={response.device_id}",
            f"PACAMATRIX_ACCESS_TOKEN={response.access_token}",
        ]
        env_content = "\n".join(env_lines) + "\n"

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

    global _bot_instance, _opencode_process

    opencode_server_url = opts.opencode_server_url

    if opencode_server_url is None:
        log.info("No opencode server URL provided, starting opencode server...")
        opencode_server_url, _opencode_process = await start_opencode_server(
            port=opts.opencode_port
        )

    bot = PacaBot(
        homeserver=opts.homeserver,
        user_id=opts.user_id,
        device_id=opts.device_id,
        access_token=opts.access_token,
        opencode_server_url=opencode_server_url,
        session_name=opts.session_name,
        model=opts.model,
    )
    _bot_instance = bot

    try:
        await bot.run_forever()
    except KeyboardInterrupt:
        log.info("Received interrupt signal")
    finally:
        _bot_instance = None
        await bot.stop()
        if _opencode_process:
            await stop_opencode_server(_opencode_process)
            _opencode_process = None


@dataclass(kw_only=True, frozen=True)
class CliOpts:
    verbose: bool
    login: bool
    homeserver: str | None
    user_id: str | None
    device_id: str | None
    access_token: str | None
    opencode_server_url: str | None
    opencode_port: int
    session_name: str | None
    model: str | None
    opencode_client: bool
    opencode_web: bool

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
            help="OpenCode server URL (env: PACAMATRIX_OPENCODE_SERVER_URL). If not provided, an opencode server will be started automatically",
        )
        parser.add_argument(
            "--opencode-port",
            default=DEFAULT_PORT,
            action=EnvAction,
            env_var="PACAMATRIX_OPENCODE_PORT",
            type=int,
            help=f"Port for the automatically started opencode server (env: PACAMATRIX_OPENCODE_PORT, default: {DEFAULT_PORT})",
        )
        parser.add_argument(
            "--session",
            required=False,
            action=EnvAction,
            env_var="PACAMATRIX_SESSION",
            help="Session ID to connect to (env: PACAMATRIX_SESSION). If not set, creates a new session",
        )
        parser.add_argument(
            "--model",
            required=False,
            action=EnvAction,
            env_var="PACAMATRIX_MODEL",
            help="OpenCode model ID, e.g. 'anthropic/claude-3-5-sonnet-20241022' (env: PACAMATRIX_MODEL)",
        )
        parser.add_argument(
            "-c",
            "--opencode-client",
            action="store_true",
            help="Open the OpenCode client attached to paca's server",
        )
        parser.add_argument(
            "-w",
            "--opencode-web",
            action="store_true",
            help="Open the OpenCode web view for paca's server",
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
            opencode_server_url=args.opencode_server_url,
            opencode_port=args.opencode_port,
            session_name=args.session,
            model=args.model,
            opencode_client=args.opencode_client,
            opencode_web=args.opencode_web,
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
