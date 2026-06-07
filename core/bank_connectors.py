"""
Connecteurs bancaires Canada (BMO, TD, RBC, Banque Nationale).

Les grandes banques canadiennes n’offrent pas d’API transactionnelle grand public
similaire à l’open banking européen. Ce module s’appuie sur **Plaid**, agrégateur
qui prend en charge ces institutions au Canada (consentement utilisateur via Plaid Link).

Variables d’environnement :
  PLAID_CLIENT_ID, PLAID_SECRET — depuis le tableau de bord Plaid
  PLAID_ENV — sandbox | development | production (défaut : sandbox)

Les jetons d’accès sont stockés dans ~/.bank2wave/plaid.json (ou PLAID_CREDENTIALS_PATH).
"""

from __future__ import annotations

import json
import os
import threading
import webbrowser
from datetime import date, datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional
from uuid import uuid4

if TYPE_CHECKING:
    pass

CONNECTORS_META = {
    "bmo": {
        "label": "BMO Banque de Montréal (Canada — Plaid)",
        "search_queries": ["BMO Bank of Montreal", "BMO"],
    },
    "td": {
        "label": "TD Canada Trust (Plaid)",
        "search_queries": ["TD Canada Trust", "TD"],
    },
    "rbc": {
        "label": "RBC Banque Royale (Plaid)",
        "search_queries": ["RBC Royal Bank", "Royal Bank of Canada"],
    },
    "nbc": {
        "label": "Banque Nationale du Canada (Plaid)",
        "search_queries": ["National Bank of Canada", "Banque Nationale"],
    },
}


def list_connector_ids() -> list[str]:
    return sorted(CONNECTORS_META.keys())


def _credentials_path() -> Path:
    override = os.environ.get("PLAID_CREDENTIALS_PATH", "").strip()
    if override:
        return Path(override).expanduser()
    return Path.home() / ".bank2wave" / "plaid.json"


