"""Installed Streamlit AppTest only: synthetic local data, no server/browser."""

import ast
import importlib.util
from pathlib import Path
import socket
import tomllib
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import requests
import streamlit
from streamlit.testing.v1 import AppTest

from trading_lab.dashboard import DASHBOARD_VIEWS
from tests import test_dashboard_model as f
from tests import test_dashboard_analytics as analytics_fixtures

PROJECT = Path(__file__).resolve().parents[1]
APP = PROJECT / "dashboard" / "app.py"


def simulated_app(root):
    from dashboard.app import main
    main(["--observability-root", root])


class DashboardAppTests(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(TemporaryDirectory())
        self.root = Path(directory).resolve() / "observability"
        self.root.mkdir(mode=0o700)
        self.enterContext(patch.object(requests.Session, "send", side_effect=AssertionError("network forbidden")))
        self.enterContext(patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")))

    def run_app(self):
        app = AppTest.from_function(simulated_app, args=(str(self.root),), default_timeout=10).run()
        self.assertEqual(len(app.exception), 0)
        return app

    def test_app_import_does_not_launch_or_render(self):
        spec = importlib.util.spec_from_file_location("dashboard_import_smoke", APP)
        module = importlib.util.module_from_spec(spec)
        with patch.object(streamlit, "set_page_config", side_effect=AssertionError("must not run on import")):
            spec.loader.exec_module(module)
        self.assertTrue(callable(module.main))
        self.assertTrue(callable(module.render_dashboard))

    def test_six_view_app_renders_current_identity_without_mutation_controls(self):
        f.write_instance(self.root, events=(f.event_fixture(),))
        app = self.run_app()
        self.assertEqual(tuple(tab.label for tab in app.tabs), DASHBOARD_VIEWS)
        self.assertIn("ema_trend · BTCUSDT · 1H · bot1", app.selectbox[0].options[0])
        self.assertEqual([metric.label for metric in app.metric[:6]],
            ["Net P&L", "Return vs Risk Capital", "Risk Equity", "Drawdown", "Daily P&L", "Position"])
        identities = [table.value for table in app.dataframe if "Field" in table.value.columns
                      and "timeframe" in table.value["Field"].tolist()]
        self.assertEqual(len(identities), 1)
        self.assertEqual(identities[0]["Value"].tolist(), ["bybit-demo", "research", "bot1", "ema_trend", "BTCUSDT", "60"])
        self.assertEqual([button.label for button in app.button], ["Refresh local files"])
        self.assertEqual(len(app.get("form")), 0)
        self.assertEqual(app.multiselect[0].value, ["INFO", "WARNING", "ERROR", "CRITICAL"])

    def test_two_strategies_use_same_ui_template_and_selector(self):
        first = f.write_instance(self.root, f.health_fixture(), (f.event_fixture(),))
        second = f.write_instance(self.root, f.health_fixture(strategy="donchian", symbol="ETHUSDT", bot="bot2"),
            (f.event_fixture(strategy="donchian", symbol="ETHUSDT", bot="bot2"),))
        app = self.run_app()
        self.assertIn("donchian · ETHUSDT · 1H · bot2", app.selectbox[0].options[0])
        self.assertEqual(app.selectbox[0].value, second.name)
        labels = [metric.label for metric in app.metric]
        app.selectbox[0].select(first.name).run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(app.selectbox[0].value, first.name)
        self.assertEqual([metric.label for metric in app.metric], labels)
        self.assertEqual(tuple(tab.label for tab in app.tabs), DASHBOARD_VIEWS)
        app.selectbox[0].select(second.name).run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(app.selectbox[0].value, second.name)

    def test_empty_root_sanitized_empty_state_no_invented_instance(self):
        app = self.run_app()
        self.assertIn("No valid Trading Lab observability instance found.", [item.value for item in app.info])
        self.assertEqual(list(self.root.iterdir()), [])

    def test_invalid_root_and_missing_cli_argument_are_sanitized(self):
        app = AppTest.from_function(simulated_app, args=(str(self.root / "SECRET-PATH"),)).run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(len(app.error), 1)
        self.assertNotIn("SECRET-PATH", app.error[0].value)
        from dashboard.app import main
        with patch.object(streamlit, "set_page_config"), patch.object(streamlit, "error") as error:
            main([])
        self.assertEqual(error.call_count, 1)

    def test_halt_and_snapshot_staleness_visible(self):
        f.write_instance(self.root, f.health_fixture(state="HALTED"))
        app = self.run_app()
        self.assertTrue(any("CRITICAL" in item.value and "STALE" in item.value for item in app.error))
        self.assertTrue(any("HALTED" in item.value for item in app.error))

    def test_long_without_open_history_displays_incomplete_not_trade(self):
        f.write_instance(self.root, f.health_fixture(state="LONG"))
        app = self.run_app()
        self.assertTrue(any("History incomplete / unavailable" in item.value for item in app.warning))
        self.assertFalse(any("Realized PnL (quote)" in table.value.columns for table in app.dataframe))

    def test_closed_cycle_missing_pnl_is_unavailable_and_chart_smoke(self):
        f.write_instance(self.root, events=analytics_fixtures.cycle())
        app = self.run_app()
        trades = [table.value for table in app.dataframe if "Realized PnL (quote)" in table.value.columns]
        self.assertEqual(len(trades), 2)  # Bounded Overview preview and the full Trades view.
        for table in trades:
            self.assertEqual(table["Realized PnL (quote)"].tolist(), ["Unavailable"])

    def test_project_local_light_theme_without_frontend_hacks(self):
        theme = tomllib.loads((PROJECT / ".streamlit" / "config.toml").read_text())
        self.assertEqual(set(theme), {"theme"})
        self.assertEqual(theme["theme"]["base"], "light")
        self.assertEqual(theme["theme"]["backgroundColor"], "#FFFFFF")
        self.assertNotIn("unsafe_allow_html", APP.read_text())

    def test_model_selector_on_main_page_not_sidebar(self):
        f.write_instance(self.root)
        app = self.run_app()
        self.assertEqual(app.selectbox[0].label, "◈ Strategy Model")
        self.assertEqual(len(app.sidebar.selectbox), 0)
        self.assertEqual(len(app.sidebar.button), 0)

    def test_positive_performance_cards_and_explicit_insufficient_history(self):
        f.write_instance(self.root, f.performance_health())
        app = self.run_app()
        self.assertEqual([metric.value for metric in app.metric[:6]],
            ["+125.25 USDT", "+12.525%", "1125.25 USDT", "0%", "+125.25 USDT", "FLAT"])
        self.assertIn("Insufficient performance history.", [item.value for item in app.info])
        self.assertIn("Current Return: +12.525%", [item.value for item in app.text])
        self.assertTrue(any(item.value == "Strategy Performance %" for item in app.subheader))

    def test_negative_performance_cards_with_adverse_drawdown(self):
        f.write_instance(self.root, f.performance_health("900"))
        app = self.run_app()
        self.assertEqual([metric.value for metric in app.metric[:6]],
            ["-100 USDT", "-10%", "900 USDT", "-10%", "-100 USDT", "FLAT"])
        self.assertEqual(app.metric[0].delta, "-10%")

    def test_genuine_zero_current_performance(self):
        f.write_instance(self.root, f.performance_health("1000"))
        app = self.run_app()
        self.assertEqual([metric.value for metric in app.metric[:2]], ["0 USDT", "0%"])

    def test_currency_comes_from_selected_validated_health(self):
        f.write_instance(self.root, f.performance_health(quote_currency="USDC"))
        app = self.run_app()
        self.assertEqual(app.metric[0].value, "+125.25 USDC")
        self.assertEqual(app.metric[2].value, "1125.25 USDC")
        self.assertIn("BTCUSDC", app.selectbox[0].options[0])

    def test_unavailable_current_performance_never_zero(self):
        f.write_instance(self.root, f.health_fixture(active=False))
        app = self.run_app()
        self.assertEqual([metric.value for metric in app.metric[:5]], ["Unavailable"]*5)
        self.assertIn("Current Return: Unavailable", [item.value for item in app.text])

    def test_snapshot_twenty_percent_does_not_create_chart(self):
        f.write_instance(self.root, f.performance_health("1200"))
        app = self.run_app()
        self.assertEqual(app.metric[1].value, "+20%")
        self.assertIn("Current Return: +20%", [item.value for item in app.text])
        self.assertEqual(len(app.get("vega_lite_chart")), 0)

    def test_multiple_retained_compatible_points_render_performance_chart(self):
        health = f.performance_health()
        events = tuple(f.risk_observation(value, n, digest=health.risk_configuration_digest)
                       for n, value in enumerate(("1000", "1025", "980", "1100")))
        f.write_instance(self.root, health, events)
        app = self.run_app()
        self.assertFalse(any(item.value == "Insufficient performance history." for item in app.info))
        self.assertGreaterEqual(len(app.get("vega_lite_chart")), 1)
        exact = [table.value for table in app.dataframe if "Return % (Decimal)" in table.value.columns]
        self.assertEqual(exact[0]["Return % (Decimal)"].tolist(), ["0%", "+2.5%", "-2%", "+10%"])

    def test_one_retained_point_keeps_current_return_without_graph(self):
        health = f.performance_health()
        f.write_instance(self.root, health, (f.risk_observation("1000", digest=health.risk_configuration_digest),))
        app = self.run_app()
        self.assertIn("Insufficient performance history.", [item.value for item in app.info])
        self.assertEqual(len(app.get("vega_lite_chart")), 0)

    def test_incompatible_history_is_explicit_and_not_plotted(self):
        f.write_instance(self.root, f.performance_health(),
            (f.risk_observation("1500", 0, digest="e"*64), f.risk_observation("1600", 1, digest="e"*64)))
        app = self.run_app()
        self.assertTrue(any("Performance history incomplete" in item.value for item in app.caption))
        self.assertIn("Insufficient performance history.", [item.value for item in app.info])

    def test_overview_preview_bounded_to_five_confirmed_cycles(self):
        events = tuple(event for n in range(7) for event in (
            f.event_fixture(f.T.POSITION_OPEN_CONFIRMED, sequence=n*2+1, occurred=f.AT+n*2),
            f.event_fixture(f.T.POSITION_CLOSE_CONFIRMED, sequence=n*2+2, occurred=f.AT+n*2+1)))
        f.write_instance(self.root, events=events)
        app = self.run_app()
        trades = [table.value for table in app.dataframe if "Realized PnL (quote)" in table.value.columns]
        self.assertEqual([len(table) for table in trades], [5, 7])
        self.assertEqual(trades[0]["Close reference"].tolist(), list(reversed(trades[1]["Close reference"].tolist()))[:5])

    def test_future_generic_strategy_has_same_performance_history_component(self):
        health = f.performance_health(strategy="donchian", symbol="ETHUSDT", bot="bot2")
        events = tuple(f.risk_observation(value, n, digest=health.risk_configuration_digest,
            strategy="donchian", symbol="ETHUSDT", bot="bot2") for n, value in enumerate(("1000", "1100")))
        f.write_instance(self.root, health, events)
        app = self.run_app()
        self.assertEqual(app.metric[0].value, "+125.25 USDT")
        self.assertEqual(tuple(tab.label for tab in app.tabs), DASHBOARD_VIEWS)
        self.assertGreaterEqual(len(app.get("vega_lite_chart")), 1)

    def test_event_severity_and_type_filters_rerender_readonly(self):
        events = (f.event_fixture(), f.event_fixture(f.T.RUNTIME_HALTED), f.event_fixture(f.T.RISK_TRIPPED))
        f.write_instance(self.root, events=events)
        app = self.run_app()
        app.multiselect[0].set_value(["CRITICAL"]).run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(set(app.dataframe[-1].value["Severity"]), {"CRITICAL"})
        app.multiselect[1].set_value(["PROCESS_STARTED"]).run()
        self.assertEqual(len(app.exception), 0)
        self.assertTrue(any(item.value == "No retained records available." for item in app.info))

    def test_refresh_does_not_change_local_artifacts(self):
        directory = f.write_instance(self.root, events=(f.event_fixture(),))
        before = {file.name: file.read_bytes() for file in directory.iterdir()}
        app = self.run_app()
        app.button[0].click().run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(before, {file.name: file.read_bytes() for file in directory.iterdir()})

    def test_no_strategy_specific_ui_or_trading_network_write_dependencies(self):
        files = tuple((PROJECT / "src" / "trading_lab" / "dashboard").glob("*.py")) + (APP,)
        forbidden_modules = {"runtime", "risk", "exchange", "strategies", "backtest", "sqlite3", "requests",
                             "socket", "telegram", "urllib", "http", "subprocess"}
        forbidden_calls = {"RuntimeStore", "connect", "place_order", "cancel_order", "send_message", "deliver_telegram_event",
            "save_checkpoint", "rearm_runtime", "rearm_risk", "write_bytes", "write_text", "mkdir", "chmod", "unlink",
            "remove", "rmdir", "Thread", "Process", "exec", "eval", "__import__"}
        for file in files:
            source = file.read_text()
            for text in ("ema_trend", "BTCUSDT", "bot1", "donchian", "ema_fast", "ema_slow", "EMA crossover", "fast_span", "slow_span"):
                self.assertNotIn(text, source, (file.name, text))
            for node in ast.walk(ast.parse(source)):
                if isinstance(node, ast.Import):
                    self.assertFalse({part for name in node.names for part in name.name.split('.')} & forbidden_modules)
                if isinstance(node, ast.ImportFrom):
                    self.assertFalse(set((node.module or "").split('.')) & forbidden_modules)
                if isinstance(node, ast.Call):
                    name = node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id if isinstance(node.func, ast.Name) else ""
                    self.assertNotIn(name, forbidden_calls, (file.name, name))
                    if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
                        self.assertNotIn((node.func.value.id, name), {("os", "replace"), ("os", "rename")})
