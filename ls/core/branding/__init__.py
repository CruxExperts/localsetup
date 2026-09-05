"""Product display identity; technical identifiers remain unchanged."""

from ..framework_version import framework_version


PRODUCT_NAME = "LocalSetup"
PRODUCT_ABBREVIATION = "LS"
CLI_NAME = "LSCli"
CLI_COMMAND = "lscli"


def user_agent() -> str:
    """Return the framework identity used on outbound model requests."""
    return f"{PRODUCT_NAME}/{framework_version()}"
