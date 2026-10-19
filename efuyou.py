"""
e服药青龙每日签到脚本

环境变量:
  EFUYAO_TOKEN       - e服药 token，多账号用 &、### 或换行分隔
  EFUYAO_USER_ID     - e服药 userId，多账号用 &、### 或换行分隔
  EFUYAO_LOGIN_NAME  - 可选，账号密码登录名；配置后 token 失效会自动刷新
  EFUYAO_PASSWORD    - 可选，账号密码登录密码；多账号分隔方式同上
  EFUYAO_LOGIN_CODE  - 可选，微信授权 code；当前接口不填也可登录，保留兼容
  EFUYAO_SSL_VERIFY  - 是否校验 HTTPS 证书，1 是，0 否，默认 0
  QYWX_AM            - 企业微信应用，格式：corpid,corpsecret,touser,agentid
  QYWX_CORPID        - 企业微信企业 ID（未配置 QYWX_AM 时使用）
  QYWX_CORPSECRET    - 企业微信应用 Secret
  QYWX_TOUSER        - 接收成员，多个用 | 分隔，默认 @all
  QYWX_AGENTID       - 企业微信应用 AgentId
  QYWX_ORIGIN        - 企业微信 API 地址，默认 https://qyapi.weixin.qq.com
  HITOKOTO           - 是否在通知末尾附带每日一言，默认 true

cron: 10 8 * * *
new Env("e服药每日签到")
"""

import os
import re
import time
from datetime import datetime

import requests

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    pass


BASE_URL = "https://miniapp-e.yidudao.cn"
HITOKOTO_CACHE = None
SSL_VERIFY = os.getenv("EFUYAO_SSL_VERIFY", "0").strip().lower() in {"1", "true", "yes", "on"}
if not SSL_VERIFY:
    try:
        requests.packages.urllib3.disable_warnings()
    except Exception:
        pass
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36 "
    "MicroMessenger/7.0.20.1781(0x6700143B) NetType/WIFI "
    "MiniProgramEnv/Windows WindowsWechat/WMPF WindowsWechat(0x63090a13) "
    "UnifiedPCWindowsWechat(0xf2541b18) XWEB/20005"
)
REFERER = "https://servicewechat.com/wxe038c10ca578887d/10/page-frame.html"


def split_env(value):
    return [item.strip() for item in re.split(r"(?:###|&|\n)+", value or "") if item.strip()]


def env_item(values, index):
    return values[index] if index < len(values) else ""


def mask_value(value, left=4, right=4):
    value = str(value or "")
    if len(value) <= left + right:
        return value[:1] + "***" if value else "-"
    return f"{value[:left]}***{value[-right:]}"


def hitokoto_parts():
    global HITOKOTO_CACHE
    if HITOKOTO_CACHE is not None:
        return HITOKOTO_CACHE
    if os.getenv("HITOKOTO", "true").lower() == "false":
        HITOKOTO_CACHE = ("", "")
        return HITOKOTO_CACHE
    try:
        response = requests.get("https://v1.hitokoto.cn/", timeout=5, verify=SSL_VERIFY)
        response.raise_for_status()
        data = response.json()
        HITOKOTO_CACHE = (data.get("hitokoto", "").strip(), data.get("from", "").strip())
    except Exception as error:
        print(f"每日一言获取失败: {error}")
        HITOKOTO_CACHE = ("", "")
    return HITOKOTO_CACHE


def request_json(path, payload):
    headers = {
        "Host": "miniapp-e.yidudao.cn",
        "Connection": "keep-alive",
        "User-Agent": USER_AGENT,
        "xweb_xhr": "1",
        "Content-Type": "application/json",
        "Accept": "*/*",
        "Sec-Fetch-Site": "cross-site",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Dest": "empty",
        "Referer": REFERER,
        "Accept-Language": "zh-CN,zh;q=0.9",
    }
    response = requests.post(
        f"{BASE_URL}{path}",
        headers=headers,
        json=payload,
        timeout=20,
        verify=SSL_VERIFY,
    )
    response.raise_for_status()
    return response.json()


def login_account(index, login_name, password, login_code=""):
    payload = {
        "loginName": login_name,
        "password": password,
        "goTake": 1,
    }
    if login_code:
        payload["code"] = login_code

    data = request_json("/api/miniapp/user/login", payload)
    account_label = f"账号{index} login={mask_value(login_name, 3, 3)}"
    if data.get("code") != 200:
        message = data.get("msg") or data.get("message") or str(data)
        raise RuntimeError(f"{account_label} 自动登录失败: {message}")

    user = data.get("data") or {}
    token = user.get("token")
    user_id = user.get("id") or user.get("userId")
    if not token or not user_id:
        raise RuntimeError(f"{account_label} 自动登录返回缺少 token/userId")

    print(f"{account_label} 自动登录成功，userId={mask_value(user_id, 2, 2)}，token={mask_value(token)}")
    return token, user_id, user


