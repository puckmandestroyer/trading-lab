"""Stage 9.6 smoke controls tested with one offline Demo broker fixture."""

import ast
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
from io import StringIO
from pathlib import Path
import unittest
from unittest.mock import patch

import requests

from scripts import bybit_demo_smoke as smoke
from tests.demo_broker_fixture import (
    ENVIRONMENT, PRIVATE_TEXT, SECRETS, IntegratedDemoSession,
    execution_response, fill, order_response, quote_order, with_private_extras,
)


PLACE = ["place", "--symbol", "BTCUSDT", "--side", "BUY", "--amount", "12.34567899",
         "--order-link-id", "caller-1", "--confirm-demo-action"]
CANCEL = ["cancel", "--symbol", "BTCUSDT", "--order-id", "order-1", "--confirm-demo-action"]


class SmokeControlTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.object(requests.Session, "send", side_effect=AssertionError("Offline only")))
        self.enterContext(patch.object(requests.Session, "request", side_effect=AssertionError("Offline only")))
        self.session = IntegratedDemoSession()
        self.factory = self.enterContext(patch("trading_lab.exchange.bybit_demo.HTTP", return_value=self.session))
        self.enterContext(patch("trading_lab.exchange.bybit_demo.os.environ", ENVIRONMENT))

    def invoke(self, argv):
        output, errors = StringIO(), StringIO()
        with redirect_stdout(output), redirect_stderr(errors):
            try:
                code = smoke.main(argv)
            except SystemExit as error:
                code = error.code
        for secret in SECRETS:
            self.assertNotIn(secret, output.getvalue() + errors.getvalue())
        return code, output.getvalue(), errors.getvalue()

    def assert_blocked_before_session(self, argv):
        code, _, _ = self.invoke(argv)
        self.assertEqual(code, 2)
        self.factory.assert_not_called()
        self.assertEqual(self.session.calls, [])

    def test_default_invocation_with_credentials_makes_no_request_or_session(self):
        with patch.object(smoke, "load_bybit_demo_credentials") as load:
            code, output, _ = self.invoke([])
        self.assertEqual(code, 0)
        self.assertIn("no mode means no requests", output)
        load.assert_not_called()
        self.factory.assert_not_called()
        self.assertEqual(self.session.calls, [])

    def test_help_makes_no_request_or_session(self):
        self.assertEqual(self.invoke(["--help"])[0], 0)
        self.factory.assert_not_called()
        self.assertEqual(self.session.calls, [])

    def test_read_mode_only_reads_metadata_account_and_open_orders(self):
        with patch.object(smoke, "BybitDemoOrderAdapter", side_effect=AssertionError("No action adapter in read mode")):
            code, output, _ = self.invoke(["read", "--symbol", "BTCUSDT"])
        self.assertEqual(code, 0)
        self.assertEqual(self.session.calls, [
            ("get_instruments_info", {"category": "spot", "symbol": "BTCUSDT"}),
            ("get_wallet_balance", {"accountType": "UNIFIED"}),
            ("get_open_orders", {"category": "spot", "openOnly": 0, "limit": 50, "symbol": "BTCUSDT"}),
        ])
        self.assertEqual(self.session.mutation_calls(), [])
        self.assertIn("Demo account", output)

    def test_read_execution_flag_adds_only_explicit_read(self):
        self.session.executions = [execution_response([fill()])]
        code, output, _ = self.invoke(["read", "--symbol", "BTCUSDT", "--executions"])
        self.assertEqual(code, 0)
        self.assertEqual(self.session.calls[-1], ("get_executions", {"category": "spot", "execType": "Trade", "limit": 100, "symbol": "BTCUSDT"}))
        self.assertIn("ExecutionState", output)
        self.assertEqual(self.session.mutation_calls(), [])

    def test_read_mode_rejects_action_flags_before_session(self):
        self.assert_blocked_before_session(["read", "--symbol", "BTCUSDT", "--confirm-demo-action"])

    def test_placement_requires_additional_action_opt_in(self):
        self.assert_blocked_before_session(PLACE[:-1])

    def test_cancellation_requires_additional_action_opt_in(self):
        self.assert_blocked_before_session(CANCEL[:-1])

    def test_missing_amount_cannot_default_to_a_purchase(self):
        args = PLACE.copy()
        del args[args.index("--amount"):args.index("--amount") + 2]
        self.assert_blocked_before_session(args)

    def test_missing_explicit_symbol_side_or_link_is_blocked(self):
        for field in ("--symbol", "--side", "--order-link-id"):
            args = PLACE.copy()
            offset = args.index(field)
            del args[offset:offset + 2]
            with self.subTest(field=field):
                self.assert_blocked_before_session(args)

    def test_missing_exact_cancellation_id_is_blocked(self):
        self.assert_blocked_before_session(["cancel", "--symbol", "BTCUSDT", "--confirm-demo-action"])

    def test_invalid_amounts_are_blocked_before_credentials_or_client(self):
        for amount in ("", "bad", "NaN", "sNaN", "Infinity", "-Infinity", "0", "-1", " 10", PRIVATE_TEXT):
            args = PLACE.copy()
            args[args.index("--amount") + 1] = amount
            with self.subTest(case=type(amount).__name__):
                self.assert_blocked_before_session(args)

    def test_invalid_side_and_arbitrary_unit_cannot_bypass_reviewed_units(self):
        args = PLACE.copy()
        args[args.index("--side") + 1] = "LONG_ENTRY"
        self.assert_blocked_before_session(args)
        self.assert_blocked_before_session(PLACE + ["--amount-unit", "BASE"])

    def test_malformed_symbol_link_and_order_id_block_before_session(self):
        for field, value in (("--symbol", "btcusdt"), ("--symbol", " BTCUSDT"),
                             ("--order-link-id", " id "), ("--order-link-id", "a" * 37)):
            args = PLACE.copy()
            args[args.index(field) + 1] = value
            self.assert_blocked_before_session(args)
        self.assert_blocked_before_session(["cancel", "--symbol", "BTCUSDT", "--order-id", " id ", "--confirm-demo-action"])

    def test_no_cli_routing_secret_or_order_type_overrides(self):
        for option in ("--live", "--testnet", "--endpoint", "--api-key", "--api-secret", "--order-type", "--leverage"):
            with self.subTest(option=option):
                self.assert_blocked_before_session(PLACE + [option, PRIVATE_TEXT])

    def test_explicit_buy_has_one_placement_no_automatic_read_or_cancel(self):
        code, output, _ = self.invoke(PLACE)
        self.assertEqual(code, 0)
        self.assertEqual([name for name, _ in self.session.calls], ["get_wallet_balance", "get_instruments_info", "place_order"])
        params = self.session.mutation_calls()[0][1]
        self.assertEqual(params, {"category": "spot", "symbol": "BTCUSDT", "side": "Buy", "orderType": "Market",
                                  "qty": "12.3456789", "marketUnit": "quoteCoin", "isLeverage": 0, "orderLinkId": "caller-1"})
        self.assertIn("not a fill", output)
        self.assertLess(output.index("authorization:"), output.index("Placement acceptance"))

    def test_explicit_sell_uses_authorized_base_amount(self):
        args = PLACE.copy()
        args[args.index("--side") + 1] = "SELL"
        args[args.index("--amount") + 1] = "0.1234569"
        self.assertEqual(self.invoke(args)[0], 0)
        params = self.session.mutation_calls()[0][1]
        self.assertEqual((params["side"], params["marketUnit"], params["qty"]), ("Sell", "baseCoin", "0.123456"))
        self.assertEqual(len(self.session.mutation_calls()), 1)

    def test_explicit_placement_read_after_observes_state_and_fills_once(self):
        self.session.realtime = [order_response([quote_order()])]
        self.session.executions = [execution_response([fill()])]
        code, output, _ = self.invoke(PLACE + ["--read-after"])
        self.assertEqual(code, 0)
        self.assertEqual([name for name, _ in self.session.calls],
                         ["get_wallet_balance", "get_instruments_info", "place_order", "get_open_orders", "get_executions"])
        self.assertIn("OrderState", output)
        self.assertIn("ExecutionState", output)
        self.assertEqual(len(self.session.mutation_calls()), 1)

    def test_explicit_cancel_has_exact_id_one_mutation_no_placement(self):
        code, output, _ = self.invoke(CANCEL)
        self.assertEqual(code, 0)
        self.assertEqual(self.session.calls, [("get_wallet_balance", {"accountType": "UNIFIED"}),
                                              ("cancel_order", {"category": "spot", "symbol": "BTCUSDT", "orderId": "order-1"})])
        self.assertIn("not terminal CANCELLED", output)

    def test_cancel_read_after_can_report_concurrent_fill(self):
        self.session.realtime = [order_response([quote_order()])]
        code, output, _ = self.invoke(CANCEL + ["--read-after"])
        self.assertEqual(code, 0)
        self.assertIn("OrderStatus.FILLED", output)
        self.assertEqual([name for name, _ in self.session.calls], ["get_wallet_balance", "cancel_order", "get_open_orders", "get_executions"])

    def test_read_only_connectivity_failure_prevents_any_action(self):
        self.session.errors["get_wallet_balance"] = RuntimeError(PRIVATE_TEXT)
        for args in (PLACE, CANCEL):
            self.session.calls.clear()
            self.assertEqual(self.invoke(args)[0], 1)
            self.assertEqual([name for name, _ in self.session.calls], ["get_wallet_balance"])
            self.assertEqual(self.session.mutation_calls(), [])

    def test_unsafe_routing_or_retry_settings_block_every_mode_before_broker_calls(self):
        for field, value in (("testnet", True), ("demo", False), ("endpoint", "https://api.bybit.com"),
                             ("endpoint", "https://unexpected.invalid"), ("max_retries", 2),
                             ("force_retry", True), ("retry_delay", 1), ("log_requests", True),
                             ("demo", None), ("max_retries", True)):
            original = getattr(self.session, field)
            setattr(self.session, field, value)
            for args in (["read", "--symbol", "BTCUSDT"], PLACE, CANCEL):
                with self.subTest(field=field, mode=args[0]):
                    self.assertEqual(self.invoke(args)[0], 1)
                    self.assertEqual(self.session.calls, [])
            setattr(self.session, field, original)

    def test_constraints_prevent_placement_and_never_increase_amount(self):
        args = PLACE.copy()
        args[args.index("--amount") + 1] = "1"
        self.assertEqual(self.invoke(args)[0], 1)
        self.assertEqual(self.session.mutation_calls(), [])
        self.session.calls.clear()
        args[args.index("--side") + 1] = "SELL"
        args[args.index("--amount") + 1] = "100"
        self.assertEqual(self.invoke(args)[0], 1)
        self.assertEqual(self.session.mutation_calls(), [])

    def test_raw_metadata_sdk_exception_is_reported_without_message_or_traceback(self):
        self.session.errors["get_instruments_info"] = RuntimeError(PRIVATE_TEXT)
        code, output, errors = self.invoke(["read", "--symbol", "BTCUSDT"])
        self.assertEqual(code, 1)
        self.assertEqual(output, "Demo smoke failed (RuntimeError).\n")
        self.assertEqual(errors, "")

    def test_ambiguous_placement_has_no_retry_or_read_after_even_when_requested(self):
        for error in (TimeoutError(PRIVATE_TEXT), ConnectionResetError(PRIVATE_TEXT), RuntimeError(PRIVATE_TEXT)):
            self.session.calls.clear()
            self.session.errors["place_order"] = error
            code, output, _ = self.invoke(PLACE + ["--read-after"])
            self.assertEqual(code, 1)
            self.assertIn("outcome is unknown", output)
            self.assertEqual([name for name, _ in self.session.calls], ["get_wallet_balance", "get_instruments_info", "place_order"])
            self.assertEqual(self.session.mutation_calls()[0][1]["orderLinkId"], "caller-1")

    def test_ambiguous_cancellation_has_no_retry_or_followup_read(self):
        self.session.errors["cancel_order"] = TimeoutError(PRIVATE_TEXT)
        code, output, _ = self.invoke(CANCEL + ["--read-after"])
        self.assertEqual(code, 1)
        self.assertIn("outcome is unknown", output)
        self.assertEqual([name for name, _ in self.session.calls], ["get_wallet_balance", "cancel_order"])

    def test_confirmed_rejection_is_explicit_without_retry_or_state_fabrication(self):
        self.session.placement = {"retCode": 10001, "retMsg": PRIVATE_TEXT}
        code, output, _ = self.invoke(PLACE + ["--read-after"])
        self.assertEqual(code, 1)
        self.assertIn("BybitDemoOrderRejectedError", output)
        self.assertNotIn("outcome is unknown", output)
        self.assertEqual([name for name, _ in self.session.calls], ["get_wallet_balance", "get_instruments_info", "place_order"])

    def test_malformed_acknowledgement_stays_unknown_without_resend(self):
        self.session.placement = {"retCode": 0, "result": {}, "retMsg": PRIVATE_TEXT}
        code, output, _ = self.invoke(PLACE + ["--read-after"])
        self.assertEqual(code, 1)
        self.assertIn("outcome is unknown", output)
        self.assertEqual([name for name, _ in self.session.calls], ["get_wallet_balance", "get_instruments_info", "place_order"])

    def test_unobserved_order_after_accepted_placement_is_not_resubmitted(self):
        code, output, _ = self.invoke(PLACE + ["--read-after"])
        self.assertEqual(code, 1)
        self.assertIn("BrokerOrderNotFoundError", output)
        self.assertEqual([name for name, _ in self.session.calls],
                         ["get_wallet_balance", "get_instruments_info", "place_order", "get_open_orders", "get_order_history"])
        self.assertEqual(len(self.session.mutation_calls()), 1)

    def test_private_response_extras_do_not_appear_in_normalized_console_output(self):
        self.session.wallet = with_private_extras(self.session.wallet)
        self.session.instrument = with_private_extras(self.session.instrument)
        self.session.placement = with_private_extras(self.session.placement)
        self.session.realtime = [with_private_extras(order_response([quote_order()]))]
        self.session.executions = [with_private_extras(execution_response([fill()]))]
        self.assertEqual(self.invoke(PLACE + ["--read-after"])[0], 0)

    def test_bad_demo_credentials_are_not_echoed_and_generic_names_cannot_fallback(self):
        for environment in ({"BYBIT_DEMO_API_KEY": " " + SECRETS[0], "BYBIT_DEMO_API_SECRET": SECRETS[1]},
                            {"BYBIT_API_KEY": SECRETS[0], "BYBIT_API_SECRET": SECRETS[1]}):
            with patch("trading_lab.exchange.bybit_demo.os.environ", environment):
                self.assertEqual(self.invoke(["read", "--symbol", "BTCUSDT"])[0], 1)
            self.factory.assert_not_called()

    def test_fixed_request_is_not_resized_using_connectivity_wallet_balance(self):
        wallet = deepcopy(self.session.wallet)
        for balance in ("0", "1000000000"):
            self.session.wallet["result"]["list"][0]["totalAvailableBalance"] = balance
            self.assertEqual(self.invoke(PLACE)[0], 0)
        self.assertEqual([params["qty"] for _, params in self.session.mutation_calls()], ["12.3456789"] * 2)
        self.assertEqual(self.session.wallet["result"]["list"][0]["totalEquity"], wallet["result"]["list"][0]["totalEquity"])

    def test_client_closes_after_success_and_failure(self):
        self.assertEqual(self.invoke(["read", "--symbol", "BTCUSDT"])[0], 0)
        self.session.client.close.assert_called_once()
        self.session.client.close.reset_mock()
        self.session.errors["get_wallet_balance"] = RuntimeError(PRIVATE_TEXT)
        self.assertEqual(self.invoke(CANCEL)[0], 1)
        self.session.client.close.assert_called_once()

    def test_cleanup_failure_is_nonzero_and_does_not_expose_sdk_exception(self):
        self.session.client.close.side_effect = RuntimeError(PRIVATE_TEXT)
        code, output, errors = self.invoke(["read", "--symbol", "BTCUSDT"])
        self.assertEqual(code, 1)
        self.assertIn("cleanup failed (RuntimeError)", output)
        self.assertEqual(errors, "")

    def test_script_has_no_runtime_loop_direct_sdk_calls_or_strategy_imports(self):
        path = Path(smoke.__file__)
        source = path.read_text()
        tree = ast.parse(source)
        self.assertFalse(any(isinstance(n, (ast.While, ast.AsyncFunctionDef)) for n in ast.walk(tree)))
        imports = [n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
        imports += [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
        self.assertFalse(any(any(part in name.split(".") for part in ("strategies", "backtest", "risk", "execution", "asyncio", "schedule")) for name in imports))
        for word in ("HTTP(", "os.environ", "sleep(", "get_wallet_balance", "place_order", "amend_order", "replace_order", "transfer", "withdraw"):
            self.assertNotIn(word, source)
        calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                 and isinstance(n.func.value, ast.Name) and n.func.value.id == "actions"]
        self.assertEqual({n.func.attr for n in calls}, {"place_market_order", "cancel_order"})


if __name__ == "__main__":
    unittest.main()
