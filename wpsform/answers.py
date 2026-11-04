"""Answer values -> submit payload, plus profile persistence and interactive fill."""

from __future__ import annotations

import json
import time
from pathlib import Path

from .schema import Form, Option, Question

PROFILE_DIR = Path("profiles")


class AnswerError(ValueError):
    """A profile value cannot be turned into a valid answer."""


# --------------------------------------------------------------- select ------
def _pick_options(question: Question, value: object) -> list[Option]:
    """Accept an option value, a 1-based index, or a list of either."""
    raw = value if isinstance(value, (list, tuple)) else [value]
    picked: list[Option] = []
    for item in raw:
        if isinstance(item, bool):
            raise AnswerError(f"{question.title}: boolean is not a valid option")
        if isinstance(item, int):
            option = question.option_by_index(item)
        else:
            option = question.option_by_value(str(item))
        if option is None:
            listed = ", ".join(f"{o.index}={o.val}" for o in question.options)
            raise AnswerError(f"{question.title}: {item!r} is not an option; choose {listed}")
        if option not in picked:
            picked.append(option)
    if len(picked) > 1 and question.multi_type != "check":
        raise AnswerError(f"{question.title}: single-select question got {len(picked)} values")
    return picked


def answer_object(question: Question, value: object) -> dict:
    if question.type == "select":
        picked = _pick_options(question, value)
        return {
            "type": "select",
            "selectValue": [
                {"val": o.val, "addedVal": "", "selectId": o.select_id} for o in picked
            ],
        }
    text = "" if value is None else str(value)
    return {"type": question.type, "strValue": text}


# --------------------------------------------------------------- payload -----
def missing_required(form: Form, values: dict[str, object]) -> list[str]:
    return [q.title for q in form.questions if q.required and not values.get(q.title)]


def build_payload(
    form: Form,
    values: dict[str, object],
    *,
    consume_time: int = 8,
) -> dict:
    absent = missing_required(form, values)
    if absent:
        raise AnswerError("missing required answers: " + ", ".join(absent))

    answers: dict[str, dict] = {}
    for question in form.questions:
        value = values.get(question.title)
        if value in (None, "", []):
            continue
        answers[question.qid] = answer_object(question, value)

    return {
        "answerJson": {"answers": answers, "consumeTime": max(1, int(consume_time))},
        "phoneNumber": "",
        "editVersion": form.edit_version,
        "token": form.token,
        "_t": int(time.time() * 1000),
    }


# --------------------------------------------------------------- profile -----
def profile_path(share_id: str) -> Path:
    return PROFILE_DIR / f"{share_id}.json"


def load_profile(share_id: str, path: Path | None = None) -> dict[str, object]:
    path = path or profile_path(share_id)
    if not path.exists():
        raise AnswerError(f"no profile at {path}; run `fill` first or pass --values")
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("values", data)


def save_profile(share_id: str, values: dict[str, object], path: Path | None = None) -> Path:
    path = path or profile_path(share_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"shareId": share_id, "values": values}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


# ------------------------------------------------------------------ fill -----
def interactive_fill(form: Form, preset: dict[str, object] | None = None) -> dict[str, object]:
    """Prompt field by field, keeping existing values as the default."""
    values: dict[str, object] = dict(preset or {})
    for question in form.questions:
        current = values.get(question.title)
        hint = f" [{current}]" if current not in (None, "") else ""
        suffix = "" if question.required else " (optional)"
        print()

        if question.options:
            print(f"{question.title}  ({question.kind}{suffix})")
            for option in question.options:
                print(f"  {option.index:>2}. {option.val}")
            prompt = (
                f"{question.title} 1-based index"
                if question.multi_type != "check"
                else f"{question.title} indices, comma separated"
            )
            raw = input(f"{prompt}{hint}: ").strip()
            if not raw:
                if question.required and current in (None, ""):
                    raise AnswerError(f"{question.title} is required")
                continue
            if question.multi_type == "check":
                values[question.title] = [int(part) for part in raw.replace("，", ",").split(",") if part.strip()]
            else:
                values[question.title] = int(raw)
            continue

        raw = input(f"{question.title}{hint}: ").strip()
        if not raw:
            if question.required and current in (None, ""):
                raise AnswerError(f"{question.title} is required")
            continue
        values[question.title] = raw
    return values