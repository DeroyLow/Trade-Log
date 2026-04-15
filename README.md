# Trading Results Dashboard

This project is a lightweight local web app for reviewing closed equity trades from `AI Trade Log.xlsx`.

## What it shows

- Year-to-date summary cards
- Interactive monthly returns chart
- Filterable table of all closed trades
- Automatic reload when the workbook changes

## Run it

```powershell
python app.py
```

Then open [http://127.0.0.1:8000](http://127.0.0.1:8000) in your browser.

## Workbook path

By default the app reads:

```text
C:\Users\User\OneDrive\Documents\New project\data\AI Trade Log.xlsx
```

If your workbook lives somewhere else, set `TRADE_LOG_PATH` before starting the server:

```powershell
$env:TRADE_LOG_PATH='C:\path\to\your\AI Trade Log.xlsx'
python app.py
```

## Hosted version

The project also includes `data/trades.json` so it can be deployed without needing access to your local Excel file.

If you update the workbook and want the hosted app to reflect the latest trades, run:

```powershell
python refresh_data.py
```

Then redeploy or push the updated `data/trades.json`.
