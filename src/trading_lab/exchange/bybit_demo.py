"""Demo-only credentials/session construction; no import-time network or request methods."""

from collections.abc import Mapping
from dataclasses import dataclass, field
import logging
import os

from pybit.unified_trading import HTTP


class BybitDemoConfigurationError(ValueError):
    """Demo configuration is missing or invalid."""


def _validate_credential(value: str, variable_name: str) -> None:
    if not isinstance(value, str) or not value or value != value.strip():
        raise BybitDemoConfigurationError(
            f"{variable_name} must be a non-empty string without surrounding whitespace."
        )


@dataclass(frozen=True, slots=True)
class BybitDemoCredentials:
    """Opaque Demo credentials with both values omitted from repr and str."""

    api_key: str = field(repr=False)
    api_secret: str = field(repr=False)

    def __post_init__(self) -> None:
        _validate_credential(self.api_key, "BYBIT_DEMO_API_KEY")
        _validate_credential(self.api_secret, "BYBIT_DEMO_API_SECRET")


def load_bybit_demo_credentials(
    environ: Mapping[str, str] | None = None,
) -> BybitDemoCredentials:
    """Load only Demo-specific names from the supplied mapping or call-time environment."""
    if environ is None:
        environ = os.environ
    elif not isinstance(environ, Mapping):
        raise BybitDemoConfigurationError("environ must be a Mapping.")

    return BybitDemoCredentials(
        api_key=environ.get("BYBIT_DEMO_API_KEY"),
        api_secret=environ.get("BYBIT_DEMO_API_SECRET"),
    )


def create_bybit_demo_session(credentials: BybitDemoCredentials) -> HTTP:
    """Construct a Demo-only HTTP client without making a request."""
    if not isinstance(credentials, BybitDemoCredentials):
        raise BybitDemoConfigurationError(
            "credentials must be a BybitDemoCredentials instance."
        )

    # One SDK attempt prevents blind resends after an ambiguous future placement.
    session = HTTP(
        testnet=False,
        demo=True,
        api_key=credentials.api_key,
        api_secret=credentials.api_secret,
        force_retry=False,
        max_retries=1,
        retry_delay=0,
        log_requests=False,
    )
    # pybit logs raw retMsg/HTTP response text even with log_requests=False.
    # Mute those SDK diagnostics on this client, not on its shared global logger.
    # The adapters continue to report safe operation/code/type context.
    session.logger = logging.Logger(__name__)
    session.logger.disabled = True
    return session
