#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
蒙娜丽莎微信小程序自动签到
部署到青龙面板(Qinglong Panel)

==================== 环境变量 ====================
  名称: monalisa_webchat_id
  值:   你的 webChatID(微信OpenID)
        多账号用 @ 分隔，例如: oXXX1@oXXX2

  获取方式: 抓包小程序，找到 doAction 请求中
            action=getCustomer&webChatID=xxxx 的 xxxx 值

==================== 依赖安装 ====================
  青龙面板 -> 依赖管理 -> 新建依赖(Python):
    requests

  验证码识别使用远程 ddddocr 服务，无需安装 ddddocr 本地依赖

==================== 定时建议 ====================
  0 8 * * *    (每天早上8点)

================================================
"""

import os
import re
import sys
import time
import uuid
import base64
import logging
import requests

# ======================== 日志配置 ========================
logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
)
logger = logging.getLogger("monalisa")


# ======================== 常量定义 ========================
BASE_URL = "https://mcs.monalisagroup.com.cn/member/doAction"
BRAND = "MON"

# 远程 ddddocr OCR 服务地址
OCR_SERVER_URL = os.environ.get("monalisa_ocr_url", "http://192.168.199.8:7777/classification")

# 模拟微信小程序请求头
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36 "
        "MicroMessenger/7.0.20.1781(0x6700143B) NetType/WIFI "
        "MiniProgramEnv/Windows WindowsWechat/WMPF "
        "WindowsWechat(0x63090a13) UnifiedPCWindowsWechat(0xf2541b18) XWEB/20079"
    ),
    "xweb_xhr": "1",
    "Content-Type": "application/x-www-form-urlencoded",
    "Accept": "*/*",
    "Sec-Fetch-Site": "cross-site",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Dest": "empty",
    "Referer": "https://servicewechat.com/wxce6a8f654e81b7a4/495/page-frame.html",
    "Accept-Encoding": "gzip, deflate, br",
    "Accept-Language": "zh-CN,zh;q=0.9",
}

# 签到验证码最大重试次数
MAX_CAPTCHA_RETRIES = 5
# 账号间间隔(秒)
ACCOUNT_INTERVAL = 3


# ======================== OCR 验证码识别(远程服务) ========================
def recognize_captcha(b64_image: str) -> str:
    """调用远程 ddddocr 服务识别验证码图片，返回文本"""
    try:
        resp = requests.post(
            OCR_SERVER_URL,
            json={"image": b64_image},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        text = data.get("result", "")
        logger.info(f"  ✅ 远程 OCR 识别: {text!r}")
        return text.strip()
    except Exception as e:
        logger.info(f"  ❌ 远程 OCR 识别失败: {e}")
        return ""


def solve_captcha(text: str):
    """
    从验证码文本中解析算式并计算结果。

    支持格式:
      - 算术题: "7+16=?", "20 - 5 = ?", "3×4=?"
      - 纯数字: "1234"
    """
    # 清理文本: 去除空格、等号、问号(半角/全角)、换行
    cleaned = re.sub(r"[\s=?？\n]", "", text)

    logger.info(f"  验证码识别原文: {text!r} -> 清理后: {cleaned!r}")

    # 匹配算术表达式: 数字 运算符 数字
    match = re.match(r"(\d+)\s*([+\-*/×÷])\s*(\d+)", cleaned)
    if match:
        a = int(match.group(1))
        op = match.group(2)
        b = int(match.group(3))

        if op == "+":
            result = a + b
        elif op == "-":
            result = a - b
        elif op in ("*", "×"):
            result = a * b
        elif op in ("/", "÷"):
            result = a // b if b != 0 else None
        else:
            return None

        if result is not None:
            logger.info(f"  算式: {a} {op} {b} = {result}")
        return result

    # 纯数字验证码
    if re.match(r"^\d+$", cleaned):
        result = int(cleaned)
        logger.info(f"  纯数字验证码: {result}")
        return result

    logger.info(f"  ⚠️ 无法解析验证码: {cleaned!r}")
    return None


# ======================== API 接口封装 ========================
def do_action(session: requests.Session, **params) -> dict:
    """调用 monalisa doAction 接口"""
    data = {"brand": BRAND}
    data.update(params)
    resp = session.post(BASE_URL, headers=HEADERS, data=data, timeout=30)
    resp.raise_for_status()
    return resp.json()


def get_customer(session: requests.Session, webchat_id: str) -> dict:
    """获取用户信息 (CustomerID, StoreID, OrganizationID 等)"""
    result = do_action(session, action="getCustomer", webChatID=webchat_id)
    if result.get("status") == 0 and result.get("resultInfo"):
        return result["resultInfo"][0]
    return None


def check_attendance(session: requests.Session, customer_id) -> dict:
    """查询连续签到状态"""
    return do_action(session, action="continuousAttendance", CustomerID=customer_id)


def generate_captcha(session: requests.Session, token_str: str) -> dict:
    """生成验证码，返回包含 base64 图片的响应"""
    return do_action(session, action="generateCaptcha", tokenStr=token_str)


def do_sign(
    session: requests.Session,
    customer_id,
    customer_name: str,
    store_id,
    org_id,
    token_str: str,
    answer,
) -> dict:
    """执行签到"""
    return do_action(
        session,
        action="sign",
        CustomerID=customer_id,
        CustomerName=customer_name,
        StoreID=store_id,
        OrganizationID=org_id,
        Brand=BRAND,  # 注意: 签到接口同时需要 brand(小写) 和 Brand(大写)
        tokenStr=token_str,
        correctAnswer=answer,
    )


# ======================== 核心签到流程 ========================
def sign_in(webchat_id: str, account_label: str = "") -> list:
    """
    执行完整签到流程:
      1. getCustomer    - 获取用户信息
      2. continuousAttendance - 查询签到状态
      3. generateCaptcha + 远程OCR - 生成并识别验证码
      4. sign           - 提交签到
    """
    session = requests.Session()
    messages = []
    prefix = f"[{account_label}] " if account_label else ""

    # ---------- 1. 获取用户信息 ----------
    logger.info(f"{prefix}📌 获取用户信息...")
    try:
        customer = get_customer(session, webchat_id)
    except Exception as e:
        msg = f"{prefix}❌ 获取用户信息异常: {e}"
        logger.info(msg)
        messages.append(msg)
        return messages

    if not customer:
        msg = f"{prefix}❌ 获取用户信息失败，请检查 webChatID 是否正确"
        logger.info(msg)
        messages.append(msg)
        return messages

    customer_id = customer["CustomerID"]
    customer_name = customer.get("CustomerName", "微信用户")
    store_id = customer["StoreID"]
    org_id = customer["OrganizationID"]
    integral = customer.get("Integral", "未知")
    store_name = customer.get("StoreName", "")

    logger.info(
        f"{prefix}👤 用户: {customer_name} | ID: {customer_id} | "
        f"积分: {integral} | 门店: {store_name}"
    )

    # ---------- 2. 查询签到状态 ----------
    logger.info(f"{prefix}📅 查询签到状态...")
    try:
        attendance = check_attendance(session, customer_id)
    except Exception as e:
        msg = f"{prefix}❌ 查询签到状态异常: {e}"
        logger.info(msg)
        messages.append(msg)
        return messages

    if attendance.get("status") == 0:
        info = attendance.get("resultInfo", {})
        todays = info.get("todays", 0)
        continuity_day = info.get("continuityDay", 0)

        if todays:
            msg = (
                f"{prefix}✅ 今日已签到 | 连续{continuity_day}天 | "
                f"当前积分: {integral}"
            )
            logger.info(msg)
            messages.append(msg)
            return messages
        else:
            logger.info(
                f"{prefix}📅 今日未签到 | 连续签到: {continuity_day}天"
            )
    else:
        logger.info(f"{prefix}⚠️ 查询签到状态返回异常: {attendance}")

    # ---------- 3 + 4. 生成验证码 -> 远程OCR识别 -> 签到 ----------
    signed_success = False
    for attempt in range(1, MAX_CAPTCHA_RETRIES + 1):
        logger.info(f"{prefix}🔑 生成验证码 (第{attempt}/{MAX_CAPTCHA_RETRIES}次)...")

        # 生成 tokenStr (客户端随机 UUID)
        token_str = str(uuid.uuid4())

        try:
            captcha_resp = generate_captcha(session, token_str)
        except Exception as e:
            logger.info(f"{prefix}⚠️ 生成验证码异常: {e}")
            time.sleep(2)
            continue

        if captcha_resp.get("status") != 0:
            logger.info(f"{prefix}⚠️ 生成验证码失败: {captcha_resp}")
            time.sleep(2)
            continue

        b64_image = captcha_resp.get("resultInfo", "")
        if not b64_image:
            logger.info(f"{prefix}⚠️ 验证码图片为空")
            time.sleep(2)
            continue

        # 远程 OCR 识别验证码
        try:
            ocr_text = recognize_captcha(b64_image)
            answer = solve_captcha(ocr_text)
        except Exception as e:
            logger.info(f"{prefix}⚠️ 验证码识别异常: {e}")
            answer = None

        if answer is None:
            logger.info(f"{prefix}⚠️ 验证码识别失败，重新生成...")
            time.sleep(1)
            continue

        logger.info(f"{prefix}🧮 验证码答案: {answer}")

        # 执行签到
        logger.info(f"{prefix}📌 提交签到...")
        try:
            sign_resp = do_sign(
                session,
                customer_id,
                customer_name,
                store_id,
                org_id,
                token_str,
                answer,
            )
        except Exception as e:
            logger.info(f"{prefix}⚠️ 签到请求异常: {e}")
            time.sleep(2)
            continue

        if sign_resp.get("status") == 0:
            points = sign_resp.get("resultInfo", "未知")
            msg = f"{prefix}🎉 签到成功！获得积分: {points} | 当前积分: {integral}"
            logger.info(msg)
            messages.append(msg)
            signed_success = True
            break
        else:
            error_info = sign_resp.get("resultInfo", "未知错误")
            logger.info(f"{prefix}⚠️ 签到失败: {error_info}，重试中...")
            time.sleep(2)

    if not signed_success:
        msg = f"{prefix}❌ 签到失败，已重试{MAX_CAPTCHA_RETRIES}次"
        logger.info(msg)
        messages.append(msg)

    return messages


# ======================== 通知发送 ========================
def send_notification(messages: list):
    """通过青龙面板的 sendNotify 发送通知"""
    try:
        from sendNotify import send

        title = "🎭 蒙娜丽莎签到"
        content = "\n".join(messages)
        send(title, content)
        logger.info("📧 通知已发送")
    except ImportError:
        logger.info("📧 未找到 sendNotify.py，跳过通知发送")
    except Exception as e:
        logger.info(f"📧 通知发送失败: {e}")


# ======================== 主函数 ========================
def main():
    logger.info("=" * 55)
    logger.info("🎭 蒙娜丽莎微信小程序自动签到")
    logger.info("=" * 55)
    logger.info(f"🔒 OCR 服务: {OCR_SERVER_URL}")
    logger.info("")

    # 读取环境变量
    webchat_ids_raw = os.environ.get("monalisa_webchat_id", "").strip()

    if not webchat_ids_raw:
        logger.info("")
        logger.info("❌ 未设置环境变量 monalisa_webchat_id")
        logger.info("")
        logger.info("请在青龙面板 -> 环境变量 中添加:")
        logger.info("  名称: monalisa_webchat_id")
        logger.info("  值:   你的 webChatID(微信OpenID)")
        logger.info("        多账号用 @ 分隔")
        logger.info("")
        logger.info("获取方式:")
        logger.info("  抓包小程序，找到 action=getCustomer 请求")
        logger.info("  其中的 webChatID=xxxx 值即为所需")
        sys.exit(1)

    # 分割多账号
    accounts = [x.strip() for x in webchat_ids_raw.split("@") if x.strip()]
    logger.info(f"📋 共 {len(accounts)} 个账号")
    logger.info("")

    all_messages = []

    for i, webchat_id in enumerate(accounts, 1):
        label = f"账号{i}"
        logger.info(f"--- {label} ---")

        messages = sign_in(webchat_id, label)
        all_messages.extend(messages)

        if i < len(accounts):
            logger.info(f"\n⏳ 等待 {ACCOUNT_INTERVAL} 秒...\n")
            time.sleep(ACCOUNT_INTERVAL)

    # 汇总结果
    logger.info("")
    logger.info("=" * 55)
    logger.info("📊 签到结果汇总:")
    for msg in all_messages:
        logger.info(f"  {msg}")
    logger.info("=" * 55)

    # 发送通知
    send_notification(all_messages)


if __name__ == "__main__":
    main()
