"""Turn the raw ``campaign`` payload into an ordered, printable form model."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(slots=True)
class Option:
    index: int  # 1-based, matches what the CLI asks for
    val: str
    select_id: str


@dataclass(slots=True)
class Question:
    qid: str
    title: str
    type: str
    required: bool
    options: list[Option] = field(default_factory=list)
    multi_type: str = ""  # "radio" / "check" for select questions

    @property
    def kind(self) -> str:
        if self.type == "select":
            return "multi-select" if self.multi_type == "check" else "single-select"
        if self.type == "telphone":
            return "phone"
        return self.type

    def option_by_value(self, val: str) -> Option | None:
        return next((o for o in self.options if o.val == val), None)

    def option_by_index(self, index: int) -> Option | None:
        return next((o for o in self.options if o.index == index), None)


@dataclass(slots=True)
class Form:
    share_id: str
    title: str
    start_ts: int
    stop_ts: int
    quota: int
    submitted: int
    token: str
    edit_version: int
    check_login: bool
    check_once: bool
    need_period: bool
    questions: list[Question]

    def question(self, title: str) -> Question | None:
        return next((q for q in self.questions if q.title == title), None)

    @property
    def start_local(self) -> str:
        return datetime.fromtimestamp(self.start_ts / 1000).strftime("%Y-%m-%d %H:%M:%S")


def parse_campaign(share_id: str, data: dict) -> Form:
    base = (data.get("setting") or {}).get("baseSetting") or {}
    question_map: dict[str, dict] = data.get("questionMap") or {}

    questions: dict[str, Question] = {}
    for qid, raw in question_map.items():
        if (raw.get("baseInfo") or {}).get("delete"):
            continue
        qtype = raw.get("type", "input")
        options: list[Option] = []
        if qtype == "select":
            selects = ((raw.get("selectInfo") or {}).get("selects")) or []
            options = [
                Option(index=i + 1, val=str(o.get("val", "")), select_id=str(o.get("selectId", "")))
                for i, o in enumerate(selects)
            ]
        questions[qid] = Question(
            qid=qid,
            title=str(raw.get("title", qid)),
            type=qtype,
            required=bool((raw.get("baseInfo") or {}).get("need")),
            options=options,
            multi_type=str((raw.get("selectInfo") or {}).get("multiType", "")),
        )

    # questionLayouts keeps the visual order; anything missing trails behind it
    ordered: list[Question] = []
    for item in data.get("questionLayouts") or []:
        if item.get("type") != "question":
            continue
        qid = item.get("id")
        if qid in questions and questions[qid] not in ordered:
            ordered.append(questions[qid])
    ordered.extend(q for q in questions.values() if q not in ordered)

    return Form(
        share_id=share_id,
        title=str(data.get("name", "")),
        start_ts=int(base.get("startTime") or 0),
        stop_ts=int(base.get("stopTime") or 0),
        quota=int(base.get("fillLimit") or 0),
        submitted=int(data.get("count") or 0),
        token=str(data.get("token") or ""),
        edit_version=int(data.get("editVersion") or 1),
        check_login=bool(base.get("checkLogin")),
        check_once=bool(base.get("checkOnce")),
        need_period=bool((base.get("periodConfig") or {}).get("checkPeriod")),
        questions=ordered,
    )