"""
Синхронизация ON/OFF switchback-теста nbd RU (аккаунт porg-y7vq4sb5) с расписанием
из schedule.csv (выгрузка таблицы Дани, зафиксирована в Jira ASMARKET-1819).

Что делает:
  - смотрит текущее время в МСК;
  - если тест ещё не начался или уже закончился — ничего не трогает;
  - иначе находит нужный блок для каждой из 32 кампаний и сверяет с реальным
    состоянием в Директе; включает/выключает только там, где есть расхождение.

Только этот файл нужно запускать. Секреты (YANDEX_DIRECT_TOKEN, YANDEX_CLIENT_LOGIN)
берутся из окружения — их кладём в GitHub Secrets, в коде их нет.
"""

import csv
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

import direct_api

SCHEDULE_PATH = "schedule.csv"
MSK = ZoneInfo("Europe/Moscow")


def fail(message: str) -> None:
    print("\n❌ " + message)
    sys.exit(1)


def load_schedule(path: str) -> list:
    rows = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            rows.append(
                {
                    "block_start": datetime.strptime(row["block_start"], "%Y-%m-%d %H:%M").replace(tzinfo=MSK),
                    "block_end": datetime.strptime(row["block_end"], "%Y-%m-%d %H:%M").replace(tzinfo=MSK),
                    "campaign": row["campaign"],
                    "treatment": row["treatment"].strip().upper(),
                }
            )
    return rows


def current_desired_state(rows: list, now: datetime) -> dict:
    """{campaign_name: "ON"/"OFF"} для блока, в который попадает `now`. Пусто, если now вне теста."""
    desired = {}
    for r in rows:
        if r["block_start"] <= now < r["block_end"]:
            desired[r["campaign"]] = r["treatment"]
    return desired


def main() -> None:
    if not direct_api.TOKEN:
        fail(
            "Не найден секрет YANDEX_DIRECT_TOKEN. "
            "Проверь Settings → Secrets and variables → Actions в этом репозитории."
        )
    if not direct_api.CLIENT_LOGIN:
        fail("Не найден секрет YANDEX_CLIENT_LOGIN (ожидается porg-y7vq4sb5).")

    rows = load_schedule(SCHEDULE_PATH)
    now = datetime.now(MSK)
    desired = current_desired_state(rows, now)

    if not desired:
        test_start = min(r["block_start"] for r in rows)
        test_end = max(r["block_end"] for r in rows)
        print(f"Сейчас {now:%Y-%m-%d %H:%M МСК} — вне периода теста ({test_start:%Y-%m-%d} — {test_end:%Y-%m-%d}). Ничего не делаю.")
        return

    print(f"Сейчас {now:%Y-%m-%d %H:%M МСК}. Кампаний в расписании на этот блок: {len(desired)}.\n")

    try:
        live = direct_api.get_states(list(desired.keys()))
    except direct_api.DirectApiError as exc:
        fail(f"Не удалось получить статусы кампаний из Директа: {exc}")

    missing = set(desired) - set(live)
    if missing:
        fail(
            "Эти кампании из расписания не найдены в кабинете по точному имени "
            f"(проверь названия!): {sorted(missing)}"
        )

    to_suspend, to_resume = [], []
    print(f"{'КАМПАНИЯ':<55} {'БЫЛО':<10} {'ДОЛЖНО':<8} {'ДЕЙСТВИЕ'}")
    print("-" * 95)
    for name, want in desired.items():
        campaign_id = live[name]["id"]
        actual_state = live[name]["state"]  # "ON" или "SUSPENDED" (либо другое, если кампания не в тесте)
        is_on = actual_state == "ON"
        wants_on = want == "ON"
        if wants_on and not is_on:
            action = "resume"
            to_resume.append(campaign_id)
        elif not wants_on and is_on:
            action = "suspend"
            to_suspend.append(campaign_id)
        else:
            action = "—"
        print(f"{name:<55} {actual_state:<10} {want:<8} {action}")

    try:
        if to_suspend:
            direct_api.suspend(to_suspend)
        if to_resume:
            direct_api.resume(to_resume)
    except direct_api.DirectApiError as exc:
        fail(f"Ошибка при переключении кампаний: {exc}")

    print(f"\nГотово. Выключено: {len(to_suspend)}, включено: {len(to_resume)}, без изменений: {len(desired) - len(to_suspend) - len(to_resume)}.")


if __name__ == "__main__":
    main()
