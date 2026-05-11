"""
Interface graphique bank2wave : connecteur banque (Plaid), identifiants, relevé du mois → CSV Wave.

Lancement depuis le dossier du projet :
  python bank2wave_gui.py

Les champs Secret sont masqués. Option « trousseau » : Windows Credential Manager (keyring).
"""

from __future__ import annotations

import calendar
import sys
import threading
import traceback
from datetime import date
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
import tkinter as tk
from typing import Callable, Optional

_KEYRING_SERVICE = "bank2wave-plaid"


def _keyring():
    try:
        import keyring

        return keyring
    except ImportError:
        return None


def _load_saved_plaid() -> tuple[str, str, str]:
    kr = _keyring()
    if not kr:
        return "", "", "sandbox"
    try:
        cid = kr.get_password(_KEYRING_SERVICE, "client_id") or ""
        sec = kr.get_password(_KEYRING_SERVICE, "secret") or ""
        env = kr.get_password(_KEYRING_SERVICE, "env") or "sandbox"
        return cid, sec, env
    except Exception:
        return "", "", "sandbox"


def _save_plaid_keyring(client_id: str, secret: str, env: str) -> bool:
    kr = _keyring()
    if not kr:
        return False
    try:
        kr.set_password(_KEYRING_SERVICE, "client_id", client_id.strip())
        kr.set_password(_KEYRING_SERVICE, "secret", secret.strip())
        kr.set_password(_KEYRING_SERVICE, "env", env.strip().lower() or "sandbox")
        return True
    except Exception:
        return False


def _clear_plaid_keyring() -> None:
    kr = _keyring()
    if not kr:
        return
    for k in ("client_id", "secret", "env"):
        try:
            kr.delete_password(_KEYRING_SERVICE, k)
        except Exception:
            pass


def _month_bounds(y: int, m: int) -> tuple[str, str]:
    last = calendar.monthrange(y, m)[1]
    return date(y, m, 1).isoformat(), date(y, m, last).isoformat()


def _month_choices() -> list[tuple[str, int, int]]:
    """Libellés « mai 2026 » + (année, mois)."""
    out: list[tuple[str, int, int]] = []
    today = date.today()
    y, m = today.year, today.month
    for _ in range(36):
        label = date(y, m, 1).strftime("%B %Y").capitalize()
        out.append((label, y, m))
        m -= 1
        if m < 1:
            m = 12
            y -= 1
    return out


