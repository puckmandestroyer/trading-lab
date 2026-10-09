"""Offline Demo credential and session safety checks; all values are synthetic."""

from collections.abc import Mapping
from dataclasses import FrozenInstanceError
import inspect
from pathlib import Path
import subprocess
import sys
import textwrap
from types import MappingProxyType
import unittest
from unittest.mock import patch, sentinel

from pybit.unified_trading import HTTP
import requests

import trading_lab.exchange as exchange
from trading_lab.exchange.bybit_demo import (
    BybitDemoConfigurationError,
    BybitDemoCredentials,
    create_bybit_demo_session,
    load_bybit_demo_credentials,
)


# Deliberately recognizable dummy values; no account or credentials are needed.
DUMMY_KEY = "offline-demo-key"
DUMMY_SECRET = "offline-demo-secret"


def demo_environment():
    return {
        "BYBIT_DEMO_API_KEY": DUMMY_KEY,
        "BYBIT_DEMO_API_SECRET": DUMMY_SECRET,
    }


class CredentialTests(unittest.TestCase):
    def test_valid_direct_construction_preserves_values(self):
        credentials = BybitDemoCredentials(DUMMY_KEY, DUMMY_SECRET)
        self.assertEqual(credentials.api_key, DUMMY_KEY)
        self.assertEqual(credentials.api_secret, DUMMY_SECRET)

    def test_credentials_are_frozen(self):
        credentials = BybitDemoCredentials(DUMMY_KEY, DUMMY_SECRET)
        for name in ("api_key", "api_secret"):
            with self.subTest(field=name), self.assertRaises(FrozenInstanceError):
                setattr(credentials, name, "replacement-dummy")

    def test_credentials_use_slots(self):
        credentials = BybitDemoCredentials(DUMMY_KEY, DUMMY_SECRET)
        self.assertFalse(hasattr(credentials, "__dict__"))
        self.assertEqual(set(credentials.__slots__), {"api_key", "api_secret"})

    def test_repr_omits_both_values(self):
        credentials = BybitDemoCredentials(DUMMY_KEY, DUMMY_SECRET)
        self.assertNotIn(DUMMY_KEY, repr(credentials))
        self.assertNotIn(DUMMY_SECRET, repr(credentials))

    def test_str_omits_both_values(self):
        credentials = BybitDemoCredentials(DUMMY_KEY, DUMMY_SECRET)
        self.assertNotIn(DUMMY_KEY, str(credentials))
        self.assertNotIn(DUMMY_SECRET, str(credentials))

    def test_empty_key_rejected(self):
        with self.assertRaises(BybitDemoConfigurationError):
            BybitDemoCredentials("", DUMMY_SECRET)

    def test_empty_secret_rejected(self):
        with self.assertRaises(BybitDemoConfigurationError):
            BybitDemoCredentials(DUMMY_KEY, "")

    def test_whitespace_only_key_rejected(self):
        for value in (" ", "\t\n", "\u2003"):
            with self.subTest(value=value), self.assertRaises(BybitDemoConfigurationError):
                BybitDemoCredentials(value, DUMMY_SECRET)

    def test_whitespace_only_secret_rejected(self):
        for value in (" ", "\t\n", "\u2003"):
            with self.subTest(value=value), self.assertRaises(BybitDemoConfigurationError):
                BybitDemoCredentials(DUMMY_KEY, value)

    def test_surrounding_whitespace_key_rejected_without_stripping(self):
        for value in (" " + DUMMY_KEY, DUMMY_KEY + "\n"):
            with self.subTest(value=value), self.assertRaises(BybitDemoConfigurationError):
                BybitDemoCredentials(value, DUMMY_SECRET)

    def test_surrounding_whitespace_secret_rejected_without_stripping(self):
        for value in ("\t" + DUMMY_SECRET, DUMMY_SECRET + " "):
            with self.subTest(value=value), self.assertRaises(BybitDemoConfigurationError):
                BybitDemoCredentials(DUMMY_KEY, value)

    def test_non_string_key_rejected(self):
        for value in (None, 123, True, b"dummy-key", ["dummy-key"]):
            with self.subTest(value=value), self.assertRaises(BybitDemoConfigurationError):
                BybitDemoCredentials(value, DUMMY_SECRET)

    def test_non_string_secret_rejected(self):
        for value in (None, 123, True, b"dummy-secret", ["dummy-secret"]):
            with self.subTest(value=value), self.assertRaises(BybitDemoConfigurationError):
                BybitDemoCredentials(DUMMY_KEY, value)

    def test_validation_errors_name_variable_without_values(self):
        for field, variable in (
            ("api_key", "BYBIT_DEMO_API_KEY"),
            ("api_secret", "BYBIT_DEMO_API_SECRET"),
        ):
            values = {"api_key": DUMMY_KEY, "api_secret": DUMMY_SECRET}
            invalid = " " + values[field]
            values[field] = invalid
            with self.subTest(field=field), self.assertRaises(BybitDemoConfigurationError) as error:
                BybitDemoCredentials(**values)
            self.assertIn(variable, str(error.exception))
            for value in (invalid, DUMMY_KEY, DUMMY_SECRET):
                self.assertNotIn(value, str(error.exception))

    def test_opaque_values_have_no_length_case_or_character_restrictions(self):
        credentials = BybitDemoCredentials("K", "s e!ç")
        self.assertEqual(credentials.api_key, "K")
        self.assertEqual(credentials.api_secret, "s e!ç")


