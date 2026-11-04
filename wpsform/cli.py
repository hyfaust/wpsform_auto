"""Command line interface: inspect / fill / run."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import asdict
import time
from datetime import datetime
from pathlib import Path

from . import answers as answers_mod
from . import scheduler
from .api import Api, ApiError
from .crypto import CryptoUnavailable
from .schema import Form, parse_campaign

SHARE_RE = re.compile(r"/(?:g|w/write)/([A-Za-z0-9]+)")


def _share_id(raw: str) -> str:
    match = SHARE_RE.search(raw)
    if match:
        return match.group(1)
    if re.fullmatch(r"[A-Za-z0-9]{6,20}", raw):
        return raw
    raise SystemExit(f"cannot find a share id in {raw!r}")


def _api(args: argparse.Namespace) -> Api:
    cookie = args.cookie or os.environ.get("WPS_SID", "")
    return Api(cookie=cookie, encrypt=args.encrypt)


def _load_form(api: Api, share_id: str) -> Form:
    return parse_campaign(share_id, api.campaign(share_id))


def _print_form(form: Form) -> None:
    print(f"title      {form.title}")
    print(f"share id   {form.share_id}")
    print(f"opens      {form.start_local}")
    if form.stop_ts:
        print(f"closes     {datetime.fromtimestamp(form.stop_ts / 1000):%Y-%m-%d %H:%M:%S}")
    print(f"quota      {form.quota or 'unlimited'}   submitted {form.submitted}")
    print(f"login      {'required' if form.check_login else 'anonymous ok'}"
          f"   repeat {'blocked' if form.check_once else 'allowed'}")
    print(f"version    {form.edit_version}   token {form.token}")
    print("fields")
    for idx, question in enumerate(form.questions, 1):
        need = "required" if question.required else "optional"
        print(f"  {idx}. {question.title}  [{question.kind}, {need}, qid={question.qid}]")
        for option in question.options:
            print(f"       {option.index:>2}. {option.val}")


def _values_from_args(raw: str | None) -> dict:
    if not raw:
        return {}
    path = Path(raw)
    if not path.exists():
        raise SystemExit(f"no such file: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("values", data)


def cmd_inspect(args: argparse.Namespace) -> int:
    share_id = _share_id(args.target)
    form = _load_form(_api(args), share_id)
    if args.json:
        print(json.dumps(asdict(form), ensure_ascii=False, indent=2, default=str))
        return 0
    _print_form(form)
    return 0


def cmd_fill(args: argparse.Namespace) -> int:
    share_id = _share_id(args.target)
    api = _api(args)
    form = _load_form(api, share_id)
    preset = _values_from_args(args.values)

    values = preset
    if not args.no_prompt:
        try:
            values = answers_mod.interactive_fill(form, preset)
        except answers_mod.AnswerError as exc:
            raise SystemExit(str(exc)) from exc

    payload = answers_mod.build_payload(form, values)  # validate before saving
    path = answers_mod.save_profile(share_id, values, Path(args.profile) if args.profile else None)
    print()
    print(f"saved {len(payload['answerJson']['answers'])} answers -> {path}")
    return 0


def _target_time(form: Form, at: str | None) -> int:
    if not at:
        return form.start_ts
    text = at.strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%H:%M:%S", "%H:%M"):
        try:
            parsed = datetime.strptime(text, fmt)
        except ValueError:
            continue
        if fmt.startswith("%H"):
            now = datetime.now()
            parsed = parsed.replace(year=now.year, month=now.month, day=now.day)
        return int(parsed.timestamp() * 1000)
    raise SystemExit(f"cannot parse --at {at!r}; use 'YYYY-MM-DD HH:MM:SS' or 'HH:MM:SS'")


def cmd_run(args: argparse.Namespace) -> int:
    share_id = _share_id(args.target)
    api = _api(args)
    form = _load_form(api, share_id)

    if args.values:
        values = _values_from_args(args.values)
    else:
        values = answers_mod.load_profile(share_id, Path(args.profile) if args.profile else None)
    missing = answers_mod.missing_required(form, values)
    if missing:
        raise SystemExit("profile is missing: " + ", ".join(missing))

    answers_mod.build_payload(form, values)  # fail fast on bad option values
    target = _target_time(form, args.at)
    print(f"form     {form.title} ({share_id})")
    print(f"target   {datetime.fromtimestamp(target / 1000):%Y-%m-%d %H:%M:%S}")
    print(f"answers  {json.dumps(values, ensure_ascii=False)}")

    if args.dry_run:
        reply = scheduler.attempt_once(api, form, values, time.time())
        print(f"dry run  {reply}")
        return 0 if reply.code == scheduler.SUCCESS else 2

    if not args.now:
        # refresh token/start time one minute before firing, then align precisely
        scheduler.wait_until(api, target - 60_000)
        form = _load_form(api, share_id)
        if not args.at:
            target = form.start_ts
        answers_mod.build_payload(form, values)
        scheduler.wait_until(api, target)

    reply = scheduler.run(
        api,
        form,
        values,
        workers=args.workers,
        max_attempts=args.max_attempts,
    )
    if reply is None:
        print("no successful submission")
        return 1
    print("SUBMITTED")
    return 0


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("target", help="form URL (https://f.wps.cn/g/XXXX) or bare share id")
    common.add_argument("--cookie", default="", help="wps_sid cookie (or WPS_SID env var)")
    common.add_argument("--encrypt", action="store_true", help="AES-128-OFB like the web client")

    parser = argparse.ArgumentParser(prog="wpsform", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_inspect = sub.add_parser("inspect", parents=[common], help="extract form schema")
    p_inspect.add_argument("--json", action="store_true", help="dump raw model")
    p_inspect.set_defaults(func=cmd_inspect)

    p_fill = sub.add_parser("fill", parents=[common], help="fill answers and save a profile")
    p_fill.add_argument("--values", help="JSON file with preset values")
    p_fill.add_argument("--profile", help="profile path (default profiles/<shareId>.json)")
    p_fill.add_argument("--no-prompt", action="store_true", help="save --values as-is")
    p_fill.set_defaults(func=cmd_fill)

    p_run = sub.add_parser("run", parents=[common], help="submit at the form start time")
    p_run.add_argument("--values", help="JSON file overriding the saved profile")
    p_run.add_argument("--profile", help="profile path (default profiles/<shareId>.json)")
    p_run.add_argument("--at", help="override target time, e.g. '19:00:00'")
    p_run.add_argument("--now", action="store_true", help="skip the wait")
    p_run.add_argument("--dry-run", action="store_true", help="single attempt, no waiting")
    p_run.add_argument("--workers", type=int, default=1, help="parallel submitters (default 1)")
    p_run.add_argument("--max-attempts", type=int, default=0, help="0 = keep trying")
    p_run.set_defaults(func=cmd_run)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except (ApiError, answers_mod.AnswerError, CryptoUnavailable) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:  # closed stdout (e.g. `| head`) on Windows raises EINVAL
        if exc.errno in (22, 32):
            return 0
        raise
    except KeyboardInterrupt:
        return 130