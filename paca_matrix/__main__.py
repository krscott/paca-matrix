import argparse
import asyncio
import base64
import getpass
import logging
import logging.handlers
import os
import re
import signal
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import aiohttp
from dotenv import find_dotenv, load_dotenv
from nio import AsyncClient  # pyright: ignore
from nio.responses import ErrorResponse  # type: ignore
from setproctitle import setproctitle

from paca_matrix.bot import PacaBot
from paca_matrix.utils import get_global_share_dir, get_share_dir

DEFAULT_MATRIX_HOMESERVER = "https://matrix.org"
DEFAULT_BOT_NAME = "paca-bot"
DEFAULT_PORT = 4096

log = logging.getLogger(__name__)


class BotStartupError(Exception):
    """Exception raised when the bot fails to start due to configuration errors."""

    pass


# Global reference for use by _signal_handler
_bot_instance: PacaBot | None = None
_opencode_process: asyncio.subprocess.Process | None = None


def _signal_handler(signum: int, _: Any) -> None:
    log.info("Received signal %s, shutting down...", signum)
    if _bot_instance:
        loop = asyncio.get_event_loop()
        loop.create_task(_bot_instance.stop())
    signal.signal(signum, signal.SIG_DFL)
    os.kill(os.getpid(), signum)


def main() -> None:
    setproctitle("paca")

    signal.signal(signal.SIGTERM, _signal_handler)

    # Load .env files in priority order (later files override earlier ones):
    # 1. Local .env (highest priority for files)
    # 2. Per-repo share .env
    # 3. Global share .env (lowest priority for files)
    load_dotenv(find_dotenv(usecwd=True))
    load_dotenv(get_share_dir() / ".env")
    load_dotenv(get_global_share_dir() / ".env")

    opts = CliOpts.parse_args()

    # Set up handlers: console + rotating file
    # In combined mode (client attached), skip console handler to avoid TUI corruption
    handlers: list[logging.Handler] = []
    if not (opts.opencode_client or opts.opencode_web):
        handlers.append(logging.StreamHandler())

    # Determine log file path (XDG-compliant default)
    log_file_path = opts.log_file
    if log_file_path is None:
        xdg_data_home = os.environ.get(
            "XDG_DATA_HOME", Path.home() / ".local" / "share"
        )
        log_dir = Path(xdg_data_home) / "paca" / "logs"
        log_file_path = str(log_dir / "paca.log")

    # Ensure log directory exists
    Path(log_file_path).parent.mkdir(parents=True, exist_ok=True)

    # Add rotating file handler (10MB per file, 3 backups = ~40MB max)
    file_handler = logging.handlers.RotatingFileHandler(
        log_file_path, maxBytes=10 * 1024 * 1024, backupCount=3
    )
    handlers.append(file_handler)

    logging.basicConfig(
        level=logging.DEBUG if opts.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        handlers=handlers,
    )

    # In combined mode, print log location since console logs are disabled
    if opts.opencode_client or opts.opencode_web:
        print(f"Logs: {log_file_path}")

    # INFO is still too verbose
    logging.getLogger("nio").setLevel(
        logging.DEBUG if opts.verbose else logging.WARNING
    )

    # DEBUG gets printed every tick, always disable
    logging.getLogger("nio.responses").setLevel(logging.INFO)

    if opts.login:
        asyncio.run(matrix_login(per_repo=opts.per_repo))
    elif opts.opencode_client:
        setproctitle("pacacode")
        try:
            asyncio.run(run_opencode_client_with_server(opts))
        except BotStartupError:
            raise SystemExit(1)
    elif opts.opencode_web:
        try:
            asyncio.run(run_opencode_web_with_server(opts))
        except BotStartupError:
            raise SystemExit(1)
    else:
        try:
            asyncio.run(run_bot(opts))
        except BotStartupError:
            raise SystemExit(1)
        except KeyboardInterrupt:
            pass


async def is_opencode_server_running(port: int) -> bool:
    """Check if an opencode server is already running on the given port."""
    url = f"http://127.0.0.1:{port}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=2)):
                return True
    except Exception:
        return False


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


async def run_opencode_attach(port: int, session_id: str | None) -> None:
    """Run opencode attach command to connect to the opencode server."""
    url = f"http://127.0.0.1:{port}"
    log.info("Attaching to opencode server at %s", url)

    cmd = ["opencode", "attach", url]

    session_file = get_share_dir() / ".paca_session"
    if not session_id and session_file.exists():
        try:
            session_id = session_file.read_text().strip()
        except Exception:
            pass

    if session_id:
        cmd.extend(["-s", session_id])

    process = await asyncio.create_subprocess_exec(*cmd)
    await process.wait()


