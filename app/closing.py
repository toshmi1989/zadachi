"""Proposals for the closing date of a task.

The specialist used to read every task and set his own closing date, earlier than the official term. The data show how: there are a few
habitual "templates" (the 15th of the month of the term, the end of the month before, "at once"), and the choice depends on the nature
of the task and on the document. So the proposal is made in two steps:
  1. the template is chosen by the most similar tasks he has already processed (nearest neighbours over the text, with a small bonus for the
     same document) — this works without any outside service;
  2. when an AI key is set in the settings, the language model chooses the template for each task, seeing the templates, their frequency and the
     closest earlier decisions. The model chooses a TEMPLATE only; the date is always computed here, so it cannot be an impossible one.
Whatever the model returns that is not a known template is replaced by the answer of step 1. A proposal is marked on the task (close_src) until a
person confirms or changes it. On the test data (leave-one-out over the specialist's December list) step 1 picks the same template as he did in
about 6 cases of 10; the rest has to be reviewed."""
import calendar
import json
import math
import os
import re
import statistics
import urllib.error
import urllib.request
from collections import Counter
from datetime import date, timedelta

from .db import audit, connect, now, put_settings, setting, today, tx

MIN_HISTORY = 20
K = 5
SAME_DOC_BONUS = 0.10
ASAP_WINDOW = 6          # a closing date within this many days after the task was entered counts as "at once"
DEFAULT_MODEL = "gpt-4o-mini"
DEFAULT_BASE = "https://api.openai.com/v1"
BATCH = 10
MAX_PER_RUN = 400


class AiError(Exception):
    pass


# ---------------------------------------------------------------- templates
def _d(s) -> date | None:
    try:
        return date.fromisoformat(str(s)[:10]) if s else None
    except ValueError:
        return None


def template_of(due: date, close: date, created: date | None) -> str:
    if created and abs((close - created).days) <= ASAP_WINDOW:
        return "asap"
    off = (close.year * 12 + close.month) - (due.year * 12 + due.month)
    return f"{off}:{close.day}"


def label(t: str, lead: int = 2) -> str:
    if t == "asap":
        return f"сразу (через {lead} дн. после загрузки)"
    off, day = (int(x) for x in t.split(":"))
    where = {0: "месяца срока", -1: "месяца перед сроком", -2: "за два месяца до срока"}.get(off, f"месяца со сдвигом {off}")
    return f"{day} число {where}"


def date_from(t: str, due: date, now_: date, lead: int) -> date:
    """The date of a template for a term, never in the past and never after the term."""
    if t == "asap":
        d = now_ + timedelta(days=lead)
    else:
        off, day = (int(x) for x in t.split(":"))
        y, m = divmod(due.year * 12 + due.month - 1 + off, 12)
        m += 1
        d = date(y, m, min(day, calendar.monthrange(y, m)[1]))
    if d <= now_:
        d = now_ + timedelta(days=lead)
    return min(d, due)


def _tokens(text: str) -> Counter:
    return Counter(re.findall(r"[а-яёқўғҳa-z]{4,}", (text or "").lower()))


