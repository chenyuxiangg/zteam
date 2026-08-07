#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""zbot 职责注入/移除（req-review 流水线的一部分）。

install   : 读 roles/bot.md → 写入 ~/.hermes/gateway.json 的
            platforms.telegram.channel_overrides[<chat_id>].system_prompt
uninstall : 精确移除该键；空壳自动清理；gateway.json 只剩本配置时删除文件。

为什么用 gateway.json 而不用 config.yaml：
- config.yaml 有大量注释，hermes config set / pyyaml 重写会丢注释（实测 36→0）；
- gateway.json 是 Hermes 官方 legacy 配置（JSON 读写无损），优先级低于 config.yaml，
  当 config.yaml 没有 platforms 段时生效（本机现状），即"最小侵入"。

chat_id 来源：TELEGRAM_HOME_CHANNEL 环境变量 > ~/.hermes/.env 解析 > 默认 6525650097。
幂等：重复 install 覆盖为最新 roles/bot.md 内容；重复 uninstall 无副作用。
"""
import json
import os
import sys

WORKSPACE = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
BOT_ROLE_FILE = os.path.join(WORKSPACE, "roles", "bot.md")
HERMES_HOME = os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes"))
GW_JSON = os.path.join(HERMES_HOME, "gateway.json")
DEFAULT_CHAT_ID = "6525650097"


def _chat_id() -> str:
    """解析目标 chat_id：env > .env > 默认。"""
    val = os.environ.get("TELEGRAM_HOME_CHANNEL", "").strip()
    if not val:
        env_file = os.path.join(HERMES_HOME, ".env")
        try:
            for line in open(env_file, encoding="utf-8"):
                line = line.strip()
                if line.startswith("TELEGRAM_HOME_CHANNEL="):
                    val = line.split("=", 1)[1].strip()
                    break
        except OSError:
            pass
    return val or DEFAULT_CHAT_ID


def _load_gw() -> dict:
    if os.path.exists(GW_JSON):
        try:
            with open(GW_JSON, encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save_gw(data: dict) -> None:
    with open(GW_JSON, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def cmd_install() -> int:
    if not os.path.exists(BOT_ROLE_FILE):
        print(f"[bot-config] 错误: 未找到 {BOT_ROLE_FILE}", file=sys.stderr)
        return 1
    chat_id = _chat_id()
    with open(BOT_ROLE_FILE, encoding="utf-8") as f:
        prompt = f.read().strip()
    data = _load_gw()
    platforms = data.setdefault("platforms", {})
    telegram = platforms.setdefault("telegram", {})
    overrides = telegram.setdefault("channel_overrides", {})
    overrides[chat_id] = {"system_prompt": prompt}
    _save_gw(data)
    print(f"[bot-config] zbot 职责已注入 gateway.json（chat_id={chat_id}，{len(prompt)} 字符）")
    print(f"[bot-config] 重启 gateway 生效: systemctl --user restart hermes-gateway")
    return 0


def cmd_uninstall() -> int:
    chat_id = _chat_id()
    data = _load_gw()
    if not data:
        print("[bot-config] gateway.json 不存在或为空，无需清理")
        return 0
    platforms = data.get("platforms", {})
    telegram = platforms.get("telegram", {}) if isinstance(platforms, dict) else {}
    overrides = telegram.get("channel_overrides", {}) if isinstance(telegram, dict) else {}
    if isinstance(overrides, dict) and chat_id in overrides:
        del overrides[chat_id]
        print(f"[bot-config] 已移除 zbot 职责配置（chat_id={chat_id}）")
    else:
        print(f"[bot-config] 未找到 zbot 职责配置（chat_id={chat_id}），无需清理")
    # 清理空壳
    if isinstance(overrides, dict) and not overrides and isinstance(telegram, dict):
        telegram.pop("channel_overrides", None)
    if isinstance(telegram, dict) and not telegram and isinstance(platforms, dict):
        platforms.pop("telegram", None)
    if isinstance(platforms, dict) and not platforms:
        data.pop("platforms", None)
    if not data:
        os.remove(GW_JSON)
        print("[bot-config] gateway.json 已无内容，删除文件")
    else:
        _save_gw(data)
    print("[bot-config] 重启 gateway 生效: systemctl --user restart hermes-gateway")
    return 0


def main(argv: list) -> int:
    cmd = argv[1] if len(argv) > 1 else ""
    if cmd == "install":
        return cmd_install()
    if cmd == "uninstall":
        return cmd_uninstall()
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