def _load_credentials() -> dict[str, Any]:
    path = _credentials_path()
    if not path.is_file():
        return {"version": 1, "items": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": 1, "items": {}}
    if not isinstance(data, dict):
        return {"version": 1, "items": {}}
    items = data.get("items")
    if not isinstance(items, dict):
        items = {}
    return {"version": 1, "items": items}


def _save_access_token(connector_id: str, access_token: str) -> Path:
    path = _credentials_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = _load_credentials()
    data["items"][connector_id] = {"access_token": access_token}
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path


def load_access_token(connector_id: str) -> str:
    data = _load_credentials()
    entry = data["items"].get(connector_id)
    if not isinstance(entry, dict):
        raise SystemExit(
            f"Aucun jeton Plaid pour le connecteur « {connector_id} ». "
            "Exécutez d’abord : bank2wave link --connector "
            f"{connector_id} --redirect-uri <URI>"
        )
    token = (entry.get("access_token") or "").strip()
    if not token:
        raise SystemExit(f"Jeton Plaid vide pour « {connector_id} ». Relancez link.")
    return token


def apply_plaid_app_credentials(
    *,
    client_id: str,
    secret: str,
    env: str = "sandbox",
) -> None:
    """Applique les identifiants Plaid pour le processus courant (ex. interface graphique)."""
    os.environ["PLAID_CLIENT_ID"] = client_id.strip()
    os.environ["PLAID_SECRET"] = secret.strip()
    os.environ["PLAID_ENV"] = (env or "sandbox").strip().lower() or "sandbox"


def _plaid_secrets() -> tuple[str, str]:
    cid = os.environ.get("PLAID_CLIENT_ID", "").strip()
    sec = os.environ.get("PLAID_SECRET", "").strip()
    if not cid or not sec:
        raise SystemExit(
            "Définissez PLAID_CLIENT_ID et PLAID_SECRET "
            "(https://dashboard.plaid.com/team/keys)."
        )
    return cid, sec


def _plaid_host():
    import plaid

    env = os.environ.get("PLAID_ENV", "sandbox").strip().lower()
    if env == "production":
        return plaid.Environment.Production
    if env in {"development", "dev"}:
        return plaid.Environment.Development
    return plaid.Environment.Sandbox


def _plaid_client():
    import plaid
    from plaid.api import plaid_api

    try:
        cid, sec = _plaid_secrets()
        configuration = plaid.Configuration(
            host=_plaid_host(),
            api_key={
                "clientId": cid,
                "secret": sec,
                "plaidVersion": "2020-09-14",
            },
        )
        api_client = plaid.ApiClient(configuration)
        return plaid_api.PlaidApi(api_client)
    except ImportError as e:
        raise SystemExit(
            "Le connecteur Plaid nécessite le paquet plaid-python. "
            "Installez : pip install -r requirements.txt"
        ) from e


def _resp_to_dict(resp: Any) -> dict[str, Any]:
    if hasattr(resp, "to_dict"):
        return resp.to_dict()
    if isinstance(resp, dict):
        return resp
    return dict(resp)


def _institution_row(inst: Any) -> tuple[str, str]:
    d = _resp_to_dict(inst) if not isinstance(inst, dict) else inst
    iid = d.get("institution_id") or ""
    name = d.get("name") or ""
    return str(iid), str(name)


def plaid_search_institutions(connector_id: str) -> list[dict[str, str]]:
    """Retourne [{institution_id, name}, ...] depuis Plaid (Canada)."""
    from plaid.model.country_code import CountryCode
    from plaid.model.institutions_search_request import InstitutionsSearchRequest
    from plaid.model.products import Products

    meta = CONNECTORS_META.get(connector_id)
    if not meta:
        raise SystemExit(f"Connecteur inconnu : {connector_id}")

    client = _plaid_client()
    seen: set[str] = set()
    out: list[dict[str, str]] = []
    for q in meta["search_queries"]:
        req = InstitutionsSearchRequest(
            query=q,
            country_codes=[CountryCode("CA")],
            products=[Products("transactions")],
        )
        resp = client.institutions_search(req)
        body = _resp_to_dict(resp)
        for inst in body.get("institutions") or []:
            iid, name = _institution_row(inst)
            if iid and iid not in seen:
                seen.add(iid)
                out.append({"institution_id": iid, "name": name})
        if out:
            break
    return out


def plaid_resolve_institution_id(
    connector_id: str, *, institution_id_override: Optional[str] = None
) -> str:
    if institution_id_override and institution_id_override.strip():
        return institution_id_override.strip()
    rows = plaid_search_institutions(connector_id)
    if not rows:
        raise SystemExit(
            f"Aucune institution Plaid trouvée pour le connecteur « {connector_id} ». "
            "Vérifiez PLAID_ENV et que les produits Transactions sont activés pour le Canada."
        )
    return rows[0]["institution_id"]


def _link_html_page(link_token: str) -> bytes:
    token_json = json.dumps(link_token)
    page = f"""<!DOCTYPE html>
<html lang="fr"><head><meta charset="utf-8"/><title>bank2wave — Plaid</title></head>
<body>
<p>Connexion à la banque…</p>
<button type="button" id="btn">Ouvrir Plaid Link</button>
<script src="https://cdn.plaid.com/link/v2/stable/link-initialize.js"></script>
<script>
const token = {token_json};
document.getElementById('btn').onclick = () => openLink();
function openLink() {{
  const handler = Plaid.create({{
    token: token,
    onSuccess: function(public_token, metadata) {{
      fetch('/exchange', {{
        method: 'POST',
        headers: {{ 'Content-Type': 'application/json' }},
        body: JSON.stringify({{ public_token: public_token }})
      }}).then(r => r.json()).then(j => {{
        document.body.innerHTML = '<p>' + (j.ok ? 'Connexion enregistrée.' : (j.error || 'Erreur')) + '</p>';
      }}).catch(e => {{
        document.body.innerHTML = '<p>' + e + '</p>';
      }});
    }},
    onExit: function(err, metadata) {{
      if (err != null) console.error(err);
    }},
  }});
  handler.open();
}}
openLink();
</script>
</body></html>"""
    return page.encode("utf-8")


def plaid_run_link_flow(
    connector_id: str,
    *,
    redirect_uri: str,
    bind: str = "127.0.0.1",
    port: int = 8765,
    institution_id_override: Optional[str] = None,
) -> Path:
    """Sert une page locale Plaid Link, échange le public_token et enregistre le jeton."""
    from plaid.model.country_code import CountryCode
    from plaid.model.item_public_token_exchange_request import ItemPublicTokenExchangeRequest
    from plaid.model.link_token_create_request import LinkTokenCreateRequest
    from plaid.model.link_token_create_request_user import LinkTokenCreateRequestUser
    from plaid.model.products import Products

    institution_id = plaid_resolve_institution_id(
        connector_id, institution_id_override=institution_id_override
    )
    client = _plaid_client()

    req = LinkTokenCreateRequest(
        client_name="bank2wave",
        language="fr",
        country_codes=[CountryCode("CA")],
        user=LinkTokenCreateRequestUser(client_user_id=str(uuid4())),
        products=[Products("transactions")],
        institution_id=institution_id,
        redirect_uri=redirect_uri.strip(),
    )
    link_resp = client.link_token_create(req)
    link_body = _resp_to_dict(link_resp)
    link_token = (link_body.get("link_token") or "").strip()
    if not link_token:
        raise SystemExit("Plaid n’a pas renvoyé de link_token.")

    done = threading.Event()
    result: dict[str, Any] = {"ok": False, "path": None, "error": None}

    class _Server(HTTPServer):
        link_token_value = link_token

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            return

        def do_GET(self) -> None:
            raw_path = self.path.split("?", 1)[0].rstrip("/") or "/"
            if raw_path not in ("/", "/oauth"):
                self.send_error(404)
                return
            body = _link_html_page(self.server.link_token_value)
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self) -> None:
            if self.path.rstrip("/") != "/exchange":
                self.send_error(404)
                return
            length = int(self.headers.get("Content-Length", "0") or 0)
            raw = self.rfile.read(length).decode("utf-8", errors="replace")
            try:
                payload = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                payload = {}
            public_token = (payload.get("public_token") or "").strip()
            if not public_token:
                err = json.dumps({"ok": False, "error": "public_token manquant"})
                self.send_response(400)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(err.encode("utf-8"))
                result["error"] = "public_token manquant"
                done.set()
                return
            try:
                ex = ItemPublicTokenExchangeRequest(public_token=public_token)
                ex_resp = client.item_public_token_exchange(ex)
                ex_body = _resp_to_dict(ex_resp)
                access_token = (ex_body.get("access_token") or "").strip()
                if not access_token:
                    raise ValueError("Pas d’access_token dans la réponse Plaid.")
                saved = _save_access_token(connector_id, access_token)
                result["path"] = str(saved)
                result["ok"] = True
                body = json.dumps({"ok": True}).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                done.set()
            except Exception as e:
                msg = str(e)
                result["error"] = msg
                body = json.dumps({"ok": False, "error": msg}).encode("utf-8")
                self.send_response(500)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                done.set()

    server = _Server((bind, port), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://{bind}:{port}/"
    print(f"Ouverture du navigateur : {url}")
    webbrowser.open(url)
    if not done.wait(timeout=600):
        server.shutdown()
        raise SystemExit(
            "Délai dépassé ou flux non terminé. Réessayez link ou vérifiez la console du navigateur."
        )
    server.shutdown()
    if not result.get("ok"):
        raise SystemExit(result.get("error") or "Échec de la liaison Plaid.")
    cred_path = Path(result.get("path") or _credentials_path())
    return cred_path


def plaid_list_account_ids(connector_id: str) -> list[str]:
    return [a["account_id"] for a in plaid_list_accounts(connector_id) if a.get("account_id")]


def plaid_list_accounts(connector_id: str) -> list[dict[str, Optional[str]]]:
    """Comptes liés : account_id, libellé affichable, masque."""
    from plaid.model.accounts_get_request import AccountsGetRequest

    access_token = load_access_token(connector_id)
    client = _plaid_client()
    resp = client.accounts_get(AccountsGetRequest(access_token=access_token))
    body = _resp_to_dict(resp)
    out: list[dict[str, Optional[str]]] = []
    for acct in body.get("accounts") or []:
        d = _resp_to_dict(acct) if not isinstance(acct, dict) else acct
        aid = d.get("account_id")
        if not aid:
            continue
        name = (d.get("name") or d.get("official_name") or "Compte") or "Compte"
        mask = d.get("mask")
        subtype = d.get("subtype")
        label = str(name).strip()
        if mask:
            label = f"{label} ···{mask}"
        if subtype is not None:
            label = f"{label} ({str(subtype)})"
        out.append(
            {
                "account_id": str(aid),
                "label": label,
                "name": str(name).strip(),
                "mask": str(mask) if mask else None,
            }
        )
    return out


def _txn_dict(t: Any) -> dict[str, Any]:
    return _resp_to_dict(t) if not isinstance(t, dict) else t


def _parse_txn_date(d: dict[str, Any]) -> Optional[date]:
    raw = d.get("authorized_date") or d.get("date")
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    s = str(raw).strip()[:10]
    try:
        return datetime.fromisoformat(s).date()
    except ValueError:
        return None


def transactions_from_plaid_added(added: list[Any]):
    """Convertit une liste de transactions Plaid (added) en Transaction Wave."""
    from bank2wave import Transaction

    out: list = []
    for t in added:
        d = _txn_dict(t)
        amt_plaid = d.get("amount")
        if amt_plaid is None:
            continue
        try:
            amt_plaid_f = float(amt_plaid)
        except (TypeError, ValueError):
            continue
        # Wave : positif = entrée, négatif = sortie ; Plaid : l’inverse pour les produits Transactions.
        amount_wave = -amt_plaid_f

        posted = _parse_txn_date(d)
        if posted is None:
            continue

        desc = (d.get("merchant_name") or d.get("name") or "").strip() or "Transaction"
        cur = d.get("iso_currency_code") or d.get("unofficial_currency_code")
        fit = d.get("transaction_id")
        out.append(
            Transaction(
                posted_date=posted,
                description=desc,
                amount=amount_wave,
                currency=str(cur) if cur else None,
                fit_id=str(fit) if fit is not None else None,
            )
        )
    return out


def _transaction_id_from_removed(r: Any) -> Optional[str]:
    d = _txn_dict(r)
    tid = d.get("transaction_id")
    return str(tid) if tid else None


def plaid_fetch_transactions_full_sync(
    access_token: str,
    *,
    account_id: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
):
    """transactions/sync paginé, fusion added/modified/removed, filtre optionnel."""
    from plaid.model.transactions_sync_request import TransactionsSyncRequest

    client = _plaid_client()
    by_id: dict[str, dict[str, Any]] = {}
    cursor: str = ""

    while True:
        req = TransactionsSyncRequest(access_token=access_token, cursor=cursor)
        resp = client.transactions_sync(req)
        body = _resp_to_dict(resp)

        for r in body.get("removed") or []:
            tid = _transaction_id_from_removed(r)
            if tid:
                by_id.pop(tid, None)

        for t in body.get("modified") or []:
            d = _txn_dict(t)
            tid = d.get("transaction_id")
            if tid:
                by_id[str(tid)] = d

        for t in body.get("added") or []:
            d = _txn_dict(t)
            tid = d.get("transaction_id")
            if tid:
                by_id[str(tid)] = d

        if not body.get("has_more"):
            break
        cursor = body.get("next_cursor") or ""
        if not cursor:
            break

    merged = list(by_id.values())
    if account_id:
        merged = [x for x in merged if str(x.get("account_id") or "") == account_id]

    df = (
        datetime.fromisoformat(date_from.strip()).date()
        if date_from and date_from.strip()
        else None
    )
    dt = (
        datetime.fromisoformat(date_to.strip()).date()
        if date_to and date_to.strip()
        else None
    )

    if df or dt:
        filtered: list[dict[str, Any]] = []
        for x in merged:
            pd = _parse_txn_date(x)
            if pd is None:
                continue
            if df and pd < df:
                continue
            if dt and pd > dt:
                continue
            filtered.append(x)
        merged = filtered

    return transactions_from_plaid_added(merged)


def plaid_fetch_transactions(
    connector_id: str,
    account_id: str,
    *,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
):
    access_token = load_access_token(connector_id)
    return plaid_fetch_transactions_full_sync(
        access_token,
        account_id=account_id.strip(),
        date_from=date_from,
        date_to=date_to,
    )
