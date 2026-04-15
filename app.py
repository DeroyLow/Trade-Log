import json
import os
import re
import zipfile
from dataclasses import dataclass
from datetime import datetime, timedelta
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse
import xml.etree.ElementTree as ET


WORKSPACE = Path(__file__).resolve().parent
STATIC_DIR = WORKSPACE / "static"
DATA_FILE = WORKSPACE / "data" / "trades.json"
DEFAULT_WORKBOOK = WORKSPACE / "data" / "AI Trade Log.xlsx"
WORKBOOK_PATH = Path(os.environ.get("TRADE_LOG_PATH", DEFAULT_WORKBOOK))

NS = {
    "main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "rel": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "pkgrel": "http://schemas.openxmlformats.org/package/2006/relationships",
}

HEADER_MAP = {
    "ENTRY \nDATE": "entry_date",
    "EXIT\nDATE": "exit_date",
    "DAY": "day",
    "Ticker": "ticker",
    "Long/Short": "side",
    "Set up": "setup",
    "Bought #": "shares",
    "Stop Loss": "stop_loss",
    "Average\nEntry Price": "entry_price",
    "Average\nExit Price": "exit_price",
    "Initial Account \nCapital Risk": "capital_risk",
    "Net $\nGain/Loss (After Fees)": "net_pnl",
    "Return %\nTo Portfolio": "portfolio_return",
    "Gross\nExposure": "gross_exposure",
    "Return %\nOf Stock": "stock_return",
    "Total\nCommissions": "commissions",
    "Gross $\nGain/Loss": "gross_pnl",
    "Technicals": "technicals",
    "Fundamentals": "fundamentals",
    "Feedback/Note to Self": "notes",
    "Slippage": "slippage",
    "Average Holding Period (Days)": "holding_days",
}

NUMERIC_FIELDS = {
    "shares",
    "stop_loss",
    "entry_price",
    "exit_price",
    "capital_risk",
    "net_pnl",
    "portfolio_return",
    "gross_exposure",
    "stock_return",
    "commissions",
    "gross_pnl",
    "slippage",
    "holding_days",
}


def column_to_index(column_name: str) -> int:
    total = 0
    for char in column_name:
        if char.isalpha():
            total = total * 26 + (ord(char.upper()) - 64)
    return total - 1


def excel_date_to_iso(value: str) -> str:
    if value in ("", None):
        return ""
    try:
        serial = float(value)
    except (TypeError, ValueError):
        return str(value)
    base = datetime(1899, 12, 30)
    return (base + timedelta(days=serial)).date().isoformat()


