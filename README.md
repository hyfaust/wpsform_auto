# wpsform_auto

[English](README.md) | [简体中文](README_zh.md)

---

> **Disclaimer** — This project is intended for learning and research only. Do not use it to harm others' interests, and do not use it for any illegal purpose.

[![Version](https://img.shields.io/badge/version-1.0.0-green.svg)](wpsform/__init__.py)
[![Python](https://img.shields.io/badge/python-%3E%3D3.10-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-GPL--3.0-blue.svg)](LICENSE)

> Automate WPS Forms end to end: extract the form schema, pre-fill answers, and submit at a precise server-synchronized time.

## Introduction

WPS Forms (`f.wps.cn` / `f.kdocs.cn`) is a widely used form service, but it has no public answer-submission API and no way to prepare an answer before a form opens. `wpsform_auto` drives the same HTTP endpoints the official web client uses, so you can:

- **Inspect** a form without opening a browser — fields, option indices, quota, open time, and whether login is required;
- **Pre-fill** answers once, interactively or from a JSON file, and reuse them later;
- **Submit** the prepared answer at the exact moment the form opens, aligned to the server clock rather than the local one.

The submit path is resilient by design: it refreshes the form token one minute before the start time, retries every 50 ms while the server still reports "not started", and stops immediately on terminal codes such as "quota exhausted" or "already answered".

## Table of Contents

- [Introduction](#introduction)
- [Features](#features)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Usage](#usage)
- [Commands](#commands)
- [Profile Format](#profile-format)
- [Submission Strategy](#submission-strategy)
- [Configuration](#configuration)
- [Project Structure](#project-structure)
- [Verification](#verification)
- [Protocol Notes](#protocol-notes)
- [Limitations](#limitations)
- [License](#license)
- [Acknowledgments](#acknowledgments)

## Features

| Capability | Detail |
|---|---|
| Schema extraction | Resolves questions, required flags, question types, and every select option with a 1-based index |
| Title-based mapping | Answers are keyed by question title, so `qid` changes never break a saved profile |
| Option resolution | Accepts an option value, a 1-based index, or a list for multi-select questions |
| Clock alignment | Three `/time` samples, median offset, compensation for a local clock that is seconds off |
| Late token refresh | Reloads the form 60 seconds before firing so `token` and `startTime` are current |
| Terminal-code handling | Stops on login-required, closed, and quota-exhausted replies instead of burning requests |
| Optional encryption | Plain JSON by default; `--encrypt` mirrors the web client's AES-128-OFB transport |
| Dry run | `--dry-run` performs a single attempt and prints the server reply, safe to repeat before the form opens |

## Prerequisites

| Dependency | Version | Required |
|---|---|---|
| Python | >= 3.10 | Yes |
| `requests` | >= 2.22 | Yes |
| `pycryptodome` | >= 3.9 | Only for `--encrypt` |

No browser, WebDriver, or WPS client installation is needed.

## Installation

```bash
git clone <repository-url> wpsform_auto
cd wpsform_auto
pip install -r requirements.txt
```

Run it as a module from the project root, or via the `main.py` entry point:

```bash
python -m wpsform --help
python main.py --help
```

## Usage

### 1. Inspect the form

```bash
python -m wpsform inspect https://f.wps.cn/g/EXAMPLE01/
```

```text
title      Sample signup form
share id   EXAMPLE01
opens      2026-01-01 09:00:00
quota      200   submitted 0
login      anonymous ok   repeat allowed
version    1   token EXAMPLE_TOKEN
fields
  1. Name  [input, required, qid=q_name]
  2. Student ID  [input, required, qid=q_id]
  3. Team  [single-select, required, qid=q_team]
         1. Team A
         2. Team B
         3. Team C
  4. Contact  [phone, required, qid=q_phone]
```

Add `--json` for a machine-readable model.

### 2. Pre-fill answers

Interactive — prompts once per field, showing option indices, then saves a profile:

```bash
python -m wpsform fill https://f.wps.cn/g/EXAMPLE01/
```

Non-interactive — import values from JSON and validate without prompting:

```bash
python -m wpsform fill https://f.wps.cn/g/EXAMPLE01/ --values answers.json --no-prompt
```

Invalid values fail immediately with the full set of legal options, before anything is saved:

```text
error: Team: 99 is not an option; choose 1=Team A, 2=Team B, 3=Team C
```

### 3. Submit at the configured time

```bash
python -m wpsform run https://f.wps.cn/g/EXAMPLE01/
```

Execution order:

1. Sample `GET /time` three times and take the median server/local offset;
2. Reload the form 60 seconds before the target to refresh `token` and `startTime`;
3. Re-sync the clock and spin until the server reaches the target timestamp;
4. `POST /campaign/{shareId}` every 50 ms until accepted or a terminal code is returned.

Useful variants:

```bash
# single attempt, print the reply (safe before the form opens)
python -m wpsform run https://f.wps.cn/g/EXAMPLE01/ --dry-run

# override the target time, e.g. for testing
python -m wpsform run https://f.wps.cn/g/EXAMPLE01/ --at 09:00:00

# start immediately instead of waiting
python -m wpsform run https://f.wps.cn/g/EXAMPLE01/ --now

# bound the number of attempts
python -m wpsform run https://f.wps.cn/g/EXAMPLE01/ --max-attempts 20
```

Sample output:

```text
form     Sample signup form (EXAMPLE01)
target   2026-01-01 09:00:00
answers  {"Name": "Jane Doe", "Student ID": "0000001", "Team": 2, "Contact": "10000000000"}
server clock offset -2.840s, target in 3.40s
[1] HTTP 403 code=13018 表单尚未开始填写 (181 ms)
```

## Commands

| Command | Description |
|---|---|
| `inspect <url\|id>` | Print the form schema; `--json` emits the raw model |
| `fill <url\|id>` | Interactive pre-fill saved to `profiles/<shareId>.json`; `--values x.json` presets values; `--no-prompt` validates without asking |
| `run <url\|id>` | Wait for the target and submit; `--at`, `--now`, `--dry-run`, `--workers N`, `--max-attempts N` |
| `--cookie` / `WPS_SID` | `wps_sid` cookie, needed only when the form requires login |
| `--encrypt` | AES-128-OFB request/response bodies, matching the web client |
| `--profile PATH` | Read or write a profile at a custom location |

The `target` argument accepts a full share URL (`https://f.wps.cn/g/<shareId>`) or a bare share id.

## Profile Format

`profiles/<shareId>.json` maps question titles to values. A value may be text, a 1-based option index, or an option value; multi-select questions take a list:

```json
{
  "shareId": "EXAMPLE01",
  "values": {
    "Name": "Jane Doe",
    "Student ID": "0000001",
    "Team": 2,
    "Contact": "10000000000"
  }
}
```

```json
{
  "values": {
    "Name": "Jane Doe",
    "Team": ["Team A", "Team C"]
  }
}
```

Missing required answers, unknown titles, and invalid option indices are rejected before any network write happens.

## Submission Strategy

| Reply code | Meaning | Handling |
|---|---|---|
| `0` | Accepted | Exit immediately |
| `13018` | Form not open yet | Retry every 50 ms |
| `10002` | Login required | Stop and report that `WPS_SID` is missing |
| `13015` | Form closed / already answered | Stop |
| `11001` | Quota exhausted / rejected | Stop |
| Other | Unknown | Retry every 100 ms, keep the raw reply in the log |

The default is a single worker. Concurrency lengthens round-trip times (a measured two-worker run peaked near 3 s per request) and increases the chance of rate limiting, so `--workers` above 2 is not recommended.

## Configuration

| Setting | Default | Purpose |
|---|---|---|
| `WPS_SID` environment variable | empty | `wps_sid` cookie for forms that require login; `--cookie` overrides it |
| `--encrypt` | off | Encrypt request bodies and decrypt responses like the web client |
| `--workers N` | `1` | Parallel submit threads |
| `--max-attempts N` | `0` (unlimited) | Upper bound on submit attempts |
| `--profile PATH` | `profiles/<shareId>.json` | Profile location |

## Project Structure

```text
wpsform_auto/
├── main.py              # Script-style entry point
├── requirements.txt     # requests; pycryptodome (optional)
├── README.md            # This file (English)
├── README_zh.md         # Simplified Chinese translation
└── wpsform/
    ├── __init__.py      # Package version
    ├── __main__.py      # `python -m wpsform` entry
    ├── api.py           # HTTP client: config, campaign, time, submit
    ├── schema.py        # campaign payload -> Form / Question / Option
    ├── answers.py       # Value normalization, payload building, profiles, prompts
    ├── scheduler.py     # Clock sync, wait_until, submit retry loop
    ├── crypto.py        # AES-128-OFB helpers (optional)
    └── cli.py           # inspect / fill / run subcommands
```

## Verification

There is no automated test suite; the fastest end-to-end check is a dry run, which exercises schema parsing, answer building, and one real submission attempt:

```bash
python -m wpsform inspect <url> --json | head -5
python -m wpsform run <url> --dry-run
python -m wpsform run <url> --dry-run --encrypt
```

A form that has not opened yet answers `HTTP 403 code=13018`, which confirms the whole request chain works. A scheduled run can be rehearsed without waiting for the real start time:

```bash
# fires 5 seconds from now, gives up after 4 attempts
python -m wpsform run <url> --at "$(date -d '+5 sec' +%H:%M:%S)" --max-attempts 4
```

## Protocol Notes

| Purpose | Request |
|---|---|
| Service config (includes `encrypt.aes_key`) | `GET /ksform/api/v3/config` |
| Form schema, `token`, open/close time | `GET /ksform/api/v3/campaign/{shareId}` |
| Authoritative server clock (ms) | `GET /ksform/api/v3/time` |
| Create one answer | `POST /ksform/api/v3/campaign/{shareId}` |

Request body:

```json
{
  "answerJson": {
    "answers": {
      "qid": {"type": "input", "strValue": "..."},
      "qid2": {"type": "select", "selectValue": [{"val": "...", "addedVal": "", "selectId": "..."}]}
    },
    "consumeTime": 8
  },
  "phoneNumber": "",
  "editVersion": 1,
  "token": "...",
  "_t": 1767225600000
}
```

Bodies stay plaintext unless the request carries `x-encrypt-alg: aes-128-ofb`; only then does the response arrive encrypted with an `x-encrypt-iv` header. That is why the default path needs no cryptography at all.

## Limitations

- Share links must be in the `/g/{shareId}` form; mini-program and QR codes have to be converted first.
- Timing follows the server clock; local drift of several seconds is compensated automatically.
- Forms protected by a CAPTCHA, a per-day time window, or a preset-key (seat) mechanism are not handled.
- The tool calls private endpoints of the web client. That is use outside the published contract: answers may be flagged, voided, or the account restricted. Evaluate the risk before relying on it, and only use it where automatic submission is permitted.

## License

GNU General Public License v3.0. See [LICENSE](LICENSE) for the full text.

## Acknowledgments

- The request shapes and field types were reconstructed from the public WPS Forms web client and verified against live endpoints.
- Built on [`requests`](https://requests.readthedocs.io/) and [`pycryptodome`](https://www.pycryptodome.org/).
