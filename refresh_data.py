import json
from pathlib import Path

import app


def main() -> None:
    payload = app.parse_xlsx(app.WORKBOOK_PATH)
    output = Path("data") / "trades.json"
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")
    print(f"Updated {output}")


if __name__ == "__main__":
    main()
