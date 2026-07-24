#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
高济健康Pro - 签到及任务自动完成脚本 (修复版)
基于 HAR 抓包分析 (2026-07-24)

功能:
1. 每日签到获取高G金
2. 查询积分/高G金余额
3. 自动完成浏览任务（逛积分商城等）

配置方式（环境变量）:
  TOKEN: 必填，bearer token (JWT access_token)
  多用户请用 & 分隔

可选环境变量:
  GJ_BUSINESS_ID: 商家ID，默认从抓包获取
  GJ_STORE_ID: 门店ID，默认空字符串
  GJ_USER_ID: 用户ID，默认从JWT解析
  GJ_PLATFORM_USER_ID: 平台用户ID，默认从JWT解析
  GJ_UNION_ID: 微信unionId，默认从JWT解析

兼容青龙面板，支持多用户
"""

import os
import re
import sys
import json
import time
import base64
import requests

BASE_URL = "https://api.gaojihealth.cn"


def log(msg, level="INFO"):
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] [{level}] {msg}")


def log_error(msg):
    log(msg, "ERROR")


def log_success(msg):
    log(msg, "SUCCESS")


def log_info(msg):
    log(msg, "INFO")


def decode_jwt(token):
    """解码 JWT token，提取 payload 中的用户信息"""
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return {}
        # JWT payload 是 base64url 编码
        payload = parts[1]
        # 补全 base64 填充
        padding = 4 - len(payload) % 4
        if padding != 4:
            payload += "=" * padding
        decoded = base64.urlsafe_b64decode(payload)
        return json.loads(decoded)
    except Exception as e:
        log_error(f"解析JWT失败: {e}")
        return {}


class GaoJiClient:

    def __init__(self, token, config=None):
        self.token = token.strip()
        self.config = {**(config or {})}
        self.session = requests.Session()

        # 从 JWT 中解析用户信息，作为默认配置
        jwt_data = decode_jwt(self.token)
        self._init_config_from_jwt(jwt_data)

        # 环境变量覆盖
        self._apply_env_overrides()

        self._init_headers()

    def _init_config_from_jwt(self, jwt_data):
        """从 JWT token 中提取配置"""
        defaults = {
            "businessId": str(jwt_data.get("businessId", "212798")),
            "userId": str(jwt_data.get("userId", "")),
            "platformUserId": str(jwt_data.get("platformUserId", "")),
            "unionId": str(jwt_data.get("unionId", "")),
            "miniOpenId": str(jwt_data.get("miniOpenId", "")),
            "storeId": "",
        }
        for key, val in defaults.items():
            if key not in self.config or not self.config.get(key):
                self.config[key] = val

    def _apply_env_overrides(self):
        """环境变量覆盖配置"""
        env_map = {
            "GJ_BUSINESS_ID": "businessId",
            "GJ_STORE_ID": "storeId",
            "GJ_USER_ID": "userId",
            "GJ_PLATFORM_USER_ID": "platformUserId",
            "GJ_UNION_ID": "unionId",
        }
        for env_key, config_key in env_map.items():
            if env_key in os.environ:
                self.config[config_key] = os.environ[env_key]

    def _init_headers(self):
        """初始化请求头 - 与抓包保持一致"""
        union_id = self.config.get("unionId", "")
        self.session.headers.update({
            "Host": "api.gaojihealth.cn",
            "Content-Type": "application/json;charset=utf-8",
            "Authorization": f"bearer {self.token}",
            "Cookie": f"access_token={self.token}",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36 "
                          "MicroMessenger/7.0.20.1781(0x6700143B) NetType/WIFI "
                          "MiniProgramEnv/Windows WindowsWechat/WMPF "
                          "WindowsWechat(0x63090a13) UnifiedPCWindowsWechat(0xf2541b18) "
                          "XWEB/20079",
            "Referer": "https://servicewechat.com/wx73ec617ea0a6c8e8/1345/page-frame.html",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9",
            # 抓包中出现的额外请求头
            "from-channelv2": "gjjk_pro",
            "from-channel": "gjjk_pro",
            "grantType": "gj_app_auth",
            "siteId": "miniprogram",
            "client-id": "miniprogram",
            "lastStart": "1256",
            "usign": union_id,
            "usign-group": f"bearer {self.token}",
            "shareId": "",
            "source": "",
            "channelPrice": "",
            "xweb_xhr": "1",
        })
        # 设置 X-XSRF-TOKEN（从 Cookie 中获取）
        self._update_xsrf_token()

    def _update_xsrf_token(self):
        """从 session cookie 中提取 XSRF-TOKEN 并设置到请求头"""
        try:
            xsrf = self.session.cookies.get("XSRF-TOKEN", domain=".gaojihealth.cn")
            if xsrf:
                self.session.headers["X-XSRF-TOKEN"] = xsrf
        except Exception:
            pass

    def _refresh_cookie_from_response(self, response):
        """从响应中提取 Set-Cookie 并更新 XSRF-TOKEN"""
        # requests.Session 自动处理 Set-Cookie，我们只需要更新请求头
        self._update_xsrf_token()

    def _get(self, path, params=None):
        url = f"{BASE_URL}{path}"
        try:
            self._update_xsrf_token()
            resp = self.session.get(url, params=params, timeout=30)
            self._refresh_cookie_from_response(resp)
            return resp.json() if resp.text else {}
        except Exception as e:
            log_error(f"GET {path} 失败: {e}")
            return None

    def _post(self, path, data=None):
        url = f"{BASE_URL}{path}"
        try:
            self._update_xsrf_token()
            resp = self.session.post(url, json=data or {}, timeout=30)
            self._refresh_cookie_from_response(resp)
            return resp.json() if resp.text else {}
        except Exception as e:
            log_error(f"POST {path} 失败: {e}")
            return None

    def get_sign_page(self):
        """获取签到页面信息"""
        path = "/fund/api/noauth/appCoupon/findDkSignActivityPage"
        params = {
            "businessId": self.config["businessId"],
            "userId": self.config["userId"],
            "version": "1.4",
        }
        result = self._get(path, params)
        if result and result.get("runFlag"):
            # 从响应中提取签到任务ID
            base_info = result.get("baseInfoModule", {})
            sign_module = result.get("signModule", {})
            integral = result.get("integralResponse", {})
            task_id = base_info.get("signTaskId") or sign_module.get("taskId")

            log_info(f"当前高G金: {integral.get('currentFund', '未知')}")
            log_info(f"签到任务ID: {task_id}")
            log_info(f"签到可得: {base_info.get('fundVal', 0)} 高G金/天")

            today_sign_flag = sign_module.get("todaySignFlag", False)
            if today_sign_flag:
                log_info("今日已签到")
                return {"signed": True, "data": result, "taskId": task_id}
            else:
                log_info("今日尚未签到，准备签到...")
                return {"signed": False, "data": result, "taskId": task_id}
        else:
            log_error("获取签到页面失败")
            return None

    def do_sign(self, task_id=None):
        """执行签到 - 与抓包完全一致"""
        # 如果没传 task_id，先获取签到页面
        if task_id is None:
            sign_page = self.get_sign_page()
            if sign_page:
                task_id = sign_page.get("taskId", 372)
            else:
                task_id = 372

        path = "/gulosity/api/dkUserEvent/everyDaySign"
        # 与抓包完全一致的请求体
        body = {
            "businessId": int(self.config["businessId"]),
            "storeId": "",  # 抓包中 storeId 为空字符串
            "userId": self.config["userId"],
            "taskId": task_id,
        }
        result = self._post(path, body)
        if result and result.get("opCode") == 200:
            prize = result.get("prizeInfo", "?")
            log_success(f"签到成功! 获得 {prize} 高G金")
            return True
        else:
            msg = result.get("opMsg", "未知错误") if result else "请求失败"
            log_error(f"签到失败: {msg}")
            return False

    def get_user_fund(self):
        """获取用户高G金余额"""
        path = "/fund/api/fundAccounts/getCurrentFundV2"
        params = {
            "businessId": self.config["businessId"],
            "storeId": self.config["storeId"],
        }
        result = self._get(path, params)
        if result:
            fund = result.get("fund", result.get("currentFund", "未知"))
            log_info(f"高G金余额: {fund}")
            return result
        return None

    def get_user_info(self):
        """获取用户信息"""
        path = "/uaa/api/userbaseinfo/userDetail"
        params = {"storeId": self.config["storeId"], "maskingFlag": "false"}
        result = self._get(path, params)
        if result:
            name = result.get("name", "未知")
            phone = result.get("phone", "")
            log_info(f"用户信息: {name} ({phone})")
            return result
        return None

    def get_user_achievement(self):
        """获取用户会员等级"""
        path = "/gulosity/api/dkUserAchievement/getUserAchievement"
        payload = {
            "businessId": int(self.config["businessId"]),
            "userId": self.config["userId"],
            "platformUserId": self.config["platformUserId"],
            "queryUserLevelNewVersion": True,
            "version": "3.0",
            "storeId": int(self.config["storeId"]) if self.config["storeId"] else "",
        }
        result = self._post(path, payload)
        if result and result.get("id"):
            log_info(f"会员等级: {result.get('levelName', '未知')} "
                     f"(Lv.{result.get('userLevel', 0)}, 积分: {result.get('score', 0)})")
            return result
        return None

    def get_tasks(self):
        """获取可完成的任务列表"""
        result = self.get_sign_page()
        if result and result.get("data"):
            tasks = result["data"].get("taskModule", {}).get("integralTaskList", [])
            if tasks:
                log_info(f"获取到 {len(tasks)} 个可完成任务:")
                for task in tasks:
                    log_info(f"  - {task.get('name', '未知')} "
                             f"(奖励: {task.get('prizeInfo', '?')} 积分, "
                             f"状态: {'已完成' if task.get('status') == 1 else '未完成'}, "
                             f"剩余: {task.get('leftTimes', 0)}次)")
            return tasks
        return []

    def complete_browse_task(self, task):
        """完成浏览任务"""
        task_id = task.get("taskId")
        task_name = task.get("name", "未知任务")
        browse_page_id = task.get("browsePageId", "")
        browse_page_url = task.get("browsePageUrl", "")
        log_info(f"开始完成任务: {task_name}")

        path = "/gulosity/api/dkUserEvent/browsePageCompleteTaskEvent"
        body = {
            "browsePageId": browse_page_id,
            "browsePageUrl": browse_page_url,
            "taskId": task_id,
        }
        result = self._post(path, body)
        # 修复：result 是 dict，不是 bool
        if result and result.get("opCode") == 200:
            log_success(f"任务 [{task_name}] 完成!")
            return True
        else:
            msg = result.get("opMsg", "失败") if result else "请求失败"
            log_error(f"任务 [{task_name}] 完成失败: {msg}")
            return False

    def complete_all_tasks(self):
        """完成所有未完成的任务"""
        tasks = self.get_tasks()
        if not tasks:
            return
        completed = 0
        for task in tasks:
            if task.get("status") == 1:
                log_info(f"任务 [{task.get('name', '未知')}] 已完成，跳过")
                continue
            if task.get("leftTimes", 0) <= 0:
                log_info(f"任务 [{task.get('name', '未知')}] 无剩余次数，跳过")
                continue
            if self.complete_browse_task(task):
                completed += 1
            time.sleep(1)
        log_success(f"完成 {completed}/{len(tasks)} 个任务")

    def run(self):
        log_info("=" * 40)
        log_info("高济健康Pro - 签到任务自动执行")
        log_info("=" * 40)

        self.get_user_info()
        self.get_user_fund()
        self.get_user_achievement()

        log_info("")
        log_info("=" * 40)
        log_info("执行签到...")
        log_info("=" * 40)
        sign_result = self.get_sign_page()
        if sign_result:
            if not sign_result.get("signed"):
                self.do_sign(sign_result.get("taskId"))
            else:
                log_info("今日已签到，跳过")
        else:
            # 直接尝试签到
            self.do_sign()

        log_info("")
        log_info("=" * 40)
        log_info("执行任务...")
        log_info("=" * 40)
        self.complete_all_tasks()

        log_info("")
        log_info("=" * 40)
        log_info("执行结果汇总")
        log_info("=" * 40)
        self.get_user_fund()
        log_success("所有任务执行完毕!")


def parse_tokens(token_str):
    """解析多用户 token 字符串"""
    if not token_str:
        return []
    tokens = re.split(r'[&\n]', token_str)
    return [t.strip() for t in tokens if t.strip()]


def run_user(token, config_override=None):
    client = GaoJiClient(token, config_override)
    try:
        client.run()
    except Exception as e:
        log_error(f"用户执行异常: {e}")
        import traceback
        traceback.print_exc()


def main():
    token_str = os.environ.get("TOKEN") or os.environ.get("GJ_TOKEN") or ""
    if not token_str:
        log_error("未设置 TOKEN 环境变量！")
        log_info("请设置 TOKEN 环境变量为你的 bearer token")
        log_info("多用户请用 & 分隔")
        sys.exit(1)

    config_override = {}
    tokens = parse_tokens(token_str)
    log_info(f"检测到 {len(tokens)} 个用户")
    for i, token in enumerate(tokens):
        log_info("")
        log_info("#" * 50)
        log_info(f"用户 {i + 1}/{len(tokens)}")
        log_info("#" * 50)
        run_user(token, config_override)

    log_success(f"全部 {len(tokens)} 个用户执行完毕!")


if __name__ == "__main__":
    main()