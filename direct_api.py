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
    """Вернуть {campaign_name: {"id": int, "state": str}} для живых кампаний по именам."""
    result = {}
    for batch in chunks(names, CAMPAIGN_BATCH):
        payload = _request(
            "campaigns",
            {
                "method": "get",
                "params": {
                    "SelectionCriteria": {"Names": batch},
                    "FieldNames": ["Id", "Name", "State"],
                },
            },
        )
        for c in payload["result"]["Campaigns"]:
            result[c["Name"]] = {"id": c["Id"], "state": c["State"]}
    return result


def suspend(campaign_ids: list) -> None:
    for batch in chunks(campaign_ids, CAMPAIGN_BATCH):
        payload = _request("campaigns", {"method": "suspend", "params": {"SelectionCriteria": {"Ids": batch}}})
        _raise_on_action_errors(payload)


def resume(campaign_ids: list) -> None:
    for batch in chunks(campaign_ids, CAMPAIGN_BATCH):
        payload = _request("campaigns", {"method": "resume", "params": {"SelectionCriteria": {"Ids": batch}}})
        _raise_on_action_errors(payload)


def _raise_on_action_errors(payload: dict) -> None:
    problems = [
        r for r in payload.get("result", {}).get("SuspendResults", payload.get("result", {}).get("ResumeResults", []))
        if "Errors" in r
    ]
    if problems:
        raise DirectApiError(f"Директ вернул ошибки по кампаниям: {problems}")