class EnvironmentLoaderTests(unittest.TestCase):
    def test_supplied_mapping_loads_only_its_values(self):
        with patch("trading_lab.exchange.bybit_demo.os.environ", {}):
            credentials = load_bybit_demo_credentials(MappingProxyType(demo_environment()))
        self.assertEqual(credentials, BybitDemoCredentials(DUMMY_KEY, DUMMY_SECRET))

    def test_none_reads_environment_at_each_call(self):
        with patch("trading_lab.exchange.bybit_demo.os.environ", demo_environment()):
            first = load_bybit_demo_credentials()
        second_environment = {
            "BYBIT_DEMO_API_KEY": "second-offline-key",
            "BYBIT_DEMO_API_SECRET": "second-offline-secret",
        }
        with patch("trading_lab.exchange.bybit_demo.os.environ", second_environment):
            second = load_bybit_demo_credentials(None)
        self.assertEqual(first.api_key, DUMMY_KEY)
        self.assertEqual(second.api_key, "second-offline-key")
        self.assertEqual(second.api_secret, "second-offline-secret")
        self.assertIsNot(first, second)

    def test_missing_key_rejected(self):
        with self.assertRaisesRegex(BybitDemoConfigurationError, "BYBIT_DEMO_API_KEY"):
            load_bybit_demo_credentials({"BYBIT_DEMO_API_SECRET": DUMMY_SECRET})

    def test_missing_secret_rejected(self):
        with self.assertRaisesRegex(BybitDemoConfigurationError, "BYBIT_DEMO_API_SECRET"):
            load_bybit_demo_credentials({"BYBIT_DEMO_API_KEY": DUMMY_KEY})

    def test_both_missing_rejected(self):
        with self.assertRaises(BybitDemoConfigurationError):
            load_bybit_demo_credentials({})

    def test_empty_values_rejected(self):
        for variable in demo_environment():
            values = demo_environment()
            values[variable] = ""
            with self.subTest(variable=variable), self.assertRaises(BybitDemoConfigurationError):
                load_bybit_demo_credentials(values)

    def test_whitespace_values_rejected(self):
        for variable in demo_environment():
            for value in (" ", "\t\n"):
                values = demo_environment()
                values[variable] = value
                with self.subTest(variable=variable, value=value), self.assertRaises(BybitDemoConfigurationError):
                    load_bybit_demo_credentials(values)

    def test_surrounding_whitespace_values_rejected(self):
        for variable in demo_environment():
            values = demo_environment()
            values[variable] = " " + values[variable]
            with self.subTest(variable=variable), self.assertRaises(BybitDemoConfigurationError):
                load_bybit_demo_credentials(values)

    def test_non_mapping_rejected(self):
        for value in ([], (), "dummy", 123, True):
            with self.subTest(value=value), self.assertRaisesRegex(BybitDemoConfigurationError, "Mapping"):
                load_bybit_demo_credentials(value)

    def test_mapping_unchanged_on_success_and_failure(self):
        for invalid in (False, True):
            values = demo_environment()
            values["UNRELATED"] = "unchanged"
            if invalid:
                values["BYBIT_DEMO_API_SECRET"] += " "
            before = values.copy()
            if invalid:
                with self.assertRaises(BybitDemoConfigurationError):
                    load_bybit_demo_credentials(values)
            else:
                load_bybit_demo_credentials(values)
            self.assertEqual(values, before)

    def test_legacy_exchange_names_are_not_credentials(self):
        with self.assertRaises(BybitDemoConfigurationError):
            load_bybit_demo_credentials({
                "EXCHANGE_API_KEY": DUMMY_KEY,
                "EXCHANGE_API_SECRET": DUMMY_SECRET,
            })

    def test_generic_bybit_names_are_not_credentials(self):
        with self.assertRaises(BybitDemoConfigurationError):
            load_bybit_demo_credentials({
                "BYBIT_API_KEY": DUMMY_KEY,
                "BYBIT_API_SECRET": DUMMY_SECRET,
            })

    def test_only_demo_names_are_used_when_legacy_names_exist(self):
        values = demo_environment()
        values.update({
            "EXCHANGE_API_KEY": "legacy-offline-key",
            "EXCHANGE_API_SECRET": "legacy-offline-secret",
            "BYBIT_API_KEY": "generic-offline-key",
            "BYBIT_API_SECRET": "generic-offline-secret",
        })
        credentials = load_bybit_demo_credentials(values)
        self.assertEqual(credentials.api_key, DUMMY_KEY)
        self.assertEqual(credentials.api_secret, DUMMY_SECRET)

    def test_partial_demo_configuration_does_not_fall_back(self):
        for missing in demo_environment():
            values = demo_environment()
            del values[missing]
            values.update({
                "EXCHANGE_API_KEY": DUMMY_KEY,
                "EXCHANGE_API_SECRET": DUMMY_SECRET,
                "BYBIT_API_KEY": DUMMY_KEY,
                "BYBIT_API_SECRET": DUMMY_SECRET,
            })
            with self.subTest(missing=missing), self.assertRaises(BybitDemoConfigurationError):
                load_bybit_demo_credentials(values)

    def test_error_names_variable_without_exposing_mapping_or_secret(self):
        values = demo_environment()
        values["BYBIT_DEMO_API_SECRET"] += " "
        values["UNRELATED"] = "private-offline-marker"
        with self.assertRaises(BybitDemoConfigurationError) as error:
            load_bybit_demo_credentials(values)
        message = str(error.exception)
        self.assertIn("BYBIT_DEMO_API_SECRET", message)
        for value in values.values():
            self.assertNotIn(value.strip(), message)

    def test_only_two_demo_variables_are_read(self):
        class RecordingMapping(Mapping):
            def __init__(self):
                self.reads = []

            def __getitem__(self, name):
                self.reads.append(name)
                return demo_environment()[name]

            def __iter__(self):
                raise AssertionError("The whole mapping must not be inspected")

            def __len__(self):
                return 2

        values = RecordingMapping()
        load_bybit_demo_credentials(values)
        self.assertEqual(values.reads, ["BYBIT_DEMO_API_KEY", "BYBIT_DEMO_API_SECRET"])