def run_opencode_web(port: int, session_id: str | None) -> None:
    """Open the web view for the opencode server."""
    url = f"http://127.0.0.1:{port}"

    session_file = get_share_dir() / ".paca_session"
    if not session_id and session_file.exists():
        try:
            session_id = session_file.read_text().strip()
        except Exception:
            pass

    if session_id:
        project_path = Path.cwd().resolve()
        project_id = (
            base64.urlsafe_b64encode(str(project_path).encode()).decode().rstrip("=")
        )
        url = f"{url}/{project_id}/session/{session_id}"

    log.info("Opening opencode web view at %s", url)
    webbrowser.open(url)


async def run_opencode_client_with_server(opts: "CliOpts") -> None:
    """Run opencode client, starting bot if needed. Stops bot when client exits."""
    port = opts.opencode_port
    bot_task: asyncio.Task[None] | None = None

    # Check if server is already running
    if not await is_opencode_server_running(port):
        log.info("No paca instance running, starting bot...")
        # Start the bot in a background task
        bot_task = asyncio.create_task(run_bot(opts))

        # Wait for server to be ready (check more frequently initially)
        for _ in range(30):  # Try for 30 seconds
            await asyncio.sleep(1)
            # Check if bot failed immediately
            if bot_task.done():
                try:
                    await bot_task
                except BotStartupError:
                    # Bot failed to start due to configuration error
                    raise
                except Exception as e:
                    log.error("Bot failed to start: %s", e)
                    raise SystemExit(1) from e
                # Bot completed successfully (shouldn't happen)
                log.error("Bot exited unexpectedly")
                raise SystemExit(1)
            if await is_opencode_server_running(port):
                log.info("Bot started and server is ready")
                break
        else:
            log.error("Bot failed to start within 30 seconds")
            if bot_task:
                bot_task.cancel()
                try:
                    await bot_task
                except asyncio.CancelledError:
                    pass
            raise SystemExit(1)

    try:
        # Run the attach command (blocks until client closes)
        await run_opencode_attach(port, opts.session_name)
    finally:
        # Stop the bot if we started it
        if bot_task:
            log.info("Client closed, stopping bot...")
            bot_task.cancel()
            try:
                await bot_task
            except asyncio.CancelledError:
                pass


async def run_opencode_web_with_server(opts: "CliOpts") -> None:
    """Open opencode web view, starting bot if needed. Bot continues running."""
    port = opts.opencode_port
    bot_task: asyncio.Task[None] | None = None

    # Check if server is already running
    if not await is_opencode_server_running(port):
        log.info("No paca instance running, starting bot...")
        # Start the bot in a background task
        bot_task = asyncio.create_task(run_bot(opts))

        # Wait for server to be ready
        for _ in range(30):  # Try for 30 seconds
            await asyncio.sleep(1)
            # Check if bot failed immediately
            if bot_task.done():
                try:
                    await bot_task
                except BotStartupError:
                    # Bot failed to start due to configuration error
                    raise
                except Exception as e:
                    log.error("Bot failed to start: %s", e)
                    raise SystemExit(1) from e
                # Bot completed successfully (shouldn't happen)
                log.error("Bot exited unexpectedly")
                raise SystemExit(1)
            if await is_opencode_server_running(port):
                log.info("Bot started and server is ready")
                break
        else:
            log.error("Bot failed to start within 30 seconds")
            if bot_task:
                bot_task.cancel()
                try:
                    await bot_task
                except asyncio.CancelledError:
                    pass
            raise SystemExit(1)

        # Open the web browser
        run_opencode_web(port, opts.session_name)

        # Keep the bot running (don't stop it)
        log.info("Bot started and browser opened. Bot will keep running.")
        try:
            # Wait for the bot task to complete (it won't unless killed)
            if bot_task:
                await bot_task
        except KeyboardInterrupt:
            log.info("Received interrupt, stopping bot...")
            if bot_task:
                bot_task.cancel()
                try:
                    await bot_task
                except asyncio.CancelledError:
                    pass
    else:
        # Server is already running, just open the browser
        run_opencode_web(port, opts.session_name)


