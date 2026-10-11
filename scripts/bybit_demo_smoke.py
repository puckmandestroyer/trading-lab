"""Manually invoked, bounded Demo diagnostics; no import-time I/O or runtime."""

import argparse
from decimal import Decimal, InvalidOperation
import re

from trading_lab.exchange import (
    BybitDemoActionParseError, BybitDemoAmbiguousActionError,
    BybitDemoOrderAdapter, BybitDemoReadOnlyAdapter, SpotMarketOrderRequest,
    create_bybit_demo_session, fetch_bybit_spot_instrument_rules,
    load_bybit_demo_credentials,
)


class _SafeParser(argparse.ArgumentParser):
    def error(self, message):
        # argparse normally echoes rejected argument values; they may be private.
        self.exit(2, "Invalid smoke arguments. Run --help for usage.\n")


def _symbol(value):
    if not value or value != value.strip() or value != value.upper():
        raise argparse.ArgumentTypeError("Invalid symbol.")
    return value


def _identifier(value):
    if not value or value != value.strip():
        raise argparse.ArgumentTypeError("Invalid order identifier.")
    return value


def _link(value):
    if re.fullmatch(r"[A-Za-z0-9_-]{1,36}", value) is None:
        raise argparse.ArgumentTypeError("Invalid caller order link.")
    return value


def _amount(value):
    try:
        number = Decimal(value)
    except InvalidOperation:
        raise argparse.ArgumentTypeError("Invalid amount.") from None
    if value != value.strip() or not number.is_finite() or number <= 0:
        raise argparse.ArgumentTypeError("Invalid amount.")
    return number


def _parser():
    parser = _SafeParser(description="Bounded Bybit Demo smoke; no mode means no requests.")
    modes = parser.add_subparsers(dest="mode")
    read = modes.add_parser("read", help="Read Demo metadata/account/open orders only.")
    read.add_argument("--symbol", required=True, type=_symbol)
    read.add_argument("--executions", action="store_true", help="Also explicitly read reported fills.")
    place = modes.add_parser("place", help="Explicitly authorize one Demo Spot Market action.")
    place.add_argument("--symbol", required=True, type=_symbol)
    place.add_argument("--side", required=True, choices=("BUY", "SELL"))
    place.add_argument("--amount", required=True, type=_amount)
    place.add_argument("--order-link-id", required=True, type=_link)
    cancel = modes.add_parser("cancel", help="Explicitly request one exact-ID Demo cancellation.")
    cancel.add_argument("--symbol", required=True, type=_symbol)
    cancel.add_argument("--order-id", required=True, type=_identifier)
    for command in (place, cancel):
        command.add_argument("--confirm-demo-action", action="store_true",
                             help="Required additional opt-in to this single mutation.")
        command.add_argument("--read-after", action="store_true",
                             help="After acceptance, explicitly read order state and fills once.")
    return parser


def main(argv=None) -> int:
    """Validate explicit intent, perform a finite sequence, close the client, exit."""
    parser = _parser()
    args = parser.parse_args(argv)
    if args.mode is None:
        parser.print_help()
        return 0
    if args.mode in ("place", "cancel") and not args.confirm_demo_action:
        parser.error("An action requires explicit confirmation.")

    session = None
    exit_code = 0
    try:
        session = create_bybit_demo_session(load_bybit_demo_credentials())
        reads = BybitDemoReadOnlyAdapter(session)
        if args.mode == "read":
            # Constructor checks Demo routing immediately before the metadata read.
            print("Demo instrument:", fetch_bybit_spot_instrument_rules(session, args.symbol))
            print("Demo account:", reads.get_account_state())
            print("Demo open orders:", reads.get_open_orders(args.symbol))
            if args.executions:
                print("Reported executions:", reads.get_executions(symbol=args.symbol))
        else:
            actions = BybitDemoOrderAdapter(session)
            # Read-only connectivity must succeed first; balances never size orders.
            reads.get_account_state()
            if args.mode == "place":
                unit = "QUOTE" if args.side == "BUY" else "BASE"
                request = SpotMarketOrderRequest(args.symbol, args.side, args.amount,
                                                 unit, args.order_link_id)
                print("Demo Spot Market authorization:", request, "isLeverage=0")
                print("Fresh Stage 9.3 rules normalize down before the single placement.")
                receipt = actions.place_market_order(request)
                print("Placement acceptance (not a fill):", receipt)
            else:
                print("Demo Spot cancellation request:", args.symbol, args.order_id)
                receipt = actions.cancel_order(args.symbol, args.order_id)
                print("Cancellation acceptance (not terminal CANCELLED):", receipt)
            if args.read_after:
                print("Observed order:", reads.get_order(receipt.broker_order_id))
                print("Reported executions:", reads.get_executions(receipt.broker_order_id, args.symbol))
    except Exception as error:
        # The metadata helper deliberately propagates SDK exceptions. Never echo
        # those messages, request bodies, headers, client reprs or raw tracebacks.
        print(f"Demo smoke failed ({type(error).__name__}).")
        if isinstance(error, (BybitDemoAmbiguousActionError, BybitDemoActionParseError)):
            print("Action outcome is unknown. No automatic retry or follow-up read was made.")
        exit_code = 1
    finally:
        if session is not None:
            try:
                session.client.close()
            except Exception as error:
                print(f"Demo client cleanup failed ({type(error).__name__}).")
                exit_code = 1
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
