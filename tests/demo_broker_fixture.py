"""One coherent offline broker; responses are fixtures, never simulated fills."""

from copy import deepcopy
from unittest.mock import Mock

from tests.test_bybit_demo_orders import FakeActionSession, ack_response
from tests.test_bybit_demo_read_only import (
    execution_record, execution_response, order_record, order_response,
)


SECRETS = (
    "OFFLINE_API_KEY_SENTINEL", "OFFLINE_API_SECRET_SENTINEL",
    "OFFLINE_SIGNATURE_SENTINEL", "OFFLINE_AUTH_HEADER_SENTINEL",
    "OFFLINE_REQUEST_HEADER_SENTINEL", "OFFLINE_REQUEST_BODY_SENTINEL",
    "OFFLINE_CLIENT_REPR_SENTINEL",
)
PRIVATE_TEXT = " / ".join(SECRETS)
ENVIRONMENT = {"BYBIT_DEMO_API_KEY": SECRETS[0], "BYBIT_DEMO_API_SECRET": SECRETS[1]}


class IntegratedDemoSession(FakeActionSession):
    """Accept factory kwargs; record SDK calls without choosing state or amounts."""

    def __init__(self, **settings):
        super().__init__()
        for name, value in settings.items():
            setattr(self, name, value)
        self.client = Mock(spec=["close"])
        self.placement = ack_response(link="caller-1")
        self.cancellation = ack_response(link="caller-1")

    def mutation_calls(self):
        return [(name, params) for name, params in self.calls if name in {"place_order", "cancel_order"}]


def quote_order(status="Filled", *, filled_base="0.0015", filled_quote="12.3"):
    """Recorded quote budget and execution dimensions are supplied explicitly."""
    record = order_record(status=status)
    record.update(side="Buy", marketUnit="quoteCoin", qty="12.3456789",
                  cumExecQty=filled_base, cumExecValue=filled_quote,
                  avgPrice="8200", orderLinkId="caller-1")
    return record


def base_order(status="Filled", *, filled="0.123456", quote="123.456"):
    record = order_record(status=status)
    record.update(qty="0.123456", cumExecQty=filled, cumExecValue=quote,
                  avgPrice="1000", orderLinkId="caller-1")
    return record


def fill(execution_id="fill-1", *, side="Buy", quantity="0.0015",
         price="8200", fee="0.0000015", currency="BTC"):
    record = execution_record(execution_id)
    record.update(side=side, execQty=quantity, execPrice=price,
                  execFee=fee, feeCurrency=currency)
    return record


def with_private_extras(response):
    """Unexpected authentication-like fields must never become normalized state."""
    result = deepcopy(response)
    result.update(retMsg=PRIVATE_TEXT, requestHeaders={"Authorization": SECRETS[3]},
                  requestBody=SECRETS[5], signature=SECRETS[2])
    for record in result.get("result", {}).get("list", []):
        record["private_diagnostic"] = PRIVATE_TEXT
    return result
