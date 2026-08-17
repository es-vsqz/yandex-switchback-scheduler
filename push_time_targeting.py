"""
Заливает TimeTargeting.Schedule (окно [сегодня; сегодня+6]) во все кампании
switchback-теста nbd RU из schedule.csv. Запускается несколько раз в сутки —
операция идемпотентна (просто переустанавливает тот же план), лишний запуск
безвреден и снижает риск, что пропуск одного прогона оставит устаревший план
на день недели дольше, чем на несколько часов.

В отличие от sync_schedule.py (suspend/resume), этот скрипт НЕ трогает статус
кампании — только почасовой коэффициент ставки. Кампании остаются в State=ON
весь тест, показами управляет только TimeTargeting.
"""

import os
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import direct_api
import time_targeting
from sync_schedule import SCHEDULE_PATH, load_schedule

MSK = ZoneInfo("Europe/Moscow")
PILOT_CAMPAIGN = os.environ.get("PILOT_CAMPAIGN", "").strip()


def fail(message: str) -> None:
    print("\n❌ " + message)
    sys.exit(1)


def main() -> None:
    if not direct_api.TOKEN:
        fail("Не найден секрет YANDEX_DIRECT_TOKEN.")
    if not direct_api.CLIENT_LOGIN:
        fail("Не найден секрет YANDEX_CLIENT_LOGIN (ожидается porg-y7vq4sb5).")

    rows = load_schedule(SCHEDULE_PATH)
    campaigns = sorted({r["campaign"] for r in rows})
    if PILOT_CAMPAIGN:
        if PILOT_CAMPAIGN not in campaigns:
            fail(f"PILOT_CAMPAIGN={PILOT_CAMPAIGN!r} не найдена в schedule.csv")
        campaigns = [PILOT_CAMPAIGN]
        print(f"⚠️  Пилотный режим — только {PILOT_CAMPAIGN}\n")
    today = datetime.now(MSK).date()

    plan = {}
    for name in campaigns:
        items = time_targeting.build_schedule_items(rows, name, today)
        if items:
            plan[name] = items

    if not plan:
        print(f"Сегодня {today} — вне периода теста ни для одной кампании. Ничего не делаю.")
        return

    print(f"Окно: {today} — {today + timedelta(days=6)}. Кампаний в плане: {len(plan)}.\n")
    for name, items in plan.items():
        print(f"{name}:")
        for item in items:
            print(f"    {item}")

    try:
        live = direct_api.get_states(list(plan.keys()))
    except direct_api.DirectApiError as exc:
        fail(f"Не удалось получить ID кампаний из Директа: {exc}")

    missing = set(plan) - set(live)
    if missing:
        fail(f"Эти кампании не найдены в кабинете по точному имени: {sorted(missing)}")

    campaign_schedules = {live[name]["id"]: items for name, items in plan.items()}

    try:
        direct_api.update_time_targeting(campaign_schedules)
    except direct_api.DirectApiError as exc:
        fail(f"Ошибка при обновлении TimeTargeting: {exc}")

    print(f"\nГотово. TimeTargeting обновлён для {len(campaign_schedules)} кампаний.")

    if PILOT_CAMPAIGN:
        campaign_id = live[PILOT_CAMPAIGN]["id"]
        readback = direct_api.get_time_targeting(campaign_id)
        sent = campaign_schedules[campaign_id]
        print("\nПроверка (читаем обратно из Директа):")
        for it in readback:
            print(" ", it)
        print("Совпадает с отправленным:", sorted(readback) == sorted(sent))


if __name__ == "__main__":
    main()
