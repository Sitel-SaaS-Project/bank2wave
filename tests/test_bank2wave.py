"""Tests unitaires bank2wave (sans appels réseau)."""

from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path

import bank2wave
from bank_connectors import list_connector_ids, transactions_from_plaid_added


class TestParseAmount(unittest.TestCase):
    def test_decimal_comma(self) -> None:
        self.assertEqual(bank2wave._parse_amount("-12,50"), -12.5)

    def test_thousands_us(self) -> None:
        self.assertEqual(bank2wave._parse_amount("1,234.56"), 1234.56)


class TestReadCsvGeneric(unittest.TestCase):
    def test_amount_column(self) -> None:
        content = "Date,Description,Montant\n02/05/2026,Cafe,-5.50\n"
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, encoding="utf-8", newline=""
        ) as f:
            f.write(content)
            path = Path(f.name)
        try:
            txns = bank2wave.read_csv_generic(path)
            self.assertEqual(len(txns), 1)
            self.assertEqual(txns[0].posted_date, date(2026, 5, 2))
            self.assertEqual(txns[0].description, "Cafe")
            self.assertEqual(txns[0].amount, -5.5)
        finally:
            path.unlink(missing_ok=True)

    def test_debit_credit(self) -> None:
        content = "date,description,debit,credit\n02/05/2026,X,10,0\n"
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, encoding="utf-8", newline=""
        ) as f:
            f.write(content)
            path = Path(f.name)
        try:
            txns = bank2wave.read_csv_generic(path)
            self.assertEqual(txns[0].amount, -10.0)
        finally:
            path.unlink(missing_ok=True)


class TestDetectAndRead(unittest.TestCase):
    def test_unsupported_extension(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            path = Path(f.name)
        try:
            with self.assertRaises(ValueError):
                bank2wave.detect_and_read(path)
        finally:
            path.unlink(missing_ok=True)


class TestToWaveRows(unittest.TestCase):
    def test_row_shape(self) -> None:
        t = bank2wave.Transaction(
            posted_date=date(2026, 1, 15),
            description="Test",
            amount=100.0,
            currency="EUR",
        )
        rows = bank2wave.to_wave_rows([t], account_name="CC")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["Account"], "CC")
        self.assertEqual(rows[0]["Amount"], "100.00")
        self.assertIn("TransactionID", rows[0])


class TestPlaidPayload(unittest.TestCase):
    def test_transaction_amount_sign_for_wave(self) -> None:
        # Plaid : positif = sortie de compte ; Wave : positif = entrée.
        row = {
            "date": "2026-04-01",
            "amount": 42.5,
            "name": "Magasin",
            "transaction_id": "t-1",
            "iso_currency_code": "CAD",
        }
        txns = transactions_from_plaid_added([row])
        self.assertEqual(len(txns), 1)
        self.assertEqual(txns[0].posted_date, date(2026, 4, 1))
        self.assertEqual(txns[0].amount, -42.5)
        self.assertEqual(txns[0].currency, "CAD")
        self.assertEqual(txns[0].description, "Magasin")
        self.assertEqual(txns[0].fit_id, "t-1")


class TestConnectorsMeta(unittest.TestCase):
    def test_canadian_banks_registered(self) -> None:
        ids = list_connector_ids()
        for x in ("bmo", "td", "rbc", "nbc"):
            self.assertIn(x, ids)


if __name__ == "__main__":
    unittest.main()
