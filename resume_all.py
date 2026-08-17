"""
Разовый скрипт перехода на TimeTargeting: переводит все 32 кампании switchback-теста
в постоянный State=ON, безусловно, не глядя на текущий блок schedule.csv.

Нужен ровно один раз при переключении с suspend/resume на TimeTargeting — дальше
показами управляет только почасовой коэффициент ставки (push_time_targeting.py),
а не статус кампании, поэтому ни одна кампания не должна оставаться SUSPENDED.
Повторный запуск безвреден (resume уже включённой кампании — no-op у Директа).
"""

import sys

import direct_api
from sync_schedule import SCHEDULE_PATH, load_schedule


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

    try:
        live = direct_api.get_states(campaigns)
    except direct_api.DirectApiError as exc:
        fail(f"Не удалось получить статусы кампаний: {exc}")

    missing = set(campaigns) - set(live)
    if missing:
        fail(f"Не найдены в кабинете: {sorted(missing)}")

    suspended = [name for name, info in live.items() if info["state"] != "ON"]
    print(f"Всего кампаний: {len(campaigns)}. Сейчас не ON: {len(suspended)}.")
    for name in suspended:
        print(f"  {name}: {live[name]['state']} → ON")

    if not suspended:
        print("\nВсе кампании уже ON, ничего делать не нужно.")
        return

    ids = [live[name]["id"] for name in suspended]
    try:
        direct_api.resume(ids)
    except direct_api.DirectApiError as exc:
        fail(f"Ошибка при включении кампаний: {exc}")

    print(f"\n✅ Готово. Включено: {len(ids)}.")


if __name__ == "__main__":
    main()