def is_auth_error(response_data):
    message = str(response_data.get("msg") or response_data.get("message") or response_data or "")
    return response_data.get("code") in {401, 403} or "auth" in message.lower() or "token" in message.lower()


def api_error_message(prefix, raw_message):
    raw_message = str(raw_message or "").strip()
    if "auth" in raw_message.lower():
        return f"{prefix}: 登录凭据已失效；请重新打开微信小程序并抓包更新 EFUYAO_TOKEN / EFUYAO_USER_ID"
    return f"{prefix}: {raw_message or '接口返回异常'}"


def run_account(index, token="", user_id="", login_name="", password="", login_code=""):
    if (not token or not user_id) and login_name and password:
        token, user_id, login_user = login_account(index, login_name, password, login_code)
    else:
        login_user = {}

    payload = {"token": token, "userId": int(user_id) if str(user_id).isdigit() else user_id}
    account_label = f"账号{index} userId={mask_value(user_id, 2, 2)}"
    print(f"=== {account_label} 开始 ===")

    home = request_json("/api/miniapp/user/index", payload)
    if home.get("code") != 200:
        if login_name and password and is_auth_error(home):
            message = home.get("msg") or home.get("message") or str(home)
            print(f"{account_label} 登录凭据失效，尝试自动刷新 token: {message}")
            token, user_id, login_user = login_account(index, login_name, password, login_code)
            payload = {"token": token, "userId": int(user_id) if str(user_id).isdigit() else user_id}
            account_label = f"账号{index} userId={mask_value(user_id, 2, 2)}"
            home = request_json("/api/miniapp/user/index", payload)

        if home.get("code") != 200:
            message = home.get("msg") or home.get("message") or str(home)
            message = api_error_message("首页查询失败", message)
            print(f"{account_label} {message}")
            return {
                "account": account_label,
                "success": False,
                "status": "失败",
                "message": message,
                "take_days": "-",
                "miss_days": "-",
                "last_take_days": "-",
            }

    data = home.get("data") or {}
    nick_name = data.get("nickName") or data.get("name") or login_user.get("nickname") or ""
    display_name = nick_name or account_label
    take_days = data.get("takeDays", "-")
    miss_days = data.get("missDays", "-")
    last_take_days = data.get("lastTakeDays", "-")

    if data.get("take") == 1:
        message = f"今日已服，跳过签到；已服 {take_days} 天，漏服 {miss_days} 天，连续 {last_take_days} 天"
        print(f"{account_label} {message}")
        return {
            "account": f"{display_name}（{account_label}）",
            "success": True,
            "status": "已完成",
            "message": message,
            "nick_name": nick_name,
            "take_days": take_days,
            "miss_days": miss_days,
            "last_take_days": last_take_days,
        }

    sign = request_json("/api/miniapp/user/medicationRecordTake", payload)
    if sign.get("code") != 200 and login_name and password and is_auth_error(sign):
        message = sign.get("msg") or sign.get("message") or str(sign)
        print(f"{account_label} 签到时登录凭据失效，尝试自动刷新 token: {message}")
        token, user_id, login_user = login_account(index, login_name, password, login_code)
        payload = {"token": token, "userId": int(user_id) if str(user_id).isdigit() else user_id}
        account_label = f"账号{index} userId={mask_value(user_id, 2, 2)}"
        sign = request_json("/api/miniapp/user/medicationRecordTake", payload)

    if sign.get("code") == 200:
        print(f"{account_label} 签到成功")
        final_home = request_json("/api/miniapp/user/index", payload)
        final_data = final_home.get("data") or {}
        final_nick_name = final_data.get("nickName") or final_data.get("name") or nick_name
        final_display_name = final_nick_name or display_name
        return {
            "account": f"{final_display_name}（{account_label}）",
            "success": True,
            "status": "成功",
            "message": sign.get("msg") or sign.get("message") or "签到成功",
            "nick_name": final_nick_name,
            "take_days": final_data.get("takeDays", take_days),
            "miss_days": final_data.get("missDays", miss_days),
            "last_take_days": final_data.get("lastTakeDays", last_take_days),
        }

    message = sign.get("msg") or sign.get("message") or str(sign)
    message = api_error_message("签到失败", message)
    print(f"{account_label} {message}")
    return {
        "account": f"{display_name}（{account_label}）",
        "success": False,
        "status": "失败",
        "message": message,
        "nick_name": nick_name,
        "take_days": take_days,
        "miss_days": miss_days,
        "last_take_days": last_take_days,
    }


