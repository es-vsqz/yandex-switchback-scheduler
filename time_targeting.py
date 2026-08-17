"""
Расчёт TimeTargeting.Schedule (временной таргетинг Директа) из schedule.csv.

TimeTargeting хранит расписание по дню недели (1=пн..7=вс), максимум 7 строк,
без привязки к конкретной дате. Поэтому окно [сегодня; сегодня+6] нужно
пересчитывать и полностью перезаписывать регулярно — тогда слот каждого дня
недели всегда соответствует его ближайшему предстоящему наступлению в
6-недельном (не повторяющемся) расписании Дани.
"""

from datetime import date, datetime, timedelta

WINDOW_DAYS = 7


def hourly_coefficients(rows: list, campaign: str, day: date) -> list:
    """24 числа (0 или 100) на конкретную календарную дату кампании. None — вне периода теста."""
    coefs = []
    for hour in range(24):
        moment = datetime(day.year, day.month, day.day, hour)
        match = next(
            (r for r in rows if r["campaign"] == campaign and r["block_start"].replace(tzinfo=None) <= moment < r["block_end"].replace(tzinfo=None)),
            None,
        )
        coefs.append(None if match is None else (100 if match["treatment"] == "ON" else 0))
    return coefs


def build_schedule_items(rows: list, campaign: str, start: date) -> list:
    """Строки для TimeTargeting.Schedule.Items на окно [start, start+6], по одной на день недели."""
    items = []
    for i in range(WINDOW_DAYS):
        day = start + timedelta(days=i)
        coefs = hourly_coefficients(rows, campaign, day)
        if any(c is None for c in coefs):
            continue  # день вне периода теста — не включаем, Директ проставит дефолт (100 = обычный показ)
        dow = day.isoweekday()  # 1=пн .. 7=вс
        items.append(f"{dow}," + ",".join(str(c) for c in coefs))
    return items
