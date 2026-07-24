#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
天禧家微信小程序 自动签到脚本 (青龙面板)

基于 gjjj.js (顾家家居) 逆向分析，适配天禧家小程序 (appId=877139, brandCode=K006)

抓包说明：
  Host: https://mc.kukahome.com
  在请求头中获取 AccessToken 和 X-Customer，格式：
    export TIANXI_TOKEN = 'AccessToken#X-Customer'
  多账号用 & 或 换行 分隔

定时规则 (cron): 5 10 * * *

技术说明：
  - 经测试验证，服务器不校验 sign 字段，仅校验 parameterSign
  - 因此无需 appSecret，POST 请求只需提供正确的 parameterSign
  - GET 请求连 parameterSign 都不需要
"""

import os
import sys
import json
import time
import random
import hashlib
import requests

# ============================================================
# 配置区
# ============================================================

# 天禧家的 appId 和 brandCode（从抓包获取）
APP_ID = '877139'
BRAND_CODE = 'K006'

# 接口地址
BASE_URL = 'https://mc.kukahome.com'
VERSION = '2.0.111'
REFERER = 'https://servicewechat.com/wx8e727b1591061cfa/136/page-frame.html'

# ============================================================
# 以下代码无需修改
# ============================================================

# 全局消息（用于推送通知）
message = ''


def get_user_agent():
    """随机 User-Agent（模拟微信小程序环境）"""
    ua_list = [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36 MicroMessenger/7.0.20.1781(0x6700143B) NetType/WIFI MiniProgramEnv/Windows WindowsWechat/WMPF WindowsWechat(0x63090a13) UnifiedPCWindowsWechat(0xf2541b18) XWEB/20079',
        'Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Mobile/15E148 MicroMessenger/8.0.43(0x18002b2c) NetType/WIFI Language/zh_CN',
        'Mozilla/5.0 (Linux; Android 13; SM-S9080) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.230 Mobile Safari/537.36 MicroMessenger/8.0.47(0x18002f2c) NetType/WIFI Language/zh_CN',
    ]
    return random.choice(ua_list)


def build_headers(access_token, x_customer, timestamp):
    """构建请求头（不含 sign，服务器不校验）"""
    return {
        'User-Agent': get_user_agent(),
        'Content-Type': 'application/json',
        'brandCode': BRAND_CODE,
        'appid': APP_ID,
        'timestamp': str(timestamp),
        'AccessToken': access_token,
        'X-Customer': x_customer,
        'versionNumber': VERSION,
        'tmpToken': '',
        'Referer': REFERER,
        'Accept-Language': 'zh-CN,zh;q=0.9',
    }


def calc_parameter_sign(body, timestamp):
    """
    计算 parameterSign：
    sign = md5(md5(排序后的key=value参数) + timestamp[4:10])
    """
    ts = str(timestamp) if timestamp else str(int(time.time() * 1000))
    sorted_keys = sorted(body.keys())
    param_parts = []
    for k in sorted_keys:
        v = body[k]
        if isinstance(v, (dict, list)):
            v = json.dumps(v, separators=(',', ':'))
        param_parts.append(f'{k}={v}')
    param_str = '&'.join(param_parts)
    inner_md5 = hashlib.md5(param_str.encode()).hexdigest()
    ts_sub = ts[4:10]
    return hashlib.md5((inner_md5 + ts_sub).encode()).hexdigest()


def send_api(url, method='post', body=None, access_token='', x_customer=''):
    """发送API请求，自动处理签名"""
    timestamp = int(time.time() * 1000)
    headers = build_headers(access_token, x_customer, timestamp)

    # 有body时计算 parameterSign（服务器不校验 sign）
    if body is not None:
        headers['parameterSign'] = calc_parameter_sign(body, timestamp)

    full_url = BASE_URL + url

    if method.upper() == 'GET':
        resp = requests.get(full_url, headers=headers, timeout=30)
    else:
        resp = requests.post(full_url, headers=headers, json=body, timeout=30)

    result = resp.json()

    # personalCenter 接口直接返回用户数据（无 code/success 字段）
    # 标准接口返回 {code, data, message, success}
    if 'code' in result:
        code = result.get('code')
        # code=101 表示"今日已签到"或其他业务状态，不算失败
        if code is not None and code != 0 and code != 101:
            err_msg = result.get('message') or result.get('msg') or '未知错误'
            raise Exception(f'请求 {url} 失败(code={code}): {err_msg}')

    return result


# ============================================================
# API 封装
# ============================================================

def get_user_info(access_token, x_customer):
    """获取用户信息（手机号、积分等）"""
    timestamp = int(time.time() * 1000)
    body = {'t': timestamp}
    result = send_api('/club-server/front/member/personalCenter', 'post', body, access_token, x_customer)
    # personalCenter 直接返回用户数据字段，没有 data 包裹
    mobile = result.get('mobile', '未获取到')
    point = result.get('point', 0)
    return mobile, point


def sign_in(access_token, x_customer):
    """执行签到"""
    body = {'scene': 'sign', 'brandCode': BRAND_CODE}
    result = send_api('/integral-server/scenePoint/scene/point', 'post', body, access_token, x_customer)
    earned_points = result.get('data', 0)
    return earned_points


def get_sign_status(access_token, x_customer):
    """获取签到日历和连续签到天数"""
    result = send_api('/integral-server/user/sign/calendar', 'get', None, access_token, x_customer)
    cal_data = result.get('data', {})
    sign_count = cal_data.get('signCount', 0)
    is_today_signed = cal_data.get('isTodaySigned', False)
    return sign_count, is_today_signed


# ============================================================
# 主流程
# ============================================================

def process_account(access_token, x_customer, index):
    """处理单个账号的签到流程"""
    global message

    print(f'\n***** 第[{index}]个天禧家账号 *****')
    prefix = f'====天禧家账号[{index}]===='

    # 1. 获取用户信息
    print('>> 获取用户信息...')
    mobile, before_point = get_user_info(access_token, x_customer)
    print(f'   手机号: {mobile}')
    print(f'   当前积分: {before_point}')
    message += f'{prefix}\n{mobile}\n当前积分: {before_point}\n'

    # 2. 检查签到状态
    sign_count, is_today_signed = get_sign_status(access_token, x_customer)
    print(f'   已连续签到 {sign_count} 天')
    print(f'   今日是否已签到: {is_today_signed}')

    if is_today_signed:
        print('   今日已签到，跳过')
        message += '今日已签到\n'
        _, after_point = get_user_info(access_token, x_customer)
        message += f'当前积分：{after_point}\n\n'
        return

    # 3. 执行签到
    print('>> 执行签到...')
    earned_points = sign_in(access_token, x_customer)
    print(f'   签到成功，积分+{earned_points}')
    message += f'签到成功，积分+{earned_points}\n'

    # 4. 签到后查询
    time.sleep(random.uniform(1, 2))
    sign_count, _ = get_sign_status(access_token, x_customer)
    _, after_point = get_user_info(access_token, x_customer)
    print(f'   已连续签到 {sign_count} 天')
    print(f'   当前积分：{after_point}')
    message += f'已连续签到 {sign_count} 天\n'
    message += f'当前积分：{after_point}\n\n'


def main():
    global message

    # 读取环境变量
    token_raw = os.environ.get('TIANXI_TOKEN', '')
    if not token_raw:
        print('未设置 TIANXI_TOKEN 环境变量')
        message = '未设置 TIANXI_TOKEN 环境变量\n'
        return

    # 解析多账号（支持 & 或换行分隔）
    token_list = [t.strip() for t in token_raw.replace('\n', '&').split('&') if t.strip()]
    account_count = len(token_list)
    print(f'共检测到 {account_count} 个账号')

    for i, token in enumerate(token_list):
        parts = token.split('#')
        if len(parts) != 2:
            print(f'账号[{i+1}] 格式错误，跳过（应为 AccessToken#X-Customer）')
            message += f'账号[{i+1}] 格式错误，跳过\n'
            continue

        access_token = parts[0].strip()
        x_customer = parts[1].strip()

        try:
            process_account(access_token, x_customer, i + 1)
        except Exception as e:
            print(f'账号[{i+1}] 执行失败: {e}')
            message += f'账号[{i+1}] 执行失败: {e}\n\n'

        # 多账号间随机等待，避免触发风控
        if i < account_count - 1:
            wait_time = random.uniform(2.0, 3.5)
            print(f'等待 {wait_time:.1f} 秒后处理下一个账号...')
            time.sleep(wait_time)


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        print(f'脚本异常: {e}')
        message += f'脚本异常: {e}\n'
    finally:
        # 推送通知到青龙面板
        if message:
            try:
                sys.path.insert(0, '/ql/scripts')
                from sendNotify import send
                send('天禧家签到', message)
                print('通知推送完成')
            except ImportError:
                # 本地运行或没有青龙通知模块，直接打印
                print('\n' + '=' * 30)
                print('签到结果:')
                print('=' * 30)
                print(message)