async def matrix_login(per_repo: bool = False) -> None:
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

        # Choose storage location based on --per-repo flag
        if per_repo:
            env_path = get_share_dir() / ".env"
            location_desc = "per-repo"
        else:
            env_path = get_global_share_dir() / ".env"
            location_desc = "global (shared across all repos)"

        # Use individual lines to avoid f-string injection issues
        env_lines = [
            f"PACAMATRIX_HOMESERVER={homeserver}",
            f"PACAMATRIX_USER_ID={response.user_id}",
            f"PACAMATRIX_DEVICE_ID={response.device_id}",
            f"PACAMATRIX_ACCESS_TOKEN={response.access_token}",
        ]
        env_content = "\n".join(env_lines) + "\n"

        env_path.parent.mkdir(parents=True, exist_ok=True)
        env_path.write_text(env_content)
        os.chmod(env_path, 0o600)
        log.info("Login successful!")
        log.info("Credentials saved to %s (%s)", env_path, location_desc)
        log.info("You can now run bot with: paca")
    finally:
        await client.close()


async def _get_available_models() -> list[str]:
    """Get the set of available models from OpenCode."""
    models: list[str] = []

    process = await asyncio.create_subprocess_exec(
        "opencode",
        "models",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    if stderr:
        log.debug("opencode models stderr: %s", stderr.decode())
    if stdout:
        output = stdout.decode().strip()
        for line in output.splitlines():
            line = line.strip()
            if line and not line.startswith("Available models"):
                models.append(line)

    assert models, "No models supported"
    return models


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
        raise BotStartupError(
            "Missing required credentials. Use --login to set up or provide "
            "--homeserver, --user-id, --device-id, and --access-token"
        )

    global _bot_instance, _opencode_process

    available_models = await _get_available_models()
    if opts.model:
        if opts.model not in available_models:
            log.error(
                "Model '%s' is not available in OpenCode. Available models:%s",
                opts.model,
                "".join(f"\n  - {m}" for m in available_models),
            )
            # TODO: All returns due to errors should lead to exit codes
            return
    else:
        log.warning("Warning: --model or PACAMATRIX_MODEL is not set.")
        log.info("It is recommended to set this in your .env file.")
        log.info(
            "Available models:%s",
            "".join(f"\n  - {m}" for m in available_models),
        )

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
        room_id=opts.room_id,
        reauth_room=opts.reauth_room,
        per_repo=opts.per_repo,
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
    per_repo: bool
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
    resume: bool
    log_file: str | None
    room_id: str | None
    reauth_room: bool

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
            "--per-repo",
            action="store_true",
            help="Store credentials in per-repo location instead of global (use with --login)",
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
            "-s",
            "--session",
            required=False,
            action=EnvAction,
            env_var="PACAMATRIX_SESSION",
            help="Session ID to connect to (env: PACAMATRIX_SESSION). If not set, creates a new session",
        )
        parser.add_argument(
            "--resume",
            action="store_true",
            help="Resume the previous session from .paca_session file",
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
        parser.add_argument(
            "--log-file",
            required=False,
            action=EnvAction,
            env_var="PACAMATRIX_LOG_FILE",
            help="Path to log file (default: ~/.local/share/paca/logs/paca.log, env: PACAMATRIX_LOG_FILE)",
        )
        parser.add_argument(
            "--room-id",
            required=False,
            action=EnvAction,
            env_var="PACAMATRIX_ROOM_ID",
            help="Matrix room ID to listen in (env: PACAMATRIX_ROOM_ID)",
        )
        parser.add_argument(
            "--reauth-room",
            action="store_true",
            help="Force re-authentication of the room (generates new auth code)",
        )

        args = parser.parse_args()

        # Allow -c/-w without credentials if server is already running
        # We'll check at runtime if we need to start the bot
        client_mode = args.opencode_client or args.opencode_web
        if (
            not args.login
            and not client_mode
            and not (
                args.homeserver
                and args.user_id
                and args.device_id
                and args.access_token
            )
        ):
            parser.error(
                "--homeserver, --user-id, --device-id, and --access-token are required when not using --login"
            )

        # Handle --resume flag: read session from .paca_session if it exists
        session_name = args.session
        session_file = get_share_dir() / ".paca_session"
        if args.resume and not session_name and session_file.exists():
            try:
                session_name = session_file.read_text().strip()
            except Exception:
                pass

        return CliOpts(
            verbose=args.verbose is not None,
            login=args.login,
            per_repo=args.per_repo,
            homeserver=args.homeserver,
            user_id=args.user_id,
            device_id=args.device_id,
            access_token=args.access_token,
            opencode_server_url=args.opencode_server_url,
            opencode_port=args.opencode_port,
            session_name=session_name,
            model=args.model,
            opencode_client=args.opencode_client,
            opencode_web=args.opencode_web,
            resume=args.resume,
            log_file=args.log_file,
            room_id=args.room_id,
            reauth_room=args.reauth_room,
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
