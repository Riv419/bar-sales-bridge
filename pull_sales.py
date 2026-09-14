#!/usr/bin/env python3
"""
Pull Square sales for all three bars (Tique's, Paddle Bar, Volstead) and write
them to JSON files that Ryan's nightly Cowork task reads.

Runs on GitHub Actions (which CAN reach connect.squareup.com). Ryan's nightly
Cowork task then reads the committed JSON instead of calling Square directly.

Files written on every run:
    wrap.json                 the most recent NIGHT — what the 1 AM wrap reads.
                              Before 4 AM ET = the day in progress; after 4 AM ET
                              = yesterday's full day, marked "is_final": true.
    days/YYYY-MM-DD.json      one file per business day (today in progress +
                              yesterday finalized). A late run can no longer wipe
                              last night's numbers.
    paddle_volstead.json      the day in progress (old name, kept for compatibility).

Tokens are read from environment variables (GitHub Actions secrets):
    SQUARE_TIQUES_TOKEN, SQUARE_PADDLE_TOKEN, SQUARE_VOLSTEAD_TOKEN
They are never printed.

Business day = 4:00 AM America/New_York to 4:00 AM the next day.
"""

import json
import os
import sys
import datetime as dt
from zoneinfo import ZoneInfo

import requests

SQUARE_BASE = "https://connect.squareup.com"
SQUARE_VERSION = "2025-01-23"
ET = ZoneInfo("America/New_York")

# One entry per bar. Token comes from the matching env var / GitHub secret.
BARS = [
    {"key": "tiques",   "name": "Tique's",    "location_id": "L91FN4CPCADRA", "token_env": "SQUARE_TIQUES_TOKEN"},
    {"key": "paddle",   "name": "Paddle Bar", "location_id": "RMSRRF4GTR3J5", "token_env": "SQUARE_PADDLE_TOKEN"},
    {"key": "volstead", "name": "Volstead",   "location_id": "G9XHMF97SD95W", "token_env": "SQUARE_VOLSTEAD_TOKEN"},
]


def business_day_date(now_et):
    """The business day that a moment in Eastern time belongs to.

    The day rolls over at 4:00 AM Eastern. Before 4 AM we are still in
    yesterday's business day (this is what makes the ~1 AM wrap look back at
    the night that just happened).
    """
    if now_et.time() < dt.time(4, 0):
        return (now_et - dt.timedelta(days=1)).date()
    return now_et.date()


def business_day_bounds(biz_date):
    """(start_utc, end_utc) for a full business day: 4 AM ET that date -> 4 AM ET next day."""
    start_et = dt.datetime.combine(biz_date, dt.time(4, 0), tzinfo=ET)
    end_et = start_et + dt.timedelta(days=1)
    return start_et.astimezone(dt.timezone.utc), end_et.astimezone(dt.timezone.utc)


def business_day_window(now_utc):
    """(start_utc, end_utc) for the business day that 'now' falls in, ending at 'now'."""
    biz_date = business_day_date(now_utc.astimezone(ET))
    start_utc, _ = business_day_bounds(biz_date)
    return start_utc, now_utc


def rfc3339(t):
    return t.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def cents_to_dollars(cents):
    return round((cents or 0) / 100.0, 2)


