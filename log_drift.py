"""
Сравнивает план из schedule.csv (окно [сегодня; +6 дней]) с тем, что реально
залито в TimeTargeting кампаний в Директе, и пишет результат в Google Таблицу.

В обычном случае — одна строка-сводка раз в 6 часов («32/32 совпадает»). Если
что-то разошлось (например, план залился не полностью) — дополнительно по
строке на каждую расходящуюся кампанию, с деталями.
"""

import sys
from datetime import datetime
from zoneinfo import ZoneInfo

import direct_api
import sheets_api
import time_targeting
from sync_schedule import SCHEDULE_PATH, load_schedule

MSK = ZoneInfo("Europe/Moscow")
SPREADSHEET_ID = "18Ui7OSHLpSKJimlzEjlInlNpc7q_5P08Ln6Kve8ryWc"


def fail(message: str) -> None:
    print("\n❌ " + message)
    sys.exit(1)


def main() -> None:
    if not direct_api.TOKEN:
        fail("Не найден секрет YANDEX_DIRECT_TOKEN.")
    if not direct_api.CLIENT_LOGIN:
        fail("Не найден секрет YANDEX_CLIENT_LOGIN.")

    rows = load_schedule(SCHEDULE_PATH)
    campaigns = sorted({r["campaign"] for r in rows})
    now = datetime.now(MSK)
    today = now.date()

    planned = {name: time_targeting.build_schedule_items(rows, name, today) for name in campaigns}
    planned = {name: items for name, items in planned.items() if items}

    if not planned:
        print(f"Сейчас {now:%Y-%m-%d %H:%M МСК} — вне периода теста. Лог не пишем.")
        return

    try:
        live = direct_api.get_all_time_targeting(list(planned.keys()))
    except direct_api.DirectApiError as exc:
        fail(f"Не удалось прочитать TimeTargeting из Директа: {exc}")

    missing = set(planned) - set(live)
    ts = now.strftime("%Y-%m-%d %H:%M")

    mismatch_rows = []
    for name, missing_reason in [(n, "кампания не найдена в кабинете") for n in sorted(missing)]:
        mismatch_rows.append([ts, "MISMATCH", name, missing_reason])

    for name, want in planned.items():
        if name in missing:
            continue
        got = live[name]["schedule_items"]
        if sorted(got) != sorted(want):
            mismatch_rows.append(
                [ts, "MISMATCH", name, f"план: {'; '.join(want)} | в Директе: {'; '.join(got) or 'пусто'}"]
            )

    total = len(planned)
    ok = total - len(mismatch_rows)
    summary = [ts, "SUMMARY", "-", f"{ok}/{total} совпадает" + (f", {len(mismatch_rows)} расхождений" if mismatch_rows else "")]

    print(summary[3])
    for r in mismatch_rows:
        print(f"  ⚠️  {r[2]}: {r[3]}")

    try:
        sheet_name = sheets_api.get_first_sheet_title(SPREADSHEET_ID)
        sheets_api.append_rows(SPREADSHEET_ID, sheet_name, [summary] + mismatch_rows)
    except sheets_api.SheetsApiError as exc:
        fail(f"Не удалось записать в Google Таблицу: {exc}")

    print("\n✅ Записано в Google Таблицу.")


if __name__ == "__main__":
    main()
