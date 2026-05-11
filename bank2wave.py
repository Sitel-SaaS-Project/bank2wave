from __future__ import annotations

import argparse
import csv
import hashlib
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Iterable, Optional

from dateutil.parser import parse as parse_dt
from ofxparse import OfxParser

from bank_connectors import CONNECTORS_META, list_connector_ids

@dataclass(frozen=True)
class Transaction:
    posted_date: date
    description: str
    amount: float  # positive = money in, negative = money out
    currency: Optional[str] = None
    fit_id: Optional[str] = None

    @property
    def stable_id(self) -> str:
        raw = f"{self.posted_date.isoformat()}|{self.description}|{self.amount:.2f}|{self.fit_id or ''}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _parse_amount(value: str) -> float:
    s = (value or "").strip()
    if not s:
        raise ValueError("empty amount")
    # handle common formats: "1,234.56" or "1 234,56" or "-123,45"
    s = s.replace(" ", "")
    if s.count(",") == 1 and s.count(".") == 0:
        s = s.replace(",", ".")
    elif s.count(",") >= 1 and s.count(".") == 1:
        # assume commas are thousands separators
        s = s.replace(",", "")
    return float(s)


def _parse_date(value: str) -> date:
    dt = parse_dt(value, dayfirst=True, fuzzy=True)
    return dt.date()


def read_ofx(path: Path) -> list[Transaction]:
    with path.open("rb") as f:
        ofx = OfxParser.parse(f)
    txns: list[Transaction] = []
    for acct in ofx.accounts:
        for t in acct.statement.transactions:
            txns.append(
                Transaction(
                    posted_date=t.date.date() if isinstance(t.date, datetime) else t.date,
                    description=(t.memo or t.payee or "").strip() or "Transaction",
                    amount=float(t.amount),
                    currency=getattr(acct.statement, "currency", None),
                    fit_id=getattr(t, "id", None),
                )
            )
    return txns


def read_csv_generic(path: Path) -> list[Transaction]:
    """
    Best-effort generic CSV reader.
    Expected columns (any of these names, case-insensitive):
      - date: date, posted_date, transaction_date
      - description: description, memo, payee, name, details
      - amount: amount, montant
      - debit/credit: debit + credit columns (optional)
    """
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise ValueError("CSV has no headers")
        cols = {c.strip().lower(): c for c in reader.fieldnames if c}

        def pick(*names: str) -> Optional[str]:
            for n in names:
                if n in cols:
                    return cols[n]
            return None

        date_col = pick("date", "posted_date", "transaction_date")
        desc_col = pick("description", "memo", "payee", "name", "details", "libellé", "libelle")
        amount_col = pick("amount", "montant")
        debit_col = pick("debit", "débit", "debit_amount")
        credit_col = pick("credit", "crédit", "credit_amount")

        if not date_col or not desc_col or (not amount_col and not (debit_col and credit_col)):
            raise ValueError(
                "CSV columns not recognized. Need at least date+description+amount (or debit+credit)."
            )

        txns: list[Transaction] = []
        for row in reader:
            d = _parse_date(row[date_col])
            desc = (row.get(desc_col) or "").strip() or "Transaction"
            if amount_col:
                amt = _parse_amount(row.get(amount_col, ""))
            else:
                debit = _parse_amount(row.get(debit_col, "") or "0")
                credit = _parse_amount(row.get(credit_col, "") or "0")
                amt = credit - debit
            txns.append(Transaction(posted_date=d, description=desc, amount=amt))
    return txns


def detect_and_read(path: Path) -> list[Transaction]:
    ext = path.suffix.lower()
    if ext in {".ofx", ".qfx"}:
        return read_ofx(path)
    if ext == ".csv":
        return read_csv_generic(path)
    raise ValueError(f"Unsupported input file type: {ext} (supported: .csv, .ofx, .qfx)")


def to_wave_rows(txns: Iterable[Transaction], account_name: str) -> list[dict[str, str]]:
    """
    Wave-friendly CSV (generic):
      Date, Description, Amount, Account
    Amount is signed (positive=in, negative=out).
    """
    rows: list[dict[str, str]] = []
    for t in txns:
        rows.append(
            {
                "Date": t.posted_date.isoformat(),
                "Description": t.description,
                "Amount": f"{t.amount:.2f}",
                "Account": account_name,
                "TransactionID": t.stable_id,
            }
        )
    return rows


def write_csv(rows: list[dict[str, str]], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys()) if rows else [
        "Date",
        "Description",
        "Amount",
        "Account",
        "TransactionID",
    ]
    with out_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow(r)

def _cmd_convert(args: argparse.Namespace) -> int:
    input_file = Path(args.input_file)
    out_file = Path(args.out)
    account_name = args.account

    txns = detect_and_read(input_file)
    rows = to_wave_rows(txns, account_name=account_name)
    write_csv(rows, out_file)
    print(f"OK {len(rows)} transactions -> {out_file}")
    return 0


def _require_connector(name: str) -> None:
    valid = list_connector_ids()
    if name not in valid:
        raise SystemExit(f"Connecteur inconnu: {name}. Disponibles: {', '.join(valid)}")