QYWX_TOKEN_CACHE = {"token": "", "expires_at": 0}
QYWX_TEXT_LIMIT = 2048
QL_CONFIG_FILES = ("/ql/data/config/config.sh", "/ql/config/config.sh")


def config_sh_value(name):
    """青龙「系统设置/配置文件」里的变量写在 config.sh，这里直接解析兜底。"""
    for path in QL_CONFIG_FILES:
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as config_file:
                for line in config_file:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if line.startswith("export "):
                        line = line[len("export "):].strip()
                    if not line.startswith(f"{name}="):
                        continue
                    value = line.split("=", 1)[1].strip()
                    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                        value = value[1:-1]
                    if value:
                        return value
        except OSError:
            continue
    return ""


def env_or_config(name):
    return os.getenv(name, "") or config_sh_value(name)


def qywx_config():
    """读取企业微信应用配置，优先 QYWX_AM=corpid,corpsecret,touser,agentid。"""
    qywx_am = env_or_config("QYWX_AM")
    parts = [part.strip() for part in qywx_am.split(",")] if qywx_am else []
    parts += [""] * (4 - len(parts))
    corpid = parts[0] or env_or_config("QYWX_CORPID")
    corpsecret = parts[1] or env_or_config("QYWX_CORPSECRET")
    touser = parts[2] or env_or_config("QYWX_TOUSER") or "@all"
    agentid = parts[3] or env_or_config("QYWX_AGENTID")
    origin = (env_or_config("QYWX_ORIGIN") or "https://qyapi.weixin.qq.com").rstrip("/")
    if not corpid or not corpsecret or not agentid:
        return None
    return {
        "corpid": corpid,
        "corpsecret": corpsecret,
        "touser": touser,
        "agentid": int(agentid) if str(agentid).isdigit() else agentid,
        "origin": origin,
    }


def qywx_access_token(config, force_refresh=False):
    now = time.time()
    if not force_refresh and QYWX_TOKEN_CACHE["token"] and QYWX_TOKEN_CACHE["expires_at"] > now + 60:
        return QYWX_TOKEN_CACHE["token"]
    response = requests.get(
        f"{config['origin']}/cgi-bin/gettoken",
        params={"corpid": config["corpid"], "corpsecret": config["corpsecret"]},
        timeout=15,
        verify=SSL_VERIFY,
    )
    response.raise_for_status()
    data = response.json()
    if data.get("errcode") != 0:
        raise RuntimeError(f"获取 access_token 失败: {data.get('errcode')} {data.get('errmsg')}")
    QYWX_TOKEN_CACHE["token"] = data["access_token"]
    QYWX_TOKEN_CACHE["expires_at"] = now + int(data.get("expires_in") or 7200)
    return QYWX_TOKEN_CACHE["token"]


def qywx_api_post(config, url, access_token, **kwargs):
    """调用企业微信接口；access_token 失效时刷新后重试一次。"""
    data = {}
    extra_params = kwargs.pop("params", None) or {}
    for attempt in range(2):
        params = dict(extra_params, access_token=access_token)
        response = requests.post(url, params=params, timeout=30, verify=SSL_VERIFY, **kwargs)
        response.raise_for_status()
        data = response.json()
        if data.get("errcode") in (40014, 42001) and attempt == 0:
            access_token = qywx_access_token(config, force_refresh=True)
            continue
        return data, access_token
    return data, access_token


def qywx_send_text(config, access_token, content):
    data, access_token = qywx_api_post(
        config,
        f"{config['origin']}/cgi-bin/message/send",
        access_token,
        json={
            "touser": config["touser"],
            "msgtype": "text",
            "agentid": config["agentid"],
            "text": {"content": content},
            "safe": 0,
        },
    )
    if data.get("errcode") != 0:
        raise RuntimeError(f"{data.get('errcode')} {data.get('errmsg')}")
    invalid_users = data.get("invaliduser")
    if invalid_users:
        print(f"企业微信应用通知：无效成员 {invalid_users}")
    return True, access_token


def qywx_text_chunks(text, limit=QYWX_TEXT_LIMIT):
    """按 UTF-8 字节数切分文本，单条不超过企业微信文本上限，不会截断多字节字符。"""
    chunks = []
    current = ""
    current_bytes = 0
    for char in text:
        char_bytes = len(char.encode("utf-8"))
        if current and current_bytes + char_bytes > limit:
            chunks.append(current)
            current, current_bytes = "", 0
        current += char
        current_bytes += char_bytes
    if current:
        chunks.append(current)
    return chunks