def parse_number(value: str) -> float | None:
    if value in ("", None, "#REF!"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def median(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


@dataclass
class WorkbookCache:
    mtime: float | None = None
    payload: dict[str, Any] | None = None


CACHE = WorkbookCache()


def parse_xlsx(path: Path) -> dict[str, Any]:
    with zipfile.ZipFile(path) as archive:
        shared_strings = load_shared_strings(archive)
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        rel_map = {
            rel.attrib["Id"]: rel.attrib["Target"]
            for rel in relationships.findall("pkgrel:Relationship", NS)
        }

        sheet_target = None
        for sheet in workbook.findall("main:sheets/main:sheet", NS):
            if sheet.attrib["name"] == "Closed Positions (US)":
                rel_id = sheet.attrib[
                    "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
                ]
                sheet_target = "xl/" + rel_map[rel_id]
                break

        if not sheet_target:
            raise FileNotFoundError("Closed Positions (US) sheet not found in workbook.")

        sheet_root = ET.fromstring(archive.read(sheet_target))
        rows = read_sheet_rows(sheet_root, shared_strings)

    return build_payload(rows, path)


def load_shared_strings(archive: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []

    root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    values: list[str] = []
    for item in root.findall("main:si", NS):
        values.append("".join(text.text or "" for text in item.iterfind(".//main:t", NS)))
    return values


def read_sheet_rows(root: ET.Element, shared_strings: list[str]) -> list[list[str]]:
    rows: list[list[str]] = []
    for row in root.findall("main:sheetData/main:row", NS):
        mapped: dict[int, str] = {}
        max_index = -1

        for cell in row.findall("main:c", NS):
            ref = cell.attrib.get("r", "")
            match = re.match(r"([A-Z]+)", ref)
            index = column_to_index(match.group(1)) if match else max_index + 1
            max_index = max(max_index, index)

            cell_type = cell.attrib.get("t")
            value_node = cell.find("main:v", NS)

            if cell_type == "s" and value_node is not None and value_node.text is not None:
                text = shared_strings[int(value_node.text)]
            elif cell_type == "inlineStr":
                inline = cell.find("main:is/main:t", NS)
                text = inline.text if inline is not None else ""
            elif value_node is not None:
                text = value_node.text or ""
            else:
                text = ""

            mapped[index] = text

        row_values = [mapped.get(i, "") for i in range(max_index + 1)] if max_index >= 0 else []
        rows.append(row_values)

    return rows


def build_payload(rows: list[list[str]], workbook_path: Path) -> dict[str, Any]:
    header_row = next(
        (row for row in rows if row and row[:4] == ["ENTRY \nDATE", "EXIT\nDATE", "DAY", "Ticker"]),
        None,
    )
    if header_row is None:
        raise ValueError("Trade header row not found.")

    header_index = rows.index(header_row)
    trades: list[dict[str, Any]] = []

    for row in rows[header_index + 1 :]:
        if len(row) < 12:
            continue

        record: dict[str, Any] = {}
        for idx, original_key in enumerate(header_row):
            key = HEADER_MAP.get(original_key)
            if not key:
                continue
            record[key] = row[idx] if idx < len(row) else ""

        if not record.get("ticker"):
            continue

        record["entry_date"] = excel_date_to_iso(record.get("entry_date"))
        record["exit_date"] = excel_date_to_iso(record.get("exit_date"))

        for field in NUMERIC_FIELDS:
            record[field] = parse_number(record.get(field, ""))

        record["month"] = (record.get("exit_date") or record.get("entry_date") or "")[:7]
        trades.append(record)

    trades.sort(key=lambda item: (item.get("exit_date") or "", item.get("ticker") or ""))

    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "workbook_path": str(workbook_path),
        "summary": compute_summary(trades),
        "monthly": compute_monthly(trades),
        "trades": trades,
        "filters": {
            "months": sorted({trade["month"] for trade in trades if trade["month"]}),
            "setups": sorted({trade["setup"] for trade in trades if trade["setup"]}),
            "sides": sorted({trade["side"] for trade in trades if trade["side"]}),
            "tickers": sorted({trade["ticker"] for trade in trades if trade["ticker"]}),
        },
    }
    return payload


def compute_summary(trades: list[dict[str, Any]]) -> dict[str, Any]:
    net_values = [trade["net_pnl"] for trade in trades if trade["net_pnl"] is not None]
    return_values = [
        trade["portfolio_return"] for trade in trades if trade["portfolio_return"] is not None
    ]
    wins = [value for value in net_values if value > 0]
    losses = [value for value in net_values if value < 0]
    holding_days = [
        trade["holding_days"] for trade in trades if trade.get("holding_days") is not None
    ]

    return {
        "trade_count": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "breakeven": len([value for value in net_values if value == 0]),
        "win_rate": (len(wins) / len(net_values)) if net_values else 0.0,
        "net_pnl": sum(net_values),
        "portfolio_return": sum(return_values),
        "average_win": (sum(wins) / len(wins)) if wins else 0.0,
        "average_loss": (sum(losses) / len(losses)) if losses else 0.0,
        "profit_factor": ((sum(wins) / len(wins)) / abs(sum(losses) / len(losses)))
        if wins and losses
        else 0.0,
        "best_trade": max(net_values) if net_values else 0.0,
        "worst_trade": min(net_values) if net_values else 0.0,
        "median_holding_days": median(holding_days),
    }


def compute_monthly(trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    monthly: dict[str, dict[str, Any]] = {}

    for trade in trades:
        month = trade["month"]
        if not month:
            continue

        bucket = monthly.setdefault(
            month,
            {
                "month": month,
                "trades": 0,
                "net_pnl": 0.0,
                "portfolio_return": 0.0,
                "wins": 0,
                "losses": 0,
            },
        )

        bucket["trades"] += 1
        bucket["net_pnl"] += trade["net_pnl"] or 0.0
        bucket["portfolio_return"] += trade["portfolio_return"] or 0.0
        if (trade["net_pnl"] or 0.0) > 0:
            bucket["wins"] += 1
        elif (trade["net_pnl"] or 0.0) < 0:
            bucket["losses"] += 1

    return [monthly[key] for key in sorted(monthly)]


def get_payload() -> dict[str, Any]:
    mtime = WORKBOOK_PATH.stat().st_mtime if WORKBOOK_PATH.exists() else None
    data_mtime = DATA_FILE.stat().st_mtime if DATA_FILE.exists() else None

    if WORKBOOK_PATH.exists():
        if CACHE.payload is None or CACHE.mtime != mtime:
            CACHE.payload = parse_xlsx(WORKBOOK_PATH)
            CACHE.mtime = mtime
        return CACHE.payload

    if DATA_FILE.exists():
        if CACHE.payload is None or CACHE.mtime != data_mtime:
            CACHE.payload = json.loads(DATA_FILE.read_text(encoding="utf-8"))
            CACHE.mtime = data_mtime
        return CACHE.payload

    if CACHE.payload is None:
        raise FileNotFoundError(
            f"Workbook not found at {WORKBOOK_PATH} and no bundled data file exists at {DATA_FILE}."
        )
    return CACHE.payload


class TradeLogHandler(SimpleHTTPRequestHandler):
    def translate_path(self, path: str) -> str:
        parsed = urlparse(path).path
        if parsed in ("", "/"):
            return str(STATIC_DIR / "index.html")
        if parsed.startswith("/static/"):
            relative = parsed.removeprefix("/static/")
            return str(STATIC_DIR / relative)
        return super().translate_path(path)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)

        if parsed.path == "/api/trades":
            self.write_json(self.filter_trades(parse_qs(parsed.query)))
            return

        if parsed.path == "/api/summary":
            payload = get_payload()
            self.write_json(
                {
                    "generated_at": payload["generated_at"],
                    "workbook_path": payload["workbook_path"],
                    "summary": payload["summary"],
                    "monthly": payload["monthly"],
                    "filters": payload["filters"],
                }
            )
            return

        super().do_GET()

    def filter_trades(self, query: dict[str, list[str]]) -> dict[str, Any]:
        payload = get_payload()
        trades = payload["trades"]

        month = query.get("month", [""])[0]
        setup = query.get("setup", [""])[0]
        side = query.get("side", [""])[0]
        search = query.get("search", [""])[0].strip().lower()

        filtered = []
        for trade in trades:
            if month and trade.get("month") != month:
                continue
            if setup and trade.get("setup") != setup:
                continue
            if side and trade.get("side") != side:
                continue

            if search:
                haystack = " ".join(
                    str(trade.get(field, "") if trade.get(field, "") is not None else "")
                    for field in (
                        "ticker",
                        "setup",
                        "side",
                        "day",
                        "notes",
                        "technicals",
                        "fundamentals",
                    )
                ).lower()
                if search not in haystack:
                    continue

            filtered.append(trade)

        return {"count": len(filtered), "trades": filtered}

    def write_json(self, payload: dict[str, Any], status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    port = int(os.environ.get("PORT", "8000"))
    host = os.environ.get("HOST", "0.0.0.0")
    server = ThreadingHTTPServer((host, port), TradeLogHandler)
    print(f"Trade log available at http://{host}:{port}")
    if WORKBOOK_PATH.exists():
        print(f"Workbook: {WORKBOOK_PATH}")
    elif DATA_FILE.exists():
        print(f"Bundled data: {DATA_FILE}")
    server.serve_forever()


if __name__ == "__main__":
    main()
