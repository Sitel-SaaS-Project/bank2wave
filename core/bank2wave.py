# bank2wave core sync module v2
from datetime import datetime
from typing import List, Dict, Any

def to_wave_rows(transactions: List[Dict[Any, Any]], account_name: str = "Bank") -> List[Dict]:
    rows = []
    for txn in transactions:
        amount = txn.get("amount", 0)
        date = txn.get("date", datetime.today().strftime("%Y-%m-%d"))
        name = txn.get("name", "Unknown")
        category = txn.get("category", ["Uncategorized"])
        if isinstance(category, list):
            category = category[0] if category else "Uncategorized"
        rows.append({
            "Transaction Date": date,
            "Description": name,
            "Amount": -amount,
            "Account Name": account_name,
            "Category": category,
        })
    return rows
