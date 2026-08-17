"""
Тонкая обёртка над Яндекс.Директ API v5 для переключения кампаний ON/OFF.

Секреты (токен, логин клиента) приходят из окружения — в коде их нет.
Стиль: голый urllib, без внешних зависимостей (как в ppc-audit-robot/collect_yandex.py).
"""

import json
import os
import urllib.error
import urllib.request

API_BASE = "https://api.direct.yandex.com/json/v5/"
CAMPAIGN_BATCH = 10  # лимит Директа на длину CampaignIds / Ids за один запрос

TOKEN = os.environ.get("YANDEX_DIRECT_TOKEN", "").strip()
CLIENT_LOGIN = os.environ.get("YANDEX_CLIENT_LOGIN", "").strip()


class DirectApiError(Exception):
    pass


def chunks(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i : i + n]


def _request(service: str, body: dict) -> dict:
    headers = {
        "Authorization": f"Bearer {TOKEN}",
        "Accept-Language": "ru",
        "Content-Type": "application/json; charset=utf-8",
    }
    if CLIENT_LOGIN:
        headers["Client-Login"] = CLIENT_LOGIN
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(API_BASE + service, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        raise DirectApiError(f"HTTP {exc.code}: {exc.read().decode('utf-8', errors='replace')[:500]}")
    except Exception as exc:  # noqa: BLE001
        raise DirectApiError(str(exc))
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        raise DirectApiError("ответ не JSON: " + raw[:300])
    if "error" in payload:
        e = payload["error"]
        raise DirectApiError(f"{e.get('error_code')} {e.get('error_string')}: {e.get('error_detail')}")
    return payload


def get_states(names: list) -> dict:
    """Вернуть {campaign_name: {"id": int, "state": str}} для живых кампаний по именам.

    У campaigns.get нет фильтра по имени — тянем все кампании кабинета одним
    запросом (Page.Limit покрывает любой реалистичный размер аккаунта) и
    сопоставляем по имени на своей стороне.
    """
    payload = _request(
        "campaigns",
        {
            "method": "get",
            "params": {
                "SelectionCriteria": {},
                "FieldNames": ["Id", "Name", "State"],
                "Page": {"Limit": 10000},
            },
        },
    )
    wanted = set(names)
    result = {}
    for c in payload["result"]["Campaigns"]:
        if c["Name"] in wanted:
            result[c["Name"]] = {"id": c["Id"], "state": c["State"]}
    return result


def suspend(campaign_ids: list) -> None:
    errors = []
    for batch in chunks(campaign_ids, CAMPAIGN_BATCH):
        payload = _request("campaigns", {"method": "suspend", "params": {"SelectionCriteria": {"Ids": batch}}})
        errors += _action_errors(payload, "SuspendResults")
    if errors:
        raise DirectApiError(f"Директ вернул ошибки при выключении кампаний: {errors}")


def resume(campaign_ids: list) -> None:
    errors = []
    for batch in chunks(campaign_ids, CAMPAIGN_BATCH):
        payload = _request("campaigns", {"method": "resume", "params": {"SelectionCriteria": {"Ids": batch}}})
        errors += _action_errors(payload, "ResumeResults")
    if errors:
        raise DirectApiError(f"Директ вернул ошибки при включении кампаний: {errors}")


def _action_errors(payload: dict, results_key: str) -> list:
    """Errors: [] у Директа означает «без ошибок» — считаем проблемой только непустой список."""
    return [r for r in payload.get("result", {}).get(results_key, []) if r.get("Errors")]


def update_time_targeting(campaign_schedules: dict) -> None:
    """campaign_schedules: {campaign_id: [строки Schedule.Items]}. Не более 10 кампаний за вызов."""
    items = list(campaign_schedules.items())
    errors = []
    for batch in chunks(items, CAMPAIGN_BATCH):
        payload = _request(
            "campaigns",
            {
                "method": "update",
                "params": {
                    "Campaigns": [
                        {
                            "Id": campaign_id,
                            "TimeZone": "Europe/Moscow",
                            "TimeTargeting": {
                                "Schedule": {"Items": schedule_items},
                                "ConsiderWorkingWeekends": "NO",
                            },
                        }
                        for campaign_id, schedule_items in batch
                    ]
                },
            },
        )
        errors += _action_errors(payload, "UpdateResults")
    if errors:
        raise DirectApiError(f"Директ вернул ошибки при обновлении TimeTargeting: {errors}")


def get_time_targeting(campaign_id: int) -> list:
    """Читает обратно TimeTargeting.Schedule.Items кампании — для проверки после update."""
    payload = _request(
        "campaigns",
        {
            "method": "get",
            "params": {
                "SelectionCriteria": {"Ids": [campaign_id]},
                "FieldNames": ["Id", "Name", "TimeTargeting"],
            },
        },
    )
    campaigns = payload["result"]["Campaigns"]
    if not campaigns:
        raise DirectApiError(f"Кампания {campaign_id} не найдена")
    tt = campaigns[0].get("TimeTargeting") or {}
    return tt.get("Schedule", {}).get("Items", [])


def get_all_time_targeting(names: list) -> dict:
    """Вернуть {campaign_name: {"id": int, "schedule_items": list}} одним запросом на весь кабинет."""
    payload = _request(
        "campaigns",
        {
            "method": "get",
            "params": {
                "SelectionCriteria": {},
                "FieldNames": ["Id", "Name", "TimeTargeting"],
                "Page": {"Limit": 10000},
            },
        },
    )
    wanted = set(names)
    result = {}
    for c in payload["result"]["Campaigns"]:
        if c["Name"] in wanted:
            tt = c.get("TimeTargeting") or {}
            result[c["Name"]] = {
                "id": c["Id"],
                "schedule_items": tt.get("Schedule", {}).get("Items", []),
            }
    return result
