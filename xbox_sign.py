#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Xbox俱乐部自动签到
青龙面板部署脚本

环境变量: xbox_data（多个账号用 & 或 换行 分隔，每个账号为一个 sid）
示例: export xbox_data="sid1&sid2"

cron: 0 0,7 * * *
"""

import os
import sys
import json
import time
import requests

# ============ 配置 ============
NOTIFY = 1          # 是否发送通知: 1=是, 0=否
DEBUG = 0           # 调试模式: 1=开启, 0=关闭
HOST = "h5.youzan.com"
HOSTNAME = f"https://{HOST}"
APP_ID = "wx7f4f694622875202"
KDT_ID = "100464643"
CHECKIN_ID = "1597464"
USER_AGENT = (
    "Mozilla/5.0 (Linux; Android 10; ELS-AN00) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/96.0.4664.92 Mobile Safari/537.36"
)

# ============ 日志 & 通知 ============
msg_log = []


def double_log(text: str):
    """同时输出到控制台和通知日志"""
    print(text)
    msg_log.append(text)


def debug_log(*args):
    if DEBUG:
        print(*args)


# ============ 通知 ============
def send_notify(title: str, content: str):
    """调用青龙面板 sendNotify 发送通知"""
    if not NOTIFY or not content:
        return
    try:
        notify_path = os.path.join(os.path.dirname(__file__), "sendNotify.py")
        if os.path.exists(notify_path):
            import importlib.util
            spec = importlib.util.spec_from_file_location("sendNotify", notify_path)
            notify_mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(notify_mod)
            notify_mod.send(title, content)
        else:
            print("[WARN] sendNotify.py 未找到，跳过通知发送")
    except Exception as e:
        print(f"[WARN] 发送通知失败: {e}")


# ============ HTTP 请求 ============
def http_get(url: str, headers: dict, tip: str, timeout: int = 10):
    """发送 GET 请求并返回 JSON"""
    try:
        debug_log(f"\n[debug] =============== {tip} 请求 ===============")
        debug_log(f"URL: {url}")
        debug_log(f"Headers: {json.dumps(headers, ensure_ascii=False, indent=2)}")

        resp = requests.get(url, headers=headers, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()

        debug_log(f"\n[debug] =============== {tip} 返回 ===============")
        debug_log(json.dumps(data, ensure_ascii=False, indent=2))
        return data
    except requests.exceptions.RequestException as e:
        double_log(f"\n {tip} 请求失败! 请稍后尝试!! 错误: {e}")
        return None
    except json.JSONDecodeError as e:
        double_log(f"\n {tip} 返回数据解析失败! 错误: {e}")
        return None


# ============ 业务逻辑 ============
def build_headers(sid: str) -> dict:
    """构建请求头"""
    return {
        "Host": HOST,
        "user-agent": USER_AGENT,
        "extra-data": json.dumps({"is_weapp": 1, "sid": sid}, ensure_ascii=False),
    }


def userinfo(sid: str, idx: int) -> str:
    """查询用户信息"""
    url = f"{HOSTNAME}/wscuser/membercenter/global.json?app_id={APP_ID}&kdt_id={KDT_ID}"
    headers = build_headers(sid)
    result = http_get(url, headers, "用户信息查询")

    if result is None:
        double_log(f"账号[{idx}] 查询失败！")
        return None

    if result.get("code") == 0:
        nick_name = result["data"]["user"]["nickName"]
        return nick_name
    else:
        double_log(f"账号[{idx}] 查询失败！")
        return None


def get_points(sid: str, idx: int, nick_name: str):
    """查询用户积分"""
    url = f"{HOSTNAME}/wscuser/membercenter/stats.json?app_id={APP_ID}&kdt_id={KDT_ID}"
    headers = build_headers(sid)
    result = http_get(url, headers, "用户积分查询")

    if result is None:
        double_log(f"账号[{idx}] 积分查询失败！")
        return

    if result.get("code") == 0:
        points = result["data"]["stats"]["points"]
        double_log(f"账号[{idx}] 用户[{nick_name}] 积分:{points} 🎉")
    else:
        double_log(f"账号[{idx}] 积分查询失败！")


def checkin(sid: str, idx: int):
    """用户签到"""
    url = (
        f"{HOSTNAME}/wscump/checkin/checkinV2.json"
        f"?checkinId={CHECKIN_ID}&app_id={APP_ID}&kdt_id={KDT_ID}"
    )
    headers = build_headers(sid)
    result = http_get(url, headers, "签到")

    if result is None:
        double_log(f"账号[{idx}] 签到请求失败！")
        return

    code = result.get("code")
    msg_text = result.get("msg", "")

    if code == 0:
        try:
            reward = result["data"]["list"][0]["infos"]["title"]
        except (KeyError, IndexError):
            reward = "未知奖励"
        double_log(f"账号[{idx}] 签到:{msg_text} 获得:{reward} 🎉")
    elif code == 1000030071:
        double_log(f"账号[{idx}] 签到失败！原因:{msg_text}")
    else:
        double_log(f"账号[{idx}] 签到失败！原因:{msg_text}")


# ============ 环境变量处理 ============
def parse_env(env_str: str) -> list:
    """解析多账号环境变量"""
    if not env_str:
        return []
    env_str = env_str.strip()
    if "&" in env_str:
        return [s.strip() for s in env_str.split("&") if s.strip()]
    elif "\n" in env_str:
        return [s.strip() for s in env_str.split("\n") if s.strip()]
    else:
        return [env_str]


# ============ 主入口 ============
def main():
    print("🔔 Xbox俱乐部V2, 开始!")
    print("\n每日执行签到,积分兑换实物")

    ck_str = os.environ.get("xbox_data", "").strip()
    ck_arr = parse_env(ck_str)

    if not ck_arr:
        print("\n❗️ Xbox俱乐部: 未填写变量 xbox_data, 请仔细阅读脚本说明!")
        sys.exit(1)

    print(f"\n========== 共找到 {len(ck_arr)} 个账号 ==========")
    debug_log(f"【debug】 这是你的账号数组:\n {ck_arr}")

    # 查询
    print("\n📌📌📌📌📌📌📌📌 查询 📌📌📌📌📌📌📌📌")
    for i, sid in enumerate(ck_arr):
        nick_name = userinfo(sid, i + 1)
        if nick_name:
            get_points(sid, i + 1, nick_name)
        time.sleep(2)

    # 签到
    print("\n📌📌📌📌📌📌📌📌 签到 📌📌📌📌📌📌📌📌")
    for i, sid in enumerate(ck_arr):
        checkin(sid, i + 1)
        time.sleep(2)

    # 发送通知
    full_msg = "\n".join(msg_log)
    if full_msg:
        send_notify("Xbox俱乐部", full_msg)

    elapsed = time.time() - time.time()  # 占位，实际无需精确计时
    print(f"\n🔔 Xbox俱乐部, 结束!")


if __name__ == "__main__":
    start_time = time.time()
    try:
        main()
    except Exception as e:
        double_log(f"\n❗️ Xbox俱乐部, 错误! {e}")
    finally:
        elapsed = time.time() - start_time
        print(f"\n🕛 共耗时 {elapsed:.2f} 秒")