class Bank2WaveApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("bank2wave — Plaid → Wave")
        self.minsize(520, 480)
        self._busy = False
        self._account_rows: list[tuple[str, str]] = []

        root = Path(__file__).resolve().parent
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))

        frm = ttk.Frame(self, padding=12)
        frm.grid(row=0, column=0, sticky="nsew")
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        frm.columnconfigure(1, weight=1)

        r = 0
        ttk.Label(frm, text="Banque (API)").grid(row=r, column=0, sticky="w", pady=2)
        self.var_bank = tk.StringVar(value="bmo")
        bank_cb = ttk.Combobox(
            frm,
            textvariable=self.var_bank,
            state="readonly",
            width=28,
            values=["bmo", "td", "rbc", "nbc"],
        )
        bank_cb.grid(row=r, column=1, sticky="ew", pady=2)
        r += 1

        ttk.Label(frm, text="Environnement Plaid").grid(row=r, column=0, sticky="w", pady=2)
        self.var_env = tk.StringVar(value="sandbox")
        ttk.Combobox(
            frm,
            textvariable=self.var_env,
            state="readonly",
            width=28,
            values=["sandbox", "development", "production"],
        ).grid(row=r, column=1, sticky="ew", pady=2)
        r += 1

        ttk.Label(frm, text="Client ID").grid(row=r, column=0, sticky="w", pady=2)
        self.var_client = tk.StringVar()
        ttk.Entry(frm, textvariable=self.var_client, width=40).grid(row=r, column=1, sticky="ew", pady=2)
        r += 1

        ttk.Label(frm, text="Secret").grid(row=r, column=0, sticky="w", pady=2)
        self.var_secret = tk.StringVar()
        ttk.Entry(frm, textvariable=self.var_secret, width=40, show="•").grid(
            row=r, column=1, sticky="ew", pady=2
        )
        r += 1

        kr = _keyring()
        self.var_save_keyring = tk.BooleanVar(value=False)
        if kr:
            ttk.Checkbutton(
                frm,
                text="Enregistrer Client ID / Secret / Env. dans le trousseau Windows",
                variable=self.var_save_keyring,
            ).grid(row=r, column=0, columnspan=2, sticky="w", pady=4)
        else:
            ttk.Label(
                frm,
                text="Installez « keyring » (pip install keyring) pour mémoriser les identifiants.",
                foreground="#666",
            ).grid(row=r, column=0, columnspan=2, sticky="w", pady=4)
        r += 1

        btn_kf = ttk.Frame(frm)
        btn_kf.grid(row=r, column=0, columnspan=2, sticky="w")
        if kr:
            ttk.Button(btn_kf, text="Charger depuis le trousseau", command=self._load_keyring).pack(
                side=tk.LEFT, padx=(0, 8)
            )
            ttk.Button(btn_kf, text="Effacer le trousseau", command=self._clear_keyring).pack(side=tk.LEFT)
        r += 1

        ttk.Separator(frm, orient=tk.HORIZONTAL).grid(row=r, column=0, columnspan=2, sticky="ew", pady=8)
        r += 1

        ttk.Label(frm, text="URI de redirection OAuth").grid(row=r, column=0, sticky="w", pady=2)
        self.var_redirect = tk.StringVar(value="http://127.0.0.1:8765/oauth")
        ttk.Entry(frm, textvariable=self.var_redirect, width=40).grid(row=r, column=1, sticky="ew", pady=2)
        r += 1

        ttk.Label(frm, text="Port serveur local").grid(row=r, column=0, sticky="w", pady=2)
        self.var_port = tk.StringVar(value="8765")
        ttk.Entry(frm, textvariable=self.var_port, width=10).grid(row=r, column=1, sticky="w", pady=2)
        r += 1

        self.btn_link = ttk.Button(frm, text="Connecter la banque (Plaid Link)", command=self._on_link)
        self.btn_link.grid(row=r, column=0, columnspan=2, sticky="ew", pady=4)
        r += 1

        ttk.Separator(frm, orient=tk.HORIZONTAL).grid(row=r, column=0, columnspan=2, sticky="ew", pady=8)
        r += 1

        ttk.Label(frm, text="Compte").grid(row=r, column=0, sticky="w", pady=2)
        self.var_account_label = tk.StringVar()
        self.cb_account = ttk.Combobox(
            frm, textvariable=self.var_account_label, state="readonly", width=36
        )
        self.cb_account.grid(row=r, column=1, sticky="ew", pady=2)
        r += 1

        self.btn_refresh = ttk.Button(frm, text="Actualiser les comptes", command=self._on_refresh_accounts)
        self.btn_refresh.grid(row=r, column=0, columnspan=2, sticky="ew", pady=2)
        r += 1

        ttk.Label(frm, text="Mois du relevé").grid(row=r, column=0, sticky="w", pady=2)
        self._month_data = _month_choices()
        self.var_month = tk.StringVar(value=self._month_data[0][0])
        ttk.Combobox(
            frm,
            textvariable=self.var_month,
            state="readonly",
            width=28,
            values=[x[0] for x in self._month_data],
        ).grid(row=r, column=1, sticky="ew", pady=2)
        r += 1

        ttk.Label(frm, text="Nom du compte Wave").grid(row=r, column=0, sticky="w", pady=2)
        self.var_wave_account = tk.StringVar(value="Bank")
        ttk.Entry(frm, textvariable=self.var_wave_account, width=28).grid(row=r, column=1, sticky="ew", pady=2)
        r += 1

        self.btn_export = ttk.Button(
            frm, text="Télécharger le mois → CSV Wave…", command=self._on_export_month
        )
        self.btn_export.grid(row=r, column=0, columnspan=2, sticky="ew", pady=6)
        r += 1

        ttk.Label(frm, text="Journal").grid(row=r, column=0, sticky="nw", pady=4)
        r += 1
        log_frame = ttk.Frame(frm)
        log_frame.grid(row=r, column=0, columnspan=2, sticky="nsew", pady=4)
        frm.rowconfigure(r, weight=1)
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        self.log = tk.Text(log_frame, height=10, wrap="word", state=tk.DISABLED)
        self.log.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(log_frame, command=self.log.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.log.configure(yscrollcommand=scroll.set)

        cid, sec, env = _load_saved_plaid()
        if cid:
            self.var_client.set(cid)
        if sec:
            self.var_secret.set(sec)
        if env:
            self.var_env.set(env)

        self._log("Prêt. Renseignez Plaid (dashboard.plaid.com), enregistrez la même URI de redirection, puis connectez la banque.")

    def _log(self, msg: str) -> None:
        self.log.configure(state=tk.NORMAL)
        self.log.insert(tk.END, msg + "\n")
        self.log.see(tk.END)
        self.log.configure(state=tk.DISABLED)

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        st = "disabled" if busy else "normal"
        for w in (self.btn_link, self.btn_refresh, self.btn_export):
            w.configure(state=st)

    def _apply_credentials(self) -> bool:
        cid = self.var_client.get().strip()
        sec = self.var_secret.get().strip()
        env = self.var_env.get().strip() or "sandbox"
        if not cid or not sec:
            messagebox.showwarning("Identifiants", "Client ID et Secret Plaid sont requis.")
            return False
        from bank_connectors import apply_plaid_app_credentials

        apply_plaid_app_credentials(client_id=cid, secret=sec, env=env)
        if self.var_save_keyring.get() and _keyring():
            if _save_plaid_keyring(cid, sec, env):
                self._log("Identifiants enregistrés dans le trousseau Windows.")
            else:
                self._log("Impossible d’écrire dans le trousseau.")
        return True

    def _load_keyring(self) -> None:
        cid, sec, env = _load_saved_plaid()
        if not cid and not sec:
            messagebox.showinfo("Trousseau", "Aucun identifiants enregistré.")
            return
        self.var_client.set(cid)
        self.var_secret.set(sec)
        self.var_env.set(env or "sandbox")
        self._log("Identifiants chargés depuis le trousseau.")

    def _clear_keyring(self) -> None:
        _clear_plaid_keyring()
        self._log("Trousseau effacé (clés bank2wave-plaid).")

    def _run_thread(self, target: Callable[[], None]) -> None:
        if self._busy:
            return

        def wrap() -> None:
            try:
                target()
            except Exception:
                err = traceback.format_exc()
                self.after(0, lambda: self._thread_error(err))

        self._set_busy(True)
        threading.Thread(target=wrap, daemon=True).start()

    def _thread_done(self, fn: Callable[[], None]) -> None:
        self._set_busy(False)
        try:
            fn()
        except Exception:
            traceback.print_exc()

    def _finish_link_saved(self, saved_path: str) -> None:
        self._set_busy(False)
        self._log(f"Connexion enregistrée : {saved_path}")
        messagebox.showinfo("Plaid", "Banque connectée. Actualisez les comptes.")

    def _thread_error(self, err: str) -> None:
        self._set_busy(False)
        self._log(err)
        messagebox.showerror("Erreur", err[:800])

    def _on_link(self) -> None:
        if not self._apply_credentials():
            return

        def work() -> None:
            from bank_connectors import plaid_run_link_flow

            port_s = self.var_port.get().strip() or "8765"
            try:
                port = int(port_s)
            except ValueError:
                self.after(0, lambda: self._thread_error("Port invalide."))
                return
            redirect = self.var_redirect.get().strip()
            bank = self.var_bank.get().strip()
            try:
                path = plaid_run_link_flow(
                    bank,
                    redirect_uri=redirect,
                    bind="127.0.0.1",
                    port=port,
                )
            except SystemExit as e:
                msg = e.args[0] if e.args else "Échec Plaid Link"
                self.after(0, lambda m=str(msg): self._thread_error(m))
                return
            except Exception as e:
                self.after(0, lambda: self._thread_error(str(e)))
                return

            self.after(0, lambda p=str(path): self._finish_link_saved(p))

        self._run_thread(work)

    def _on_refresh_accounts(self) -> None:
        if not self._apply_credentials():
            return

        def work() -> None:
            from bank_connectors import plaid_list_accounts

            bank = self.var_bank.get().strip()
            try:
                rows = plaid_list_accounts(bank)
            except SystemExit as e:
                msg = e.args[0] if e.args else "Erreur"
                self.after(0, lambda m=str(msg): self._thread_error(m))
                return
            except Exception as e:
                self.after(0, lambda: self._thread_error(str(e)))
                return

            pairs: list[tuple[str, str]] = [(r["label"], r["account_id"]) for r in rows]

            def apply() -> None:
                self._account_rows = pairs
                self.cb_account["values"] = [p[0] for p in pairs]
                if pairs:
                    self.var_account_label.set(pairs[0][0])
                    self._log(f"{len(pairs)} compte(s) chargé(s).")
                else:
                    self.var_account_label.set("")
                    self._log("Aucun compte — connectez la banque d’abord.")

            self.after(0, lambda: self._thread_done(apply))

        self._run_thread(work)

    def _selected_account_id(self) -> Optional[str]:
        label = self.var_account_label.get().strip()
        for lab, aid in self._account_rows:
            if lab == label:
                return aid
        return None

    def _resolve_month(self) -> Optional[tuple[int, int]]:
        sel = self.var_month.get().strip()
        for label, y, m in self._month_data:
            if label == sel:
                return y, m
        return None

    def _on_export_month(self) -> None:
        if not self._apply_credentials():
            return
        aid = self._selected_account_id()
        if not aid:
            messagebox.showwarning("Compte", "Choisissez un compte ou actualisez la liste.")
            return
        ym = self._resolve_month()
        if not ym:
            messagebox.showwarning("Mois", "Mois invalide.")
            return
        y, m = ym
        d_from, d_to = _month_bounds(y, m)
        bank = self.var_bank.get().strip()
        wave_name = self.var_wave_account.get().strip() or "Bank"

        default = f"wave_import_{y}-{m:02d}_{bank}.csv"
        path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            initialfile=default,
            filetypes=[("CSV Wave", "*.csv"), ("Tous les fichiers", "*.*")],
        )
        if not path:
            return

        out_path = Path(path)

        def work() -> None:
            from bank_connectors import plaid_fetch_transactions
            import bank2wave

            try:
                txns = plaid_fetch_transactions(
                    bank,
                    aid,
                    date_from=d_from,
                    date_to=d_to,
                )
            except SystemExit as e:
                msg = e.args[0] if e.args else "Erreur"
                self.after(0, lambda m=str(msg): self._thread_error(m))
                return
            except Exception as e:
                self.after(0, lambda: self._thread_error(str(e)))
                return

            rows = bank2wave.to_wave_rows(txns, account_name=wave_name)
            try:
                bank2wave.write_csv(rows, out_path)
            except Exception as e:
                self.after(0, lambda: self._thread_error(str(e)))
                return

            n = len(rows)

            def done() -> None:
                self._log(f"OK {n} opérations → {out_path}")
                messagebox.showinfo("Export", f"{n} transactions enregistrées.")

            self.after(0, lambda: self._thread_done(done))

        self._run_thread(work)


def main() -> None:
    app = Bank2WaveApp()
    app.mainloop()


if __name__ == "__main__":
    main()