class SessionFactoryTests(unittest.TestCase):
    def test_exact_constructor_settings_and_return_value(self):
        credentials = BybitDemoCredentials(DUMMY_KEY, DUMMY_SECRET)
        with patch("trading_lab.exchange.bybit_demo.HTTP", return_value=sentinel.session) as constructor:
            result = create_bybit_demo_session(credentials)
        self.assertIs(result, sentinel.session)
        constructor.assert_called_once_with(
            testnet=False,
            demo=True,
            api_key=DUMMY_KEY,
            api_secret=DUMMY_SECRET,
            force_retry=False,
            max_retries=1,
            retry_delay=0,
            log_requests=False,
        )

    def test_wrong_credential_types_rejected_before_construction(self):
        for value in (None, DUMMY_KEY, {}, (DUMMY_KEY, DUMMY_SECRET), object()):
            with self.subTest(value=value), patch("trading_lab.exchange.bybit_demo.HTTP") as constructor:
                with self.assertRaises(BybitDemoConfigurationError) as error:
                    create_bybit_demo_session(value)
                constructor.assert_not_called()
                self.assertNotIn(DUMMY_KEY, str(error.exception))
                self.assertNotIn(DUMMY_SECRET, str(error.exception))

    def test_real_pybit_construction_is_offline_and_demo_only(self):
        with patch.object(requests.Session, "send", side_effect=AssertionError("No network send")) as send:
            with patch.object(requests.Session, "request", side_effect=AssertionError("No request")) as request:
                credentials = load_bybit_demo_credentials(demo_environment())
                session = create_bybit_demo_session(credentials)
                try:
                    self.assertIsInstance(session, HTTP)
                    self.assertEqual(session.endpoint, "https://api-demo.bybit.com")
                    self.assertIs(session.testnet, False)
                    self.assertIs(session.demo, True)
                    self.assertIs(session.force_retry, False)
                    self.assertEqual(session.max_retries, 1)
                    self.assertEqual(session.retry_delay, 0)
                    self.assertIs(session.log_requests, False)
                    send.assert_not_called()
                    request.assert_not_called()
                finally:
                    session.client.close()

    def test_each_call_creates_an_independent_client(self):
        credentials = BybitDemoCredentials(DUMMY_KEY, DUMMY_SECRET)
        with patch.object(requests.Session, "send", side_effect=AssertionError("No network send")):
            with patch.object(requests.Session, "request", side_effect=AssertionError("No request")):
                first = create_bybit_demo_session(credentials)
                second = create_bybit_demo_session(credentials)
                try:
                    self.assertIsNot(first, second)
                    self.assertIsNot(first.client, second.client)
                finally:
                    first.client.close()
                    second.client.close()

    def test_factory_signature_has_only_credentials(self):
        signature = inspect.signature(create_bybit_demo_session)
        self.assertEqual(list(signature.parameters), ["credentials"])
        self.assertEqual(signature.parameters["credentials"].kind, inspect.Parameter.POSITIONAL_OR_KEYWORD)

    def test_environment_overrides_are_not_accepted(self):
        credentials = BybitDemoCredentials(DUMMY_KEY, DUMMY_SECRET)
        for name in ("testnet", "demo", "mainnet", "real_trading", "production_mode", "endpoint", "base_url", "domain", "tld"):
            with self.subTest(name=name), patch("trading_lab.exchange.bybit_demo.HTTP") as constructor:
                with self.assertRaises(TypeError):
                    create_bybit_demo_session(credentials, **{name: "override"})
                constructor.assert_not_called()

    def test_factory_does_not_mutate_credentials(self):
        credentials = BybitDemoCredentials(DUMMY_KEY, DUMMY_SECRET)
        with patch("trading_lab.exchange.bybit_demo.HTTP"):
            create_bybit_demo_session(credentials)
        self.assertEqual(credentials.api_key, DUMMY_KEY)
        self.assertEqual(credentials.api_secret, DUMMY_SECRET)

    def test_project_factory_does_not_print_or_log_the_client(self):
        credentials = BybitDemoCredentials(DUMMY_KEY, DUMMY_SECRET)
        with patch("trading_lab.exchange.bybit_demo.HTTP", return_value=sentinel.session):
            with patch("builtins.print") as output, patch("logging.getLogger") as logger:
                create_bybit_demo_session(credentials)
                output.assert_not_called()
                logger.assert_not_called()