def send_notify(title, content):
    """发送纯文字通知；企业微信文本上限 2048 字节，超长自动分片。"""
    config = qywx_config()
    if not config:
        print("企业微信应用通知未配置：请在青龙「系统设置-通知设置」选择企业微信应用，或设置环境变量 QYWX_AM")
        return False
    try:
        access_token = qywx_access_token(config)
    except Exception as error:
        print(f"企业微信应用通知获取 token 异常: {error}")
        return False

    try:
        chunks = qywx_text_chunks(f"{title}\n\n{content}")
        for chunk in chunks or [""]:
            _, access_token = qywx_send_text(config, access_token, chunk)
        print(f"企业微信应用文字通知发送成功（{max(1, len(chunks))} 条）")
        return True
    except Exception as error:
        print(f"企业微信应用文字通知异常: {error}")
    return False


def build_summary(results):
    lines = [f"共 {len(results)} 个账号，执行时间 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"]
    success_count = sum(1 for result in results if result.get("success"))
    for result in results:
        lines.append("")
        lines.append(f"【{result['account']}】{result['status']}")
        lines.append(f"  · 结果：{result['message']}")
        lines.append(
            f"  · 已服 {result.get('take_days', '-')} 天｜漏服 {result.get('miss_days', '-')} 天"
            f"｜连续 {result.get('last_take_days', '-')} 天"
        )
    lines.append("")
    lines.append(f"成功 {success_count} 个，失败 {len(results) - success_count} 个")

    hitokoto_content, hitokoto_source = hitokoto_parts()
    if hitokoto_content:
        lines.append("")
        lines.append(f"—— {hitokoto_content}" + (f"「{hitokoto_source}」" if hitokoto_source else ""))
    return "\n".join(lines).strip()


def main():
    tokens = split_env(os.getenv("EFUYAO_TOKEN", ""))
    user_ids = split_env(os.getenv("EFUYAO_USER_ID", ""))
    login_names = split_env(os.getenv("EFUYAO_LOGIN_NAME", ""))
    passwords = split_env(os.getenv("EFUYAO_PASSWORD", ""))
    login_codes = split_env(os.getenv("EFUYAO_LOGIN_CODE", ""))

    account_count = max(len(tokens), len(user_ids), len(login_names), len(passwords), len(login_codes))
    if account_count == 0:
        print("请至少配置 EFUYAO_TOKEN/EFUYAO_USER_ID 或 EFUYAO_LOGIN_NAME/EFUYAO_PASSWORD")
        return 1

    env_counts = {
        "EFUYAO_TOKEN": len(tokens),
        "EFUYAO_USER_ID": len(user_ids),
        "EFUYAO_LOGIN_NAME": len(login_names),
        "EFUYAO_PASSWORD": len(passwords),
        "EFUYAO_LOGIN_CODE": len(login_codes),
    }
    for name, count in env_counts.items():
        if count not in {0, account_count}:
            print(f"账号配置数量不一致: {name}={count} 个，最大账号数={account_count} 个")
            return 1

    if (tokens and not user_ids) or (user_ids and not tokens):
        print("EFUYAO_TOKEN 和 EFUYAO_USER_ID 需要成对配置；若不想维护 token，可只配置 EFUYAO_LOGIN_NAME/EFUYAO_PASSWORD")
        return 1
    if (login_names and not passwords) or (passwords and not login_names):
        print("EFUYAO_LOGIN_NAME 和 EFUYAO_PASSWORD 需要成对配置")
        return 1

    results = []
    for offset in range(account_count):
        index = offset + 1
        token = env_item(tokens, offset)
        user_id = env_item(user_ids, offset)
        login_name = env_item(login_names, offset)
        password = env_item(passwords, offset)
        login_code = env_item(login_codes, offset)
        account_hint = f"账号{index} userId={mask_value(user_id, 2, 2)}" if user_id else f"账号{index} login={mask_value(login_name, 3, 3)}"
        try:
            if (not token or not user_id) and (not login_name or not password):
                raise RuntimeError("缺少 token/userId，且未配置账号密码自动登录")
            results.append(run_account(index, token, user_id, login_name, password, login_code))
        except Exception as error:
            message = str(error)
            print(f"账号{index} 执行异常: {message}")
            results.append(
                {
                    "account": account_hint,
                    "success": False,
                    "status": "异常",
                    "message": message,
                    "take_days": "-",
                    "miss_days": "-",
                    "last_take_days": "-",
                }
            )

    title = "e服药每日签到通知"
    content = build_summary(results)
    print("\n" + content)
    send_notify(title, content)
    return 1 if any(not result.get("success") for result in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