class Model:
    """What the specialist has done so far: the templates with their frequency, and a text index to find similar tasks."""

    def __init__(self, c):
        self.h = []
        for r in c.execute("""SELECT id, code, doc_no, text, due, close_date, created_at FROM tasks
                              WHERE close_date IS NOT NULL AND due IS NOT NULL AND close_src='' AND text != ''"""):
            due, close = _d(r["due"]), _d(r["close_date"])
            if not due or not close:
                continue
            created = _d(r["created_at"])
            self.h.append({"code": r["code"], "doc": (r["doc_no"] or "").strip(), "text": r["text"], "due": due, "close": close, "created": created,
                           "tmpl": template_of(due, close, created), "tok": _tokens(r["text"])})
        raw = Counter(x["tmpl"] for x in self.h)
        self.snap = self._snap(raw)
        for x in self.h:
            x["tmpl"] = self.snap.get(x["tmpl"], x["tmpl"])
        self.freq = Counter(x["tmpl"] for x in self.h)
        leads = [(x["close"] - x["created"]).days for x in self.h if x["tmpl"] == "asap" and x["created"]]
        self.lead = min(max(int(statistics.median(leads)), 1), 5) if leads else 2
        df = Counter()
        for x in self.h:
            df.update(set(x["tok"]))
        self.n = max(len(self.h), 1)
        self.df = df
        for x in self.h:
            x["v"] = self._vec(x["tok"])
            x["norm"] = math.sqrt(sum(v * v for v in x["v"].values())) or 1.0

    def _vec(self, tok: Counter) -> dict:
        return {w: (1 + math.log(n)) * math.log(self.n / (1 + self.df.get(w, 0)) + 1) for w, n in tok.items()}

    @staticmethod
    def _snap(raw: Counter) -> dict:
        """A rare template (one-off day) is moved to the nearest frequent one of the same month offset, so the votes do not scatter."""
        frequent = [t for t, n in raw.items() if n >= 3 and t != "asap"]
        out = {}
        for t in raw:
            if t == "asap" or raw[t] >= 3:
                continue
            off, day = (int(x) for x in t.split(":"))
            near = [f for f in frequent if int(f.split(":")[0]) == off and abs(int(f.split(":")[1]) - day) <= 3]
            if near:
                out[t] = min(near, key=lambda f: abs(int(f.split(":")[1]) - day))
        return out

    @property
    def ready(self) -> bool:
        return len(self.h) >= MIN_HISTORY

    def neighbours(self, text: str, doc: str, k: int = K, skip_code: str | None = None) -> list[tuple[float, dict]]:
        tok = _tokens(text)
        v = self._vec(tok)
        nv = math.sqrt(sum(x * x for x in v.values())) or 1.0
        scored = []
        for x in self.h:
            if skip_code and x["code"] == skip_code:
                continue
            s = sum(v.get(w, 0) * y for w, y in x["v"].items()) / (nv * x["norm"]) + (SAME_DOC_BONUS if doc and x["doc"] == doc else 0)
            scored.append((s, x))
        scored.sort(key=lambda t: -t[0])
        return scored[:k]

    def vote(self, text: str, doc: str, skip_code: str | None = None) -> tuple[str, float, int]:
        """(template, share of the vote, how many neighbours agreed)."""
        nb = self.neighbours(text, doc, K, skip_code)
        votes: Counter = Counter()
        for s, x in nb:
            votes[x["tmpl"]] += max(s, 0.01)
        t, w = votes.most_common(1)[0]
        return t, w / sum(votes.values()), sum(1 for _, x in nb if x["tmpl"] == t)


def evaluate(c) -> dict:
    """How often the history alone picks the template the specialist picked (each task is judged by all the others)."""
    m = Model(c)
    if not m.ready:
        return {"history": len(m.h), "accuracy": None}
    ok = sum(1 for x in m.h if m.vote(x["text"], x["doc"], skip_code=x["code"])[0] == x["tmpl"])
    base = m.freq.most_common(1)[0][1] / len(m.h)
    return {"history": len(m.h), "accuracy": round(ok / len(m.h), 3), "always_the_most_common": round(base, 3)}


# ---------------------------------------------------------------- the language model
def ai_config() -> dict:
    key = setting("ai_key").strip() or os.environ.get("OPENAI_API_KEY", "").strip()
    return {"enabled": setting("ai_enabled") == "1" and bool(key), "key": key, "model": setting("ai_model").strip() or DEFAULT_MODEL,
            "base": (setting("ai_base_url").strip() or DEFAULT_BASE).rstrip("/")}