class ImportSafetyTests(unittest.TestCase):
    def test_package_exports_exactly_the_four_configuration_names(self):
        expected = {
            "BybitDemoConfigurationError": BybitDemoConfigurationError,
            "BybitDemoCredentials": BybitDemoCredentials,
            "load_bybit_demo_credentials": load_bybit_demo_credentials,
            "create_bybit_demo_session": create_bybit_demo_session,
        }
        self.assertEqual(set(exchange.__all__), set(expected))
        for name, value in expected.items():
            self.assertIs(getattr(exchange, name), value)

    def assert_fresh_import_safe(self, module_name):
        # A fresh interpreter avoids changing the test runner's module cache.
        script = textwrap.dedent("""
            import importlib
            import os
            from unittest.mock import patch
            import requests
            import pybit.unified_trading

            class NoEnvironmentReads(dict):
                def __getitem__(self, name):
                    raise AssertionError('Import must not read environment')
                def get(self, name, default=None):
                    raise AssertionError('Import must not read environment')

            with patch('os.environ', NoEnvironmentReads()):
                with patch('pybit.unified_trading.HTTP', side_effect=AssertionError('No import-time HTTP client')) as constructor:
                    with patch.object(requests.Session, 'send', side_effect=AssertionError('No network send')) as send:
                        with patch.object(requests.Session, 'request', side_effect=AssertionError('No request')) as request:
                            importlib.import_module(MODULE_NAME)
                            constructor.assert_not_called()
                            send.assert_not_called()
                            request.assert_not_called()
        """).replace("MODULE_NAME", repr(module_name))
        src = Path(__file__).resolve().parents[1] / "src"
        result = subprocess.run(
            [sys.executable, "-c", script],
            env={"PYTHONPATH": str(src), "PYTHONDONTWRITEBYTECODE": "1"},
            capture_output=True,
            text=True,
            timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")

    def test_package_import_has_no_environment_session_or_network_side_effect(self):
        self.assert_fresh_import_safe("trading_lab.exchange")

    def test_module_import_has_no_environment_session_or_network_side_effect(self):
        self.assert_fresh_import_safe("trading_lab.exchange.bybit_demo")


if __name__ == "__main__":
    unittest.main()
