#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
爱果乐之家自动签到
青龙面板部署脚本

环境变量: aigole_data
  单账号格式: sid&access_token
  多账号格式: sid1&access_token1@sid2&access_token2
  示例: export aigole_data="YZ1530142349802045440YZTq0EKx7Y&66d2211eb8dcec9fb60d16c69cb618"

参数获取方式（抓包 h5.youzan.com 域名）:
  - sid: 请求头 Extra-Data 中的 sid 字段
  - access_token: 签到请求 URL 中的 access_token 参数

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
APP_ID = "wxa1086b8081476f46"
KDT_ID = "18774683"
CHECKIN_ID = "4544173"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/132.0.0.0 Safari/537.36 "
    "MicroMessenger/7.0.20.1781(0x6700143B) "
    "NetType/WIFI MiniProgramEnv/Windows "
    "WindowsWechat/WMPF WindowsWechat(0x63090a13) "
    "UnifiedPCWindowsWechat(0xf2541b18) XWEB/20079"
)
REFERER = f"https://servicewechat.com/{APP_ID}/3/page-frame.html"

# ============ 日志 & 通知 ============
msg_log = []


def double_log(text: str):
    """同时输出到控制台和通知日志"""
    print(text)
    msg_log.append(text)


def debug_log(*args):
    if DEBUG:
        print(*args)


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
    """构建请求头，sid 动态替换，ftime 用当前时间戳"""
    extra_data = {
        "is_weapp": 1,
        "sid": sid,
        "version": "2.195.7.101",
        "client": "weapp",
        "bizEnv": "wsc",
        "uuid": "QpTPveeftCBFJkr1784777974756",
        "ftime": int(time.time() * 1000),
    }
    return {
        "Host": HOST,
        "Connection": "keep-alive",
        "User-Agent": USER_AGENT,
        "xweb_xhr": "1",
        "Content-Type": "application/json",
        "Extra-Data": json.dumps(extra_data, ensure_ascii=False),
        "Accept": "*/*",
        "Sec-Fetch-Site": "cross-site",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Dest": "empty",
        "Referer": REFERER,
        "Accept-Language": "zh-CN,zh;q=0.9",
    }


def build_query_url(path: str, access_token: str) -> str:
    """构建带 access_token 的查询接口 URL"""
    return f"{HOSTNAME}{path}?app_id={APP_ID}&kdt_id={KDT_ID}&access_token={access_token}"


def userinfo(sid: str, access_token: str, idx: int) -> str:
    """查询用户信息"""
    url = build_query_url("/wscuser/membercenter/global.json", access_token)
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


def get_points(sid: str, access_token: str, idx: int, nick_name: str):
    """查询用户积分"""
    url = build_query_url("/wscuser/membercenter/stats.json", access_token)
    headers = build_headers(sid)
    result = http_get(url, headers, "积分查询")

    if result is None:
        double_log(f"账号[{idx}] 积分查询失败！")
        return

    if result.get("code") == 0:
        points = result["data"]["stats"]["points"]
        double_log(f"账号[{idx}] 用户[{nick_name}] 积分:{points} 🎉")
    else:
        double_log(f"账号[{idx}] 积分查询失败！")


def checkin(sid: str, access_token: str, idx: int):
    """用户签到"""
    url = (
        f"{HOSTNAME}/wscump/checkin/checkinV2.json"
        f"?checkinId={CHECKIN_ID}&app_id={APP_ID}&kdt_id={KDT_ID}&access_token={access_token}"
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
        try:
            desc = result["data"].get("desc", "")
        except (KeyError, IndexError):
            desc = ""
        if desc:
            double_log(f"账号[{idx}] 签到:{msg_text} {desc} 获得:{reward} 🎉")
        else:
            double_log(f"账号[{idx}] 签到:{msg_text} 获得:{reward} 🎉")
    elif code == 1000030071:
        double_log(f"账号[{idx}] 签到失败！原因:{msg_text}（今日已签到）")
    else:
        double_log(f"账号[{idx}] 签到失败！原因:{msg_text}")


# ============ 环境变量处理 ============
def parse_env(env_str: str) -> list:
    """解析多账号环境变量，支持 @ 和换行分隔"""
    if not env_str:
        return []
    env_str = env_str.strip()
    if "@" in env_str:
        return [s.strip() for s in env_str.split("@") if s.strip()]
    elif "\n" in env_str:
        return [s.strip() for s in env_str.split("\n") if s.strip()]
    else:
        return [env_str]


def parse_account(account: str, idx: int):
    """解析单账号，返回 (sid, access_token) 或 None"""
    parts = account.split("&")
    if len(parts) < 2:
        double_log(f"账号[{idx}] 格式错误！应为 sid&access_token")
        return None
    return parts[0].strip(), parts[1].strip()


# ============ 主入口 ============
def main():
    print("🔔 爱果乐之家, 开始!")
    print("\n每日执行签到,赚取品牌积分")

    ck_str = os.environ.get("aigole_data", "").strip()
    ck_arr = parse_env(ck_str)

    if not ck_arr:
        print("\n❗️ 爱果乐之家: 未填写变量 aigole_data, 请仔细阅读脚本说明!")
        sys.exit(1)

    print(f"\n========== 共找到 {len(ck_arr)} 个账号 ==========")
    debug_log(f"【debug】 这是你的账号数组:\n {ck_arr}")

    # 查询
    print("\n📌📌📌📌📌📌📌📌 查询 📌📌📌📌📌📌📌📌")
    for i, account in enumerate(ck_arr):
        parsed = parse_account(account, i + 1)
        if not parsed:
            continue
        sid, access_token = parsed
        nick_name = userinfo(sid, access_token, i + 1)
        if nick_name:
            get_points(sid, access_token, i + 1, nick_name)
        time.sleep(2)

    # 签到
    print("\n📌📌📌📌📌📌📌📌 签到 📌📌📌📌📌📌📌📌")
    for i, account in enumerate(ck_arr):
        parsed = parse_account(account, i + 1)
        if not parsed:
            continue
        sid, access_token = parsed
        checkin(sid, access_token, i + 1)
        time.sleep(2)

    # 发送通知
    full_msg = "\n".join(msg_log)
    if full_msg:
        send_notify("爱果乐之家", full_msg)

    print(f"\n🔔 爱果乐之家, 结束!")


if __name__ == "__main__":
    start_time = time.time()
    try:
        main()
    except Exception as e:
        double_log(f"\n❗️ 爱果乐之家, 错误! {e}")
    finally:
        elapsed = time.time() - start_time
        print(f"\n🕛 共耗时 {elapsed:.2f} 秒")
