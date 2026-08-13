"""
Тест связи с API Яндекс.Директа для switchback-теста nbd RU.

Только читает текущее состояние 32 кампаний из schedule.csv (метод campaigns.get) —
ничего не включает и не выключает. Нужен, чтобы до старта теста (17.08) убедиться,
что токен, Client-Login и точные названия кампаний совпадают с тем, что в кабинете.
"""

import sys

import direct_api
import sync_schedule


def fail(message: str) -> None:
    print("\n❌ " + message)
    sys.exit(1)


def main() -> None:
    if not direct_api.TOKEN:
        fail("Не найден секрет YANDEX_DIRECT_TOKEN.")
    if not direct_api.CLIENT_LOGIN:
        fail("Не найден секрет YANDEX_CLIENT_LOGIN (ожидается porg-y7vq4sb5).")

    rows = sync_schedule.load_schedule(sync_schedule.SCHEDULE_PATH)
    names = sorted({r["campaign"] for r in rows})
    print(f"Кампаний в schedule.csv: {len(names)}\n")

    try:
        live = direct_api.get_states(names)
    except direct_api.DirectApiError as exc:
        fail(f"Не удалось получить статусы кампаний из Директа: {exc}")

    missing = [n for n in names if n not in live]

    print(f"{'КАМПАНИЯ':<60} {'ID':<12} {'СТАТУС В ДИРЕКТЕ'}")
    print("-" * 95)
    for name in names:
        if name in live:
            print(f"{name:<60} {live[name]['id']:<12} {live[name]['state']}")
        else:
            print(f"{name:<60} {'—':<12} НЕ НАЙДЕНА В КАБИНЕТЕ")

    print(f"\nНайдено: {len(names) - len(missing)} из {len(names)}.")
    if missing:
        fail(
            "Эти кампании из schedule.csv не нашлись в кабинете по точному имени — "
            f"переключение работать не будет, пока это не исправлено: {missing}"
        )
    print("\n✅ Связь работает, все 32 кампании найдены. Можно спокойно ждать 17.08.")


if __name__ == "__main__":
    main()
