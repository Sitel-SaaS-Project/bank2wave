# bank2wave

Outil Python pour convertir un export de transactions bancaires (CSV/OFX/QFX) en CSV importable dans Wave.

## Installation

```bash
cd "C:\Users\Maro\OneDrive\Desktop\Marouane file\Projet wave\bank2wave"
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

## Utilisation

### Convertir un fichier

```bash
python .\bank2wave.py convert .\export.ofx --out .\wave_import.csv --account "Compte courant"
```

Formats supportés:
- `.ofx` / `.qfx`
- `.csv` (détection best-effort des colonnes)

## Import dans Wave

Dans Wave, utilise l’écran d’import de transactions et sélectionne le fichier `wave_import.csv`.

Si ton Wave attend d’autres noms de colonnes (Wave varie selon pays/produit), envoie-moi:
- un CSV “template” d’import Wave (ou une capture des en-têtes demandés),
et j’adapte le mapping exactement.

