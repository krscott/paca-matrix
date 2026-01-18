import logging

log = logging.getLogger(__name__)


def greet(name: str) -> None:
    """Print a greeting message.

    Args:
        name: The name of the person to greet.
    """
    log.debug("Greeting user...")
    print(f"Hello, {name}!")