def ai_call(cfg: dict, messages: list[dict], timeout: int = 120) -> dict:
    body = {"model": cfg["model"], "messages": messages, "response_format": {"type": "json_object"}}
    req = urllib.request.Request(cfg["base"] + "/chat/completions", json.dumps(body).encode(),
                                 {"Content-Type": "application/json", "Authorization": "Bearer " + cfg["key"], "User-Agent": "zadachi"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.load(r)
    except urllib.error.HTTPError as e:
        try:
            msg = (json.load(e).get("error") or {}).get("message", "")
        except ValueError:
            msg = ""
        raise AiError(f"ИИ ответил ошибкой {e.code}: {msg[:200]}".replace(cfg["key"], "***")) from None
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise AiError("Нет связи с сервисом ИИ: " + str(getattr(e, "reason", e)).replace(cfg["key"], "***")) from None
    try:
        return json.loads(data["choices"][0]["message"]["content"])
    except (KeyError, IndexError, TypeError, ValueError):
        raise AiError("ИИ вернул ответ не в том виде") from None


def ai_test() -> str:
    cfg = ai_config()
    if not cfg["key"]:
        raise AiError("Ключ не задан")
    out = ai_call(cfg, [{"role": "system", "content": "Ответь JSON {\"ok\": true}"}, {"role": "user", "content": "проверка связи"}], timeout=30)
    return f"Связь есть, модель {cfg['model']} ответила" if out else "Пустой ответ"


SYSTEM = """Ты помогаешь специалисту по контролю исполнения поручений. Для каждого поручения он ставит собственную «дату закрытия»: внутренний срок, раньше официального, чтобы успеть согласовать ответ. Он всегда выбирает один из привычных ШАБЛОНОВ дат (они даны в списке templates вместе с тем, как часто он их выбирал). Выбор зависит от сути поручения и документа: сроки ближе к официальному у поручений, итог которых известен только в конце периода (показатели, проценты), и раньше у организационных действий и поручений, где нужен долгий ответ. Тебе дают новые поручения и для каждого несколько его прошлых решений по похожим поручениям (examples).
Для каждого нового поручения выбери ровно один template из списка (поле id), опираясь на примеры. Не придумывай своих шаблонов и не считай даты сам. Верни только JSON: {"items":[{"code":"...","template":"...","reason":"не больше 12 слов по-русски"}]}."""


def ai_choose(cfg: dict, model: Model, items: list[dict]) -> dict[str, dict]:
    """{code: {template, reason}} for the given tasks; only templates the specialist really uses are accepted."""
    top = [t for t, _ in model.freq.most_common(8)]
    templates = [{"id": t, "meaning": label(t, model.lead), "count": model.freq[t]} for t in top]
    tasks = []
    for it in items:
        ex = [{"due": x["due"].isoformat(), "close": x["close"].isoformat(), "template": x["tmpl"], "text": x["text"][:220]} for _, x in model.neighbours(it["text"], it["doc"], 6)]
        tasks.append({"code": it["code"], "document": it["doc"], "due": it["due"].isoformat(), "text": it["text"][:600], "examples": ex})
    out = ai_call(cfg, [{"role": "system", "content": SYSTEM}, {"role": "user", "content": json.dumps({"today": today().isoformat(), "templates": templates, "tasks": tasks}, ensure_ascii=False)}])
    res = {}
    for r in (out.get("items") or []) if isinstance(out, dict) else []:
        if isinstance(r, dict) and r.get("template") in top and isinstance(r.get("code"), str):
            res[r["code"]] = {"template": r["template"], "reason": str(r.get("reason") or "")[:200]}
    return res


# ---------------------------------------------------------------- proposals
def suggest(ids: list[int] | None = None, redo: bool = False, use_ai: bool = True) -> dict:
    """Closing dates for open tasks that have none (redo: also for those proposed earlier and not yet confirmed). Returns a summary."""
    c = connect()
    try:
        model = Model(c)
        sql = "SELECT id, code, doc_no, text, due FROM tasks WHERE status IN ('todo','progress') AND due IS NOT NULL AND text != ''"
        sql += " AND (close_date IS NULL" + (" OR close_src != ''" if redo else "") + ")"
        args: list = []
        if ids:
            sql += f" AND id IN ({','.join('?' * len(ids))})"
            args += list(ids)
        rows = [dict(r) for r in c.execute(sql + " ORDER BY id LIMIT ?", args + [MAX_PER_RUN])]
    finally:
        c.close()
    summary = {"asked": len(rows), "proposed": 0, "by_ai": 0, "by_history": 0, "history": len(model.h), "errors": [], "templates": [{"id": t, "label": label(t, model.lead), "count": n} for t, n in model.freq.most_common(6)]}
    if not rows:
        return summary
    if not model.ready:
        summary["errors"].append(f"В истории только {len(model.h)} задач с датой закрытия: нужно не меньше {MIN_HISTORY}, иначе подбирать не по чему")
        return summary
    todo = []
    for r in rows:
        due = _d(r["due"])
        t, share, n = model.vote(r["text"], (r["doc_no"] or "").strip(), skip_code=r["code"])
        todo.append({"id": r["id"], "code": r["code"], "doc": (r["doc_no"] or "").strip(), "text": r["text"], "due": due, "tmpl": t, "src": "rule",
                     "note": f"Похожие прежние задачи: {n} из {K} — {label(t, model.lead)}"})
    cfg = ai_config()
    if use_ai and cfg["enabled"]:
        for i in range(0, len(todo), BATCH):
            chunk = todo[i:i + BATCH]
            try:
                got = ai_choose(cfg, model, chunk)
            except AiError as e:
                summary["errors"].append(str(e))
                break                       # no point in knocking again: the rest keeps the answer of the history
            for it in chunk:
                g = got.get(it["code"])
                if g:
                    it.update(tmpl=g["template"], src="ai", note=("ИИ: " + g["reason"] + f" — {label(g['template'], model.lead)}").strip(" —"))
    t0 = today()
    with tx() as c:
        for it in todo:
            d = date_from(it["tmpl"], it["due"], t0, model.lead)
            c.execute("UPDATE tasks SET close_date=?, close_src=?, close_note=?, updated_at=? WHERE id=?", (d.isoformat(), it["src"], it["note"][:300], now(), it["id"]))
            c.execute("INSERT INTO task_events(task_id, user_id, field, old, new, created_at) VALUES (?,?,?,?,?,?)",
                      (it["id"], None, "close_date", "", d.isoformat() + (" (предложено ИИ)" if it["src"] == "ai" else " (по прежним решениям)"), now()))
            summary["proposed"] += 1
            summary["by_ai" if it["src"] == "ai" else "by_history"] += 1
        audit(c, "closing.suggest", "task", None, {"proposed": summary["proposed"], "ai": summary["by_ai"]})
    return summary


def confirm(ids: list[int] | None) -> int:
    with tx() as c:
        if ids:
            n = c.execute(f"UPDATE tasks SET close_src='', close_note='' WHERE close_src != '' AND id IN ({','.join('?' * len(ids))})", ids).rowcount
        else:
            n = c.execute("UPDATE tasks SET close_src='', close_note='' WHERE close_src != ''").rowcount
        audit(c, "closing.confirm", "task", None, {"count": n})
    return n


def settings_view() -> dict:
    key = setting("ai_key").strip()
    return {"enabled": setting("ai_enabled") == "1", "model": setting("ai_model") or DEFAULT_MODEL, "base_url": setting("ai_base_url") or "", "key_set": bool(key or os.environ.get("OPENAI_API_KEY")),
            "key_tail": ("…" + key[-4:]) if len(key) >= 8 else "", "key_from_env": bool(not key and os.environ.get("OPENAI_API_KEY"))}


def save_settings(b: dict) -> None:
    vals = {}
    if "enabled" in b:
        vals["ai_enabled"] = "1" if b["enabled"] else "0"
    if "model" in b:
        m = str(b["model"]).strip()
        if m and not re.fullmatch(r"[A-Za-z0-9._:/-]{1,80}", m):
            raise ValueError("Название модели: латиница, цифры, точка, дефис")
        vals["ai_model"] = m
    if "base_url" in b:
        u = str(b["base_url"]).strip()
        if u and not re.fullmatch(r"https?://[^\s]+", u):
            raise ValueError("Адрес сервиса должен начинаться с https://")
        vals["ai_base_url"] = u
    if b.get("clear_key"):
        vals["ai_key"] = ""
    elif b.get("key"):
        k = str(b["key"]).strip()
        if not re.fullmatch(r"[A-Za-z0-9_\-.]{16,300}", k):
            raise ValueError("Ключ выглядит неверно: латиница, цифры, - и _, от 16 знаков")
        vals["ai_key"] = k
    with tx() as c:
        put_settings(c, vals)
        audit(c, "ai.settings", "settings", None, {k: ("***" if k == "ai_key" and v else v) for k, v in vals.items()})
