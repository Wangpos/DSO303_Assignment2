"""Unit tests for the value conversion in lib/db.py (no database needed)."""
import datetime
import decimal
import os
import sys
import types
import unittest
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.modules.setdefault("boto3", types.ModuleType("boto3"))  # not needed for these tests

from lib import db  # noqa: E402


class CellConversion(unittest.TestCase):
    def test_uuid_becomes_string(self):
        u = uuid.uuid4()
        self.assertEqual(db._cell(u), str(u))

    def test_decimal_becomes_float(self):
        self.assertEqual(db._cell(decimal.Decimal("2.5")), 2.5)

    def test_datetime_is_returned_as_utc_iso(self):
        bt = datetime.timezone(datetime.timedelta(hours=6))
        value = datetime.datetime(2026, 11, 23, 12, 0, tzinfo=bt)
        self.assertEqual(db._cell(value), "2026-11-23T06:00:00+00:00")

    def test_jsonb_round_trip(self):
        cell = db._cell(["A", "B"])
        self.assertIsInstance(cell, str)
        self.assertEqual(db.jsonb(cell), ["A", "B"])

    def test_plain_values_unchanged(self):
        for v in (None, 1, 1.5, True, "text"):
            self.assertEqual(db._cell(v), v)


class ParamConversion(unittest.TestCase):
    def test_dicts_and_lists_are_sent_as_json(self):
        self.assertEqual(db._param({"a": 1}), '{"a": 1}')
        self.assertEqual(db._param([1, 2]), "[1, 2]")

    def test_scalars_unchanged(self):
        for v in (None, 3, 2.0, "x"):
            self.assertEqual(db._param(v), v)


if __name__ == "__main__":
    unittest.main()