def _cmd_list_banks(args: argparse.Namespace) -> int:
    _require_connector(args.connector)
    from bank_connectors import plaid_search_institutions

    rows = plaid_search_institutions(args.connector)
    for row in rows:
        print(f"{row['institution_id']}\t{row['name']}")
    print(f"OK {len(rows)} résultat(s) Plaid ({args.connector})")
    return 0


def _cmd_link(args: argparse.Namespace) -> int:
    _require_connector(args.connector)
    from bank_connectors import plaid_run_link_flow

    override = (args.institution_id or "").strip() or None
    path = plaid_run_link_flow(
        args.connector,
        redirect_uri=args.redirect_uri.strip(),
        bind=args.bind.strip(),
        port=args.port,
        institution_id_override=override,
    )
    print(f"Identifiants enregistrés dans : {path}")
    return 0


def _cmd_list_accounts(args: argparse.Namespace) -> int:
    _require_connector(args.connector)
    from bank_connectors import plaid_list_account_ids

    for aid in plaid_list_account_ids(args.connector):
        print(aid)
    return 0


def _cmd_fetch_api(args: argparse.Namespace) -> int:
    _require_connector(args.connector)
    from bank_connectors import plaid_fetch_transactions

    txns = plaid_fetch_transactions(
        args.connector,
        args.account_id.strip(),
        date_from=args.date_from,
        date_to=args.date_to,
    )
    out_file = Path(args.out)
    rows = to_wave_rows(txns, account_name=args.account)
    write_csv(rows, out_file)
    print(f"OK {len(rows)} transactions -> {out_file}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    connector_help = "; ".join(
        f"{k}: {v['label']}" for k, v in sorted(CONNECTORS_META.items())
    )
    p = argparse.ArgumentParser(
        prog="bank2wave",
        description="Banque vers CSV Wave : fichiers (CSV/OFX/QFX) ou API (connecteurs).",
        epilog=(
            "API Plaid (Canada, BMO / TD / RBC / Banque Nationale) : PLAID_CLIENT_ID, PLAID_SECRET, "
            "optionnel PLAID_ENV=sandbox|development|production "
            "(https://dashboard.plaid.com/). "
            "Enregistrez l’URI de redirection OAuth dans le tableau de bord Plaid "
            "(ex. http://127.0.0.1:8765/oauth). Flux : list-banks, link, list-accounts, fetch-api.\n\n"
            f"Connecteurs : {connector_help}"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = p.add_subparsers(dest="command", required=True)

    c = sub.add_parser("convert", help="Convertir un fichier banque vers CSV Wave")
    c.add_argument("input_file", help="Export (.csv/.ofx/.qfx)")
    c.add_argument("--out", "-o", default="wave_import.csv", help="CSV Wave")
    c.add_argument("--account", default="Bank", help="Nom du compte Wave")
    c.set_defaults(func=_cmd_convert)

    lb = sub.add_parser(
        "list-banks",
        help="Institutions Plaid correspondant au connecteur (Canada)",
    )
    lb.add_argument(
        "--connector",
        choices=list_connector_ids(),
        default="bmo",
        help="Banque cible (BMO, TD, RBC ou Banque Nationale)",
    )
    lb.set_defaults(func=_cmd_list_banks)

    lk = sub.add_parser(
        "link",
        help="Plaid Link : navigateur local, échange du jeton et enregistrement",
    )
    lk.add_argument(
        "--connector",
        choices=list_connector_ids(),
        default="bmo",
        help="Banque cible",
    )
    lk.add_argument(
        "--redirect-uri",
        required=True,
        help="URI OAuth enregistrée chez Plaid (sans paramètres de requête)",
    )
    lk.add_argument(
        "--institution-id",
        default="",
        help="Forcer un institution_id Plaid (sinon résolution automatique)",
    )
    lk.add_argument(
        "--bind",
        default="127.0.0.1",
        help="Adresse du mini-serveur Plaid Link",
    )
    lk.add_argument(
        "--port",
        type=int,
        default=8765,
        help="Port du mini-serveur",
    )
    lk.set_defaults(func=_cmd_link)

    la = sub.add_parser(
        "list-accounts",
        help="Lister les account_id Plaid après link",
    )
    la.add_argument(
        "--connector",
        choices=list_connector_ids(),
        default="bmo",
        help="Banque utilisée lors du link",
    )
    la.set_defaults(func=_cmd_list_accounts)

    fa = sub.add_parser(
        "fetch-api",
        help="Télécharger les transactions via API et écrire le CSV Wave",
    )
    fa.add_argument(
        "--connector",
        choices=list_connector_ids(),
        default="bmo",
        help="Banque utilisée lors du link",
    )
    fa.add_argument("--account-id", required=True, help="account_id Plaid du compte")
    fa.add_argument("--from", dest="date_from", help="YYYY-MM-DD (optionnel)")
    fa.add_argument("--to", dest="date_to", help="YYYY-MM-DD (optionnel)")
    fa.add_argument("--out", "-o", default="wave_import.csv", help="CSV Wave")
    fa.add_argument("--account", default="Bank", help="Nom du compte Wave")
    fa.set_defaults(func=_cmd_fetch_api)

    return p


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
