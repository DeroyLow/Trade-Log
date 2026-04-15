$ErrorActionPreference = "Stop"

Set-Location -LiteralPath $PSScriptRoot

python refresh_data.py
git add "data/trades.json" "data/AI Trade Log.xlsx"
git commit -m "Update trade log data"
git push
