"""Synthetic scalar tests for the Decision-011 capital-budget contract."""

from fractions import Fraction
from math import inf, isfinite, nextafter
import unittest

import numpy as np
import pandas as pd

from trading_lab.risk.position_sizing import calculate_position_budget


class PositionSizingTests(unittest.TestCase):
    def test_default_fraction_allocates_all_current_capital(self):
        self.assertEqual(calculate_position_budget(10_000), 10_000.0)

    def test_explicit_full_fraction(self):
        self.assertEqual(calculate_position_budget(10_000, 1.0), 10_000.0)

    def test_half_fraction(self):
        self.assertEqual(calculate_position_budget(10_000, 0.5), 5_000.0)

    def test_quarter_fraction(self):
        self.assertEqual(calculate_position_budget(10_000, 0.25), 2_500.0)

    def test_budget_uses_current_capital(self):
        self.assertEqual(calculate_position_budget(10_000, 0.5), 5_000.0)
        self.assertEqual(calculate_position_budget(10_500, 0.5), 5_250.0)

    def test_small_positive_fraction_has_no_arbitrary_minimum(self):
        self.assertEqual(calculate_position_budget(10_000, 1e-300), 1e-296)

    def test_smallest_positive_float_fraction_is_valid_when_budget_is_positive(self):
        smallest = nextafter(0.0, 1.0)
        self.assertGreater(smallest, 0)
        self.assertEqual(calculate_position_budget(1.0, smallest), smallest)

    def test_smallest_positive_float_capital_is_valid_at_full_allocation(self):
        smallest = nextafter(0.0, 1.0)
        self.assertEqual(calculate_position_budget(smallest), smallest)

    def test_largest_finite_float_capital_is_valid(self):
        largest = float.fromhex("0x1.fffffffffffffp+1023")
        self.assertTrue(isfinite(largest))
        self.assertEqual(calculate_position_budget(largest), largest)

    def test_python_integer_and_float_capital(self):
        for capital in (10_000, 10_000.0):
            with self.subTest(capital_type=type(capital).__name__):
                self.assertEqual(calculate_position_budget(capital, 0.5), 5_000.0)

    def test_numpy_integer_scalar_capital(self):
        for capital in (np.int32(10_000), np.int64(10_000), np.uint64(10_000)):
            with self.subTest(capital_type=type(capital).__name__):
                self.assertEqual(calculate_position_budget(capital, 0.5), 5_000.0)

    def test_numpy_floating_scalar_capital(self):
        for capital in (np.float32(10_000), np.float64(10_000)):
            with self.subTest(capital_type=type(capital).__name__):
                self.assertEqual(calculate_position_budget(capital, 0.5), 5_000.0)

    def test_python_numeric_fractions(self):
        for fraction, expected in ((1, 10_000.0), (1.0, 10_000.0), (0.5, 5_000.0), (0.25, 2_500.0)):
            with self.subTest(fraction=fraction):
                self.assertEqual(calculate_position_budget(10_000, fraction), expected)

    def test_numpy_numeric_scalar_fractions(self):
        for fraction, expected in ((np.int64(1), 10_000.0), (np.float32(0.5), 5_000.0), (np.float64(0.25), 2_500.0)):
            with self.subTest(fraction_type=type(fraction).__name__):
                self.assertEqual(calculate_position_budget(10_000, fraction), expected)

    def test_exact_real_numeric_scalars(self):
        self.assertEqual(calculate_position_budget(Fraction(10_500), Fraction(1, 2)), 5_250.0)

    def test_output_type_is_always_exact_python_float(self):
        for capital, fraction in ((10_000, 1), (10_000.0, 0.5), (np.int64(10_000), np.float64(0.25))):
            with self.subTest(capital_type=type(capital).__name__, fraction_type=type(fraction).__name__):
                self.assertIs(type(calculate_position_budget(capital, fraction)), float)

    def test_repeated_calls_are_identical(self):
        first = calculate_position_budget(10_500, 0.25)
        self.assertEqual(first, 2_625.0)
        self.assertEqual(calculate_position_budget(10_500, 0.25), first)

    def test_nonpositive_capital_is_rejected(self):
        for capital in (0, 0.0, -0.0, -1, -0.5, np.int64(0), np.float64(-1)):
            with self.subTest(capital=capital):
                with self.assertRaisesRegex(ValueError, "capital_before"):
                    calculate_position_budget(capital)

    def test_python_and_numpy_boolean_capital_is_rejected(self):
        for capital in (True, False, np.bool_(True), np.bool_(False)):
            with self.subTest(capital_type=type(capital).__name__, capital=capital):
                with self.assertRaisesRegex(ValueError, "capital_before"):
                    calculate_position_budget(capital)

    def test_nonfinite_capital_is_rejected(self):
        for capital in (float("nan"), np.nan, np.float64("nan"), inf, -inf, np.inf, -np.inf):
            with self.subTest(capital=capital):
                with self.assertRaisesRegex(ValueError, "capital_before"):
                    calculate_position_budget(capital)

    def test_nonnumeric_and_complex_capital_is_rejected(self):
        for capital in (None, "10000", 10_000 + 0j, 1 + 2j):
            with self.subTest(capital=capital):
                with self.assertRaisesRegex(ValueError, "capital_before"):
                    calculate_position_budget(capital)

    def test_nonscalar_capital_is_rejected_without_extracting_elements(self):
        for capital in ([], [10_000], (), (10_000,), {}, {"capital": 10_000}, np.array(10_000), np.array([10_000]), pd.Series([10_000])):
            with self.subTest(capital_type=type(capital).__name__):
                with self.assertRaisesRegex(ValueError, "capital_before"):
                    calculate_position_budget(capital)

    def test_fraction_outside_open_closed_range_is_rejected(self):
        for fraction in (0, 0.0, -0.0, -1, -0.5, 1.2, np.int64(2)):
            with self.subTest(fraction=fraction):
                with self.assertRaisesRegex(ValueError, "position_fraction"):
                    calculate_position_budget(10_000, fraction)

    def test_python_and_numpy_boolean_fraction_is_rejected(self):
        for fraction in (True, False, np.bool_(True), np.bool_(False)):
            with self.subTest(fraction_type=type(fraction).__name__, fraction=fraction):
                with self.assertRaisesRegex(ValueError, "position_fraction"):
                    calculate_position_budget(10_000, fraction)

    def test_nonfinite_fraction_is_rejected(self):
        for fraction in (float("nan"), np.nan, np.float64("nan"), inf, -inf, np.inf, -np.inf):
            with self.subTest(fraction=fraction):
                with self.assertRaisesRegex(ValueError, "position_fraction"):
                    calculate_position_budget(10_000, fraction)

    def test_nonnumeric_and_complex_fraction_is_rejected(self):
        for fraction in (None, "0.5", 0.5 + 0j, 1 + 2j):
            with self.subTest(fraction=fraction):
                with self.assertRaisesRegex(ValueError, "position_fraction"):
                    calculate_position_budget(10_000, fraction)

    def test_nonscalar_fraction_is_rejected_without_extracting_elements(self):
        for fraction in ([], [0.5], (), (0.5,), {}, {"fraction": 0.5}, np.array(0.5), np.array([0.5]), pd.Series([0.5])):
            with self.subTest(fraction_type=type(fraction).__name__):
                with self.assertRaisesRegex(ValueError, "position_fraction"):
                    calculate_position_budget(10_000, fraction)

    def test_float_fraction_just_above_one_is_rejected(self):
        above_one = nextafter(1.0, inf)
        self.assertGreater(above_one, 1)
        with self.assertRaisesRegex(ValueError, "position_fraction"):
            calculate_position_budget(10_000, above_one)

    def test_exact_fraction_above_one_is_rejected_even_if_float_rounds_to_one(self):
        above_one = Fraction(2**54 + 1, 2**54)
        self.assertGreater(above_one, 1)
        self.assertEqual(float(above_one), 1.0)
        with self.assertRaisesRegex(ValueError, "position_fraction"):
            calculate_position_budget(10_000, above_one)

    def test_capital_conversion_overflow_is_rejected(self):
        capital = 10**400
        self.assertGreater(capital, 0)
        with self.assertRaises(OverflowError):
            float(capital)
        with self.assertRaisesRegex(ValueError, "capital_before"):
            calculate_position_budget(capital)

    def test_fraction_conversion_overflow_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "position_fraction"):
            calculate_position_budget(10_000, 10**400)

    def test_capital_conversion_underflow_is_rejected(self):
        capital = Fraction(1, 10**400)
        self.assertGreater(capital, 0)
        self.assertEqual(float(capital), 0.0)
        with self.assertRaisesRegex(ValueError, "capital_before"):
            calculate_position_budget(capital)

    def test_fraction_conversion_underflow_is_rejected(self):
        fraction = Fraction(1, 10**400)
        self.assertGreater(fraction, 0)
        self.assertEqual(float(fraction), 0.0)
        with self.assertRaisesRegex(ValueError, "position_fraction"):
            calculate_position_budget(10_000, fraction)

    def test_multiplication_underflow_to_zero_is_rejected(self):
        smallest = nextafter(0.0, 1.0)
        self.assertGreater(smallest, 0)
        self.assertEqual(smallest * 0.5, 0.0)
        with self.assertRaisesRegex(ValueError, "position budget"):
            calculate_position_budget(smallest, 0.5)

    def test_valid_budgets_are_positive_finite_and_no_larger_than_capital(self):
        for capital in (1e-200, 1.0, 10_500.0, float.fromhex("0x1.fffffffffffffp+1023")):
            for fraction in (0.25, 0.5, 1.0):
                with self.subTest(capital=capital, fraction=fraction):
                    budget = calculate_position_budget(capital, fraction)
                    self.assertTrue(isfinite(budget))
                    self.assertGreater(budget, 0)
                    self.assertLessEqual(budget, capital)