def search_orders(token, location_id, state, date_field, start_iso, end_iso):
    """Return all orders for one state, paging through results."""
    headers = {
        "Authorization": f"Bearer {token}",
        "Square-Version": SQUARE_VERSION,
        "Content-Type": "application/json",
    }
    orders = []
    cursor = None
    while True:
        body = {
            "location_ids": [location_id],
            "return_entries": False,
            "limit": 500,
            "query": {
                "filter": {
                    "state_filter": {"states": [state]},
                    "date_time_filter": {date_field: {"start_at": start_iso, "end_at": end_iso}},
                },
                "sort": {"sort_field": date_field.upper(), "sort_order": "DESC"},
            },
        }
        if cursor:
            body["cursor"] = cursor
        resp = requests.post(f"{SQUARE_BASE}/v2/orders/search", headers=headers, json=body, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        orders.extend(data.get("orders", []))
        cursor = data.get("cursor")
        if not cursor:
            break
    return orders


def fetch_category_map(token, variation_ids):
    """Best-effort: map each line-item catalog_object_id to a category name.

    Returns {} on any failure — category is a nice-to-have, never fatal.
    """
    if not variation_ids:
        return {}
    headers = {
        "Authorization": f"Bearer {token}",
        "Square-Version": SQUARE_VERSION,
        "Content-Type": "application/json",
    }
    try:
        # 1) category id -> category name
        cat_names = {}
        cursor = None
        while True:
            body = {"object_types": ["CATEGORY"], "include_deleted_objects": False}
            if cursor:
                body["cursor"] = cursor
            r = requests.post(f"{SQUARE_BASE}/v2/catalog/search", headers=headers, json=body, timeout=60)
            r.raise_for_status()
            d = r.json()
            for obj in d.get("objects", []):
                if obj.get("type") == "CATEGORY":
                    cat_names[obj["id"]] = obj.get("category_data", {}).get("name")
            cursor = d.get("cursor")
            if not cursor:
                break

        # 2) variation id -> parent item -> category id  (batch, with related objects)
        var_to_cat = {}
        ids = list(variation_ids)
        for i in range(0, len(ids), 200):
            chunk = ids[i:i + 200]
            r = requests.post(
                f"{SQUARE_BASE}/v2/catalog/batch-retrieve",
                headers=headers,
                json={"object_ids": chunk, "include_related_objects": True},
                timeout=60,
            )
            r.raise_for_status()
            d = r.json()
            items_by_id = {o["id"]: o for o in d.get("related_objects", []) if o.get("type") == "ITEM"}
            for obj in d.get("objects", []):
                if obj.get("type") != "ITEM_VARIATION":
                    continue
                item_id = obj.get("item_variation_data", {}).get("item_id")
                item = items_by_id.get(item_id)
                if not item:
                    continue
                idata = item.get("item_data", {})
                cat_id = None
                rc = idata.get("reporting_category")
                if isinstance(rc, dict):
                    cat_id = rc.get("id")
                if not cat_id and idata.get("categories"):
                    cat_id = idata["categories"][0].get("id")
                if not cat_id:
                    cat_id = idata.get("category_id")
                var_to_cat[obj["id"]] = cat_names.get(cat_id)
        return var_to_cat
    except Exception:
        return {}


def summarize_bar(token, bar, start_iso, end_iso):
    completed = search_orders(token, bar["location_id"], "COMPLETED", "closed_at", start_iso, end_iso)
    open_orders = search_orders(token, bar["location_id"], "OPEN", "created_at", start_iso, end_iso)
    all_orders = completed + open_orders

    net_cents = 0
    tips_cents = 0
    tax_cents = 0
    cash_cents = 0
    card_cents = 0
    open_tab_cents = 0
    discounts = {}          # name -> {"amount_cents": int, "count": int}
    line_items = {}         # (name, variation) -> {"qty": float, "gross_cents": int, "cat_var_id": str|None}
    custom_items = {}       # name -> {"qty": float, "gross_cents": int}
    variation_ids = set()

    for o in all_orders:
        total = (o.get("total_money") or {}).get("amount", 0) or 0
        net_cents += total
        tips_cents += (o.get("total_tip_money") or {}).get("amount", 0) or 0
        tax_cents += (o.get("total_tax_money") or {}).get("amount", 0) or 0
        if o.get("state") == "OPEN":
            open_tab_cents += total

        for t in o.get("tenders", []) or []:
            amt = (t.get("amount_money") or {}).get("amount", 0) or 0
            if t.get("type") == "CASH":
                cash_cents += amt
            else:
                card_cents += amt

        for d in o.get("discounts", []) or []:
            name = d.get("name") or "(unnamed discount)"
            amt = (d.get("amount_money") or {}).get("amount", 0) or 0
            row = discounts.setdefault(name, {"amount_cents": 0, "count": 0})
            row["amount_cents"] += amt
            row["count"] += 1

        for li in o.get("line_items", []) or []:
            try:
                qty = float(li.get("quantity", "0") or 0)
            except ValueError:
                qty = 0.0
            gross = (li.get("gross_sales_money") or li.get("total_money") or {}).get("amount", 0) or 0
            cat_var_id = li.get("catalog_object_id")
            name = li.get("name") or "(custom amount)"
            if cat_var_id:
                variation_ids.add(cat_var_id)
                var = li.get("variation_name") or ""
                key = (name, var)
                row = line_items.setdefault(key, {"qty": 0.0, "gross_cents": 0, "cat_var_id": cat_var_id})
                row["qty"] += qty
                row["gross_cents"] += gross
            else:
                row = custom_items.setdefault(name, {"qty": 0.0, "gross_cents": 0})
                row["qty"] += qty
                row["gross_cents"] += gross

    cat_map = fetch_category_map(token, variation_ids)

    line_items_out = []
    for (name, var), row in line_items.items():
        line_items_out.append({
            "name": name,
            "variation": var,
            "category": cat_map.get(row["cat_var_id"]),
            "qty": round(row["qty"], 2),
            "gross": cents_to_dollars(row["gross_cents"]),
        })
    line_items_out.sort(key=lambda r: r["qty"], reverse=True)

    custom_out = [
        {"name": n, "qty": round(r["qty"], 2), "gross": cents_to_dollars(r["gross_cents"])}
        for n, r in custom_items.items()
    ]

    discounts_out = [
        {"name": n, "amount": cents_to_dollars(r["amount_cents"]), "count": r["count"]}
        for n, r in discounts.items()
    ]
    discounts_out.sort(key=lambda r: r["amount"], reverse=True)

    net = cents_to_dollars(net_cents)
    return {
        "name": bar["name"],
        "location_id": bar["location_id"],
        "net_sales": net,
        "tax_backout_base": round(net / 1.0675, 2),  # Ohio 6.75% embedded
        "transaction_count": len(all_orders),
        "completed_count": len(completed),
        "open_count": len(open_orders),
        "open_tab_total": cents_to_dollars(open_tab_cents),
        "tips": cents_to_dollars(tips_cents),
        "tax_collected": cents_to_dollars(tax_cents),
        "cash_total": cents_to_dollars(cash_cents),
        "card_total": cents_to_dollars(card_cents),
        "discounts": discounts_out,
        "line_items": line_items_out,
        "custom_amount_items": custom_out,
    }


def pull_day(biz_date, now_utc, is_final):
    """Pull all three bars for one business day.

    is_final=False -> the day in progress: window is 4 AM ET .. now.
    is_final=True  -> a finished day: window is the full 4 AM .. 4 AM span.
    """
    start_utc, full_end_utc = business_day_bounds(biz_date)
    end_utc = full_end_utc if is_final else now_utc
    start_iso, end_iso = rfc3339(start_utc), rfc3339(end_utc)

    out = {
        "generated_at_utc": rfc3339(now_utc),
        "generated_at_et": now_utc.astimezone(ET).strftime("%Y-%m-%d %H:%M:%S %Z"),
        "business_day": biz_date.isoformat(),
        "business_day_start_et": start_utc.astimezone(ET).strftime("%Y-%m-%d %H:%M %Z"),
        "is_final": is_final,
        "window_start_utc": start_iso,
        "window_end_utc": end_iso,
        "bars": {},
        "errors": [],
    }

    for bar in BARS:
        token = os.environ.get(bar["token_env"], "").strip()
        if not token:
            out["errors"].append(f'{bar["name"]}: missing {bar["token_env"]} secret')
            continue
        try:
            out["bars"][bar["key"]] = summarize_bar(token, bar, start_iso, end_iso)
        except requests.HTTPError as e:
            code = e.response.status_code if e.response is not None else "?"
            out["errors"].append(f'{bar["name"]}: Square API HTTP {code}')
        except Exception as e:
            out["errors"].append(f'{bar["name"]}: {type(e).__name__}: {e}')

    # Combined line so readers don't have to add it up.
    bars = out["bars"].values()
    out["combined"] = {
        "net_sales": round(sum(b["net_sales"] for b in bars), 2),
        "transaction_count": sum(b["transaction_count"] for b in bars),
        "tips": round(sum(b["tips"] for b in bars), 2),
        "open_tab_total": round(sum(b["open_tab_total"] for b in bars), 2),
    }
    return out


def write_json(path, data):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def main():
    now_utc = dt.datetime.now(dt.timezone.utc)
    now_et = now_utc.astimezone(ET)
    today_biz = business_day_date(now_et)
    prev_biz = today_biz - dt.timedelta(days=1)

    # 1) The business day in progress (4 AM ET .. now).
    today = pull_day(today_biz, now_utc, is_final=False)
    write_json("paddle_volstead.json", today)          # kept for anything still reading the old name
    write_json(f"days/{today_biz.isoformat()}.json", today)

    # 2) The previous business day, pulled over its FULL 4 AM..4 AM window and marked final.
    #    This is what protects last night's numbers when GitHub runs us late (after 4 AM).
    prev = pull_day(prev_biz, now_utc, is_final=True)
    if prev["bars"]:
        write_json(f"days/{prev_biz.isoformat()}.json", prev)

    # 3) wrap.json = "the most recent night", which is what the 1 AM wrap wants:
    #    before 4 AM ET that's the day in progress; after 4 AM it's yesterday, finalized.
    wrap = today if now_et.time() < dt.time(4, 0) else prev
    write_json("wrap.json", wrap)

    # Console output is safe: no tokens, just status lines.
    print(f'today  {today_biz}: bars={list(today["bars"].keys())} errors={today["errors"]}')
    print(f'prev   {prev_biz}: bars={list(prev["bars"].keys())} errors={prev["errors"]} (final)')
    print(f'wrap.json -> business day {wrap["business_day"]} (final={wrap["is_final"]})')
    # Exit non-zero only if every bar failed, so one bad token still commits the others.
    if not today["bars"] and not prev["bars"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
