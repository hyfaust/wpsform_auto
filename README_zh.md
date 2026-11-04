# wpsform_auto

[English](README.md) | [简体中文](README_zh.md)

---

> **免责声明** — 此项目主要用于学习、交流，不可用于损害他人利益，请勿用于非法用途。

[![Version](https://img.shields.io/badge/version-1.0.0-green.svg)](wpsform/__init__.py)
[![Python](https://img.shields.io/badge/python-%3E%3D3.10-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-GPL--3.0-blue.svg)](LICENSE)

> 端到端自动化 WPS 表单：提取表单结构、预填写答案，并按服务器时间精确提交。

## 项目简介

WPS 表单（`f.wps.cn` / `f.kdocs.cn`）使用广泛，但没有公开的答案提交接口，也无法在表单开放前预先准备答案。`wpsform_auto` 调用与官方网页端相同的 HTTP 接口，因此可以：

- **提取**：不打开浏览器就能拿到字段列表、选项序号、名额、开放时间，以及是否需要登录；
- **预填**：交互式或从 JSON 文件录入一次答案，之后重复使用；
- **提交**：在表单开放的精确时刻提交预置答案，时间基准是服务器时钟而非本机时钟。

提交流程按失败可恢复设计：开始前一分钟重新拉取表单以刷新 `token`，服务器仍返回「尚未开始」时每 50 ms 重试一次，命中「名额已满」「已提交过」等终止码立即停止。

## 目录

- [项目简介](#项目简介)
- [功能特性](#功能特性)
- [环境依赖](#环境依赖)
- [安装](#安装)
- [使用](#使用)
- [命令参考](#命令参考)
- [Profile 格式](#profile-格式)
- [提交策略](#提交策略)
- [配置项](#配置项)
- [项目结构](#项目结构)
- [验证](#验证)
- [协议说明](#协议说明)
- [限制](#限制)
- [许可证](#许可证)
- [致谢](#致谢)

## 功能特性

| 能力 | 说明 |
|---|---|
| 结构提取 | 解析题目、必填标记、题型，以及每个选项从 1 开始的序号 |
| 按标题映射 | 答案以题目标题为键，`qid` 变化不会让已保存的 profile 失效 |
| 选项解析 | 支持选项名称、从 1 开始的序号，多选题目支持数组 |
| 时钟对齐 | 三次 `/time` 采样取中位偏移，自动补偿偏差数秒的本机时钟 |
| 提交前刷新 | 起爆前 60 秒重新拉取表单，保证 `token` 与 `startTime` 是最新的 |
| 终止码处理 | 遇到「需要登录」「已关闭」「名额已满」直接停止，不做无谓请求 |
| 可选加密 | 默认明文 JSON；`--encrypt` 复刻网页端的 AES-128-OFB 传输 |
| 试运行 | `--dry-run` 只发一次并打印服务端返回，表单开放前可反复执行 |

## 环境依赖

| 依赖 | 版本 | 是否必需 |
|---|---|---|
| Python | >= 3.10 | 是 |
| `requests` | >= 2.22 | 是 |
| `pycryptodome` | >= 3.9 | 仅 `--encrypt` 需要 |

不需要浏览器、WebDriver 或安装 WPS 客户端。

## 安装

```bash
git clone <repository-url> wpsform_auto
cd wpsform_auto
pip install -r requirements.txt
```

在项目根目录以模块方式运行，或使用 `main.py` 入口：

```bash
python -m wpsform --help
python main.py --help
```

## 使用

### 1. 提取表单信息

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

加 `--json` 可输出机器可读的结构。

### 2. 预填写答案

交互式：每道题提示一次，展示选项序号，最后保存 profile：

```bash
python -m wpsform fill https://f.wps.cn/g/EXAMPLE01/
```

非交互式：从 JSON 导入并只做校验，不提问：

```bash
python -m wpsform fill https://f.wps.cn/g/EXAMPLE01/ --values answers.json --no-prompt
```

非法值会在写入任何文件之前直接报错，并列出全部合法选项：

```text
error: Team: 99 is not an option; choose 1=Team A, 2=Team B, 3=Team C
```

### 3. 到点提交

```bash
python -m wpsform run https://f.wps.cn/g/EXAMPLE01/
```

执行顺序：

1. 三次采样 `GET /time`，取中位数得到服务器与本机的时钟偏移；
2. 目标时刻前 60 秒重新拉取表单，刷新 `token` 与 `startTime`；
3. 再次对齐时钟，自旋等待服务器时间到达目标时刻；
4. 每 50 ms 请求一次 `POST /campaign/{shareId}`，直到被接受或返回终止码。

常用变体：

```bash
# 只发一次并打印返回，表单开放前可安全执行
python -m wpsform run https://f.wps.cn/g/EXAMPLE01/ --dry-run

# 覆盖目标时间，例如用于演练
python -m wpsform run https://f.wps.cn/g/EXAMPLE01/ --at 09:00:00

# 不等待，立即开始
python -m wpsform run https://f.wps.cn/g/EXAMPLE01/ --now

# 限制尝试次数
python -m wpsform run https://f.wps.cn/g/EXAMPLE01/ --max-attempts 20
```

输出示例：

```text
form     Sample signup form (EXAMPLE01)
target   2026-01-01 09:00:00
answers  {"Name": "Jane Doe", "Student ID": "0000001", "Team": 2, "Contact": "10000000000"}
server clock offset -2.840s, target in 3.40s
[1] HTTP 403 code=13018 表单尚未开始填写 (181 ms)
```

## 命令参考

| 命令 | 说明 |
|---|---|
| `inspect <url\|id>` | 打印表单结构；`--json` 输出原始模型 |
| `fill <url\|id>` | 交互式预填并保存到 `profiles/<shareId>.json`；`--values x.json` 预置值；`--no-prompt` 只校验不提问 |
| `run <url\|id>` | 等待目标时刻并提交；支持 `--at`、`--now`、`--dry-run`、`--workers N`、`--max-attempts N` |
| `--cookie` / `WPS_SID` | `wps_sid` Cookie，仅在表单要求登录时需要 |
| `--encrypt` | 按网页端方式对请求体 AES-128-OFB 加密、对响应解密 |
| `--profile PATH` | 从自定义路径读取或写入 profile |

`target` 参数既接受完整分享链接（`https://f.wps.cn/g/<shareId>`），也接受裸 share id。

## Profile 格式

`profiles/<shareId>.json` 把题目标题映射到答案值。值可以是文本、从 1 开始的选项序号，或选项名称；多选题用数组：

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

必填项缺失、标题不存在、选项序号非法，都会在任何网络写入之前被拒绝。

## 提交策略

| 返回码 | 含义 | 处理 |
|---|---|---|
| `0` | 提交成功 | 立即退出 |
| `13018` | 表单尚未开始 | 每 50 ms 重试 |
| `10002` | 需要登录 | 停止并提示缺少 `WPS_SID` |
| `13015` | 表单已关闭 / 已提交过 | 停止 |
| `11001` | 名额已满 / 不允许提交 | 停止 |
| 其他 | 未知 | 每 100 ms 重试，日志保留原始返回 |

默认单线程。并发会拉长每次请求的往返时间（实测 2 线程时单次接近 3 s），并提高被限流的概率，因此不建议把 `--workers` 调到 2 以上。

## 配置项

| 配置 | 默认值 | 作用 |
|---|---|---|
| `WPS_SID` 环境变量 | 空 | 需要登录的表单所用的 `wps_sid` Cookie；`--cookie` 优先 |
| `--encrypt` | 关闭 | 与网页端一致地加密请求体、解密响应 |
| `--workers N` | `1` | 并发提交线程数 |
| `--max-attempts N` | `0`（不限） | 提交尝试次数上限 |
| `--profile PATH` | `profiles/<shareId>.json` | profile 存放路径 |

## 项目结构

```text
wpsform_auto/
├── main.py              # 脚本式入口
├── requirements.txt     # requests；pycryptodome（可选）
├── README.md            # 英文说明
├── README_zh.md         # 简体中文说明（本文件）
└── wpsform/
    ├── __init__.py      # 包版本
    ├── __main__.py      # `python -m wpsform` 入口
    ├── api.py           # HTTP 客户端：config、campaign、time、submit
    ├── schema.py        # campaign 返回值 -> Form / Question / Option
    ├── answers.py       # 值归一化、payload 组装、profile、交互提问
    ├── scheduler.py     # 时钟同步、wait_until、提交重试循环
    ├── crypto.py        # AES-128-OFB 辅助函数（可选）
    └── cli.py           # inspect / fill / run 子命令
```

## 验证

项目没有自动化测试套件，最快的端到端检查是试运行，它会走完结构解析、答案组装，并真实发起一次提交：

```bash
python -m wpsform inspect <url> --json | head -5
python -m wpsform run <url> --dry-run
python -m wpsform run <url> --dry-run --encrypt
```

表单尚未开放时会返回 `HTTP 403 code=13018`，说明整条请求链路可用。也可以用未来的几秒做定时演练，不必等待真实开放时间：

```bash
# 5 秒后开火，最多尝试 4 次
python -m wpsform run <url> --at "$(date -d '+5 sec' +%H:%M:%S)" --max-attempts 4
```

## 协议说明

| 用途 | 请求 |
|---|---|
| 服务配置（含 `encrypt.aes_key`） | `GET /ksform/api/v3/config` |
| 表单结构、`token`、起止时间 | `GET /ksform/api/v3/campaign/{shareId}` |
| 权威服务器时钟（毫秒） | `GET /ksform/api/v3/time` |
| 创建一条答案 | `POST /ksform/api/v3/campaign/{shareId}` |

请求体：

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

除非请求头带 `x-encrypt-alg: aes-128-ofb`，报文始终是明文；只有带这个头时，响应才会用 `x-encrypt-iv` 加密。默认路径因此完全不需要加密库。

## 限制

- 分享链接必须是 `/g/{shareId}` 形式；小程序码与二维码需要先转换。
- 时间以服务器时钟为准，本机偏差数秒会被自动补偿。
- 带图形验证码、每日时段限制，或使用预置名额（座位）机制的表单不在支持范围内。
- 本工具直接调用网页端的私有接口，属于约定之外的使用方式：提交可能被判定异常、作废，或导致账号受限。请自行评估风险，并只在允许自动提交的场景使用。

## 许可证

GNU General Public License v3.0，完整条款见 [LICENSE](LICENSE)。

## 致谢

- 请求结构与字段类型依据公开的 WPS 表单网页端还原，并在真实接口上逐项验证。
- 基于 [`requests`](https://requests.readthedocs.io/) 与 [`pycryptodome`](https://www.pycryptodome.org/) 构建。
