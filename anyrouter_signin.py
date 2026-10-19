#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
anyrouter.top 自动签到（青龙面板版，支持多账号）

new Env('anyrouter签到')
cron: 5 8 * * *

============ 环境变量配置 ============
1. ANYROUTER_ACCOUNTS（必填）：JSON 数组，单行，每个元素含 user_id，以及
   access_token 与 cookie 至少一项：
   [{"user_id":"165045","access_token":"iLp0Wm...","cookie":"session=abcd..."}]

   * access_token（推荐）：长效凭证，不像 session 那样几天就过期，配一次可长期用。
     获取：登录 anyrouter.top -> F12 -> Network -> /api/user/self 响应里的
     access_token 字段；若为 null，去「个人设置」里生成/重置系统访问令牌。
   * cookie：登录后的 session，会较快过期。没有 access_token 时用它兜底。
   * 两者都填时优先用 access_token 认证，cookie 仅用于辅助（如 WAF）。

2. ANYROUTER_PROXY（按需）：代理地址，如 http://127.0.0.1:7890。
   国内直连 anyrouter.top 常被 TLS 重置，若签到报网络错误请配置可达的代理；
   若青龙主机本身能直连（海外/已走网关代理）可不填。

3. 企业微信应用通知（按需）：
   QYWX_AM=corpid,corpsecret,touser,agentid
   也可分开配置 QYWX_CORPID / QYWX_CORPSECRET / QYWX_TOUSER / QYWX_AGENTID，
   或直接在青龙「系统设置-通知设置」里选择企业微信应用并填写（脚本会读取 config.sh）。
   QYWX_ORIGIN 可指定企业微信代理地址，默认 https://qyapi.weixin.qq.com
"""

import gzip
import json
import os
import random
import re
import sys
import time
import zlib
from datetime import datetime
from urllib import request, error
from urllib.parse import urlencode

# 保证在任何平台（含 Windows GBK 控制台）都能输出 emoji/中文
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

QYWX_TOKEN_CACHE = {"token": "", "expires_at": 0}
QYWX_TEXT_LIMIT = 2048
QL_CONFIG_FILES = ("/ql/data/config/config.sh", "/ql/config/config.sh")
# 企业微信 API 直连（不走 ANYROUTER_PROXY，否则出口 IP 与可信 IP 白名单不一致）
QYWX_OPENER = request.build_opener(request.ProxyHandler({}))


def config_sh_value(name: str) -> str:
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


def env_or_config(name: str) -> str:
    return os.environ.get(name, "") or config_sh_value(name)


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


def _qywx_http(url: str, payload=None, params=None, timeout: int = 20) -> dict:
    if params:
        url = f"{url}?{urlencode(params)}"
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST" if data is not None else "GET",
    )
    with QYWX_OPENER.open(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def qywx_access_token(config, force_refresh: bool = False) -> str:
    now = time.time()
    if not force_refresh and QYWX_TOKEN_CACHE["token"] and QYWX_TOKEN_CACHE["expires_at"] > now + 60:
        return QYWX_TOKEN_CACHE["token"]
    data = _qywx_http(
        f"{config['origin']}/cgi-bin/gettoken",
        params={"corpid": config["corpid"], "corpsecret": config["corpsecret"]},
    )
    if data.get("errcode") != 0:
        raise RuntimeError(f"获取 access_token 失败: {data.get('errcode')} {data.get('errmsg')}")
    QYWX_TOKEN_CACHE["token"] = data["access_token"]
    QYWX_TOKEN_CACHE["expires_at"] = now + int(data.get("expires_in") or 7200)
    return QYWX_TOKEN_CACHE["token"]


def qywx_send_text(config, access_token: str, content: str) -> str:
    url = f"{config['origin']}/cgi-bin/message/send?{urlencode({'access_token': access_token})}"
    data = _qywx_http(
        url,
        payload={
            "touser": config["touser"],
            "msgtype": "text",
            "agentid": config["agentid"],
            "text": {"content": content},
            "safe": 0,
        },
    )
    if data.get("errcode") in (40014, 42001):
        access_token = qywx_access_token(config, force_refresh=True)
        url = f"{config['origin']}/cgi-bin/message/send?{urlencode({'access_token': access_token})}"
        data = _qywx_http(
            url,
            payload={
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
    return access_token


def qywx_text_chunks(text: str, limit: int = QYWX_TEXT_LIMIT):
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


def send_notify(title: str, content: str) -> bool:
    """发送纯文字通知；企业微信文本上限 2048 字节，超长自动分片。"""
    config = qywx_config()
    if not config:
        print("企业微信应用通知未配置：请在青龙「系统设置-通知设置」选择企业微信应用，或设置环境变量 QYWX_AM")
        print(f"\n===== {title} =====\n{content}")
        return False
    try:
        access_token = qywx_access_token(config)
    except Exception as exc:  # noqa: BLE001
        print(f"企业微信应用通知获取 token 异常: {exc}")
        print(f"\n===== {title} =====\n{content}")
        return False

    try:
        chunks = qywx_text_chunks(f"{title}\n\n{content}")
        for chunk in chunks or [""]:
            access_token = qywx_send_text(config, access_token, chunk)
        print(f"企业微信应用文字通知发送成功（{max(1, len(chunks))} 条）")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"企业微信应用文字通知异常: {exc}")
        print(f"\n===== {title} =====\n{content}")
        return False


def send(title: str, content: str) -> bool:
    return send_notify(title, content)


BASE_URL = "https://anyrouter.top"
SIGN_IN_PATH = "/api/user/sign_in"
SELF_PATH = "/api/user/self"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36"
)

ENV_NAME = "ANYROUTER_ACCOUNTS"
PROXY_ENV = "ANYROUTER_PROXY"
SLEEP_SECONDS = 5  # 多账号之间的间隔，避免请求过密触发风控

# ---- 阿里云 WAF acw_sc__v2 反爬挑战求解 ----
# 首次请求会返回一段混淆 JS（含 var arg1='...'），浏览器需执行后算出
# acw_sc__v2 cookie 再重放。算法确定性，纯 Python 复现：
#   1. 按固定位置表 _ACW_POS 对 arg1 做 unsbox 重排
#   2. 与固定密钥 _ACW_KEY 逐字节十六进制异或
_ACW_POS = [
    0xF, 0x23, 0x1D, 0x18, 0x21, 0x10, 0x1, 0x26, 0xA, 0x9, 0x13, 0x1F,
    0x28, 0x1B, 0x16, 0x17, 0x19, 0xD, 0x6, 0xB, 0x27, 0x12, 0x14, 0x8,
    0xE, 0x15, 0x20, 0x1A, 0x2, 0x1E, 0x7, 0x4, 0x11, 0x5, 0x3, 0x1C,
    0x22, 0x25, 0xC, 0x24,
]
_ACW_KEY = "3000176000856006061501533003690027800375"


def solve_acw_sc_v2(arg1: str) -> str:
    """由挑战页里的 arg1 计算 acw_sc__v2 cookie 值。"""
    unboxed = [""] * len(_ACW_POS)
    for i, p in enumerate(_ACW_POS):
        if p - 1 < len(arg1):
            unboxed[i] = arg1[p - 1]
    unboxed = "".join(unboxed)
    result = []
    for i in range(0, len(unboxed), 2):
        a = int(unboxed[i:i + 2], 16)
        b = int(_ACW_KEY[i:i + 2], 16)
        result.append("%02x" % (a ^ b))
    return "".join(result)


def build_opener() -> request.OpenerDirector:
    """构造 urllib opener。优先用 ANYROUTER_PROXY，其次标准 HTTPS_PROXY/HTTP_PROXY。"""
    proxy = (
        os.environ.get(PROXY_ENV)
        or os.environ.get("HTTPS_PROXY")
        or os.environ.get("https_proxy")
        or os.environ.get("HTTP_PROXY")
        or os.environ.get("http_proxy")
    )
    if proxy:
        proxy = proxy.strip()
        print(f"[网络] 使用代理: {proxy}")
        return request.build_opener(request.ProxyHandler({"http": proxy, "https": proxy}))
    return request.build_opener(request.ProxyHandler({}))


OPENER = build_opener()


def build_headers(user_id: str, access_token: str = "") -> dict:
    headers = {
        "accept": "application/json, text/plain, */*",
        "accept-language": "zh-CN,zh;q=0.9,en-CN;q=0.8,en;q=0.7",
        "cache-control": "no-store",
        "new-api-user": str(user_id),
        "origin": BASE_URL,
        "referer": f"{BASE_URL}/console",
        "user-agent": USER_AGENT,
    }
    # new-api 支持用系统访问令牌免 cookie 认证：Authorization 头带 access_token
    if access_token:
        headers["authorization"] = access_token
    return headers


def parse_cookie_str(cookie: str) -> dict:
    """把 'a=1; b=2' 形式的 Cookie 串解析成 dict。"""
    jar = {}
    for part in cookie.split(";"):
        part = part.strip()
        if "=" in part:
            k, v = part.split("=", 1)
            jar[k.strip()] = v.strip()
    return jar


def _cookie_header(jar: dict) -> str:
    return "; ".join(f"{k}={v}" for k, v in jar.items() if v)


def _parse_set_cookie(resp_headers) -> dict:
    """从响应 Set-Cookie 头取出 name=value（如 WAF 下发的 acw_tc）。"""
    out = {}
    for hdr in resp_headers.get_all("Set-Cookie") or []:
        first = hdr.split(";", 1)[0]
        if "=" in first:
            k, v = first.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def _decode_body(body: bytes, encoding: str) -> str:
    """按 Content-Encoding 解压响应体。"""
    encoding = (encoding or "").lower().strip()
    if encoding == "gzip":
        body = gzip.decompress(body)
    elif encoding == "deflate":
        try:
            body = zlib.decompress(body)
        except zlib.error:
            body = zlib.decompress(body, -zlib.MAX_WBITS)
    return body.decode("utf-8", errors="replace")


def _raw_request(method: str, url: str, headers: dict, jar: dict, timeout: int = 45):
    """发一次请求，返回 (响应文本, 新增 cookie)。"""
    data = b"" if method == "POST" else None
    hdrs = {**headers, "accept-encoding": "gzip, deflate", "cookie": _cookie_header(jar)}
    req = request.Request(url, data=data, headers=hdrs, method=method)
    try:
        with OPENER.open(req, timeout=timeout) as resp:
            text = _decode_body(resp.read(), resp.headers.get("Content-Encoding"))
            return text, _parse_set_cookie(resp.headers)
    except error.HTTPError as e:
        body = _decode_body(e.read(), e.headers.get("Content-Encoding"))
        return body, _parse_set_cookie(e.headers)
    except error.URLError as e:
        raise RuntimeError(f"网络错误: {e.reason}") from e
    except TimeoutError as e:
        raise RuntimeError(f"网络错误: 请求超时 ({timeout}s)") from e


WAF_MAX_RETRY = 5  # 命中 WAF 挑战页时的最大重试次数


def _is_waf_challenge(text: str) -> bool:
    """判断响应是否为阿里云 WAF 挑战页（新版 aliyun_waf 或旧版 arg1）。"""
    head = (text or "")[:800]
    return "aliyun_waf" in head or "arg1=" in head.replace(" ", "") or "acw_sc__v2" in head


def warm_waf_cookies(jar: dict) -> None:
    """预热站点，尽量先拿到 acw_tc 等 WAF cookie，降低首个 API 直接被挑战概率。"""
    try:
        headers = {
            "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "accept-language": "zh-CN,zh;q=0.9,en;q=0.8",
            "user-agent": USER_AGENT,
        }
        text, new_cookies = _raw_request("GET", BASE_URL + "/", headers, jar, timeout=30)
        jar.update(new_cookies)
        m = re.search(r"arg1\s*=\s*'([0-9A-Fa-f]+)'", text)
        if m:
            jar["acw_sc__v2"] = solve_acw_sc_v2(m.group(1))
            _, new_cookies = _raw_request("GET", BASE_URL + "/", headers, jar, timeout=30)
            jar.update(new_cookies)
    except RuntimeError as e:
        print(f"[WAF] 预热失败（将继续直接请求 API）: {e}")


def http_json(method: str, url: str, headers: dict, jar: dict) -> dict:
    """发起请求并解析 JSON。

    遇到 WAF 挑战页时：
      - 旧版 acw_sc__v2（含 arg1='...'）：纯 Python 求解后重试
      - 新版按风险间歇触发：吸收 acw_tc 后退避重试
    """
    text = ""
    for attempt in range(WAF_MAX_RETRY):
        text, new_cookies = _raw_request(method, url, headers, jar)
        jar.update(new_cookies)

        # 旧版挑战：含 arg1='...'，可纯 Python 求解 acw_sc__v2
        m = re.search(r"arg1\s*=\s*'([0-9A-Fa-f]+)'", text)
        if m:
            jar["acw_sc__v2"] = solve_acw_sc_v2(m.group(1))
            if attempt < WAF_MAX_RETRY - 1:
                time.sleep(0.4 + random.uniform(0, 0.4))
            continue

        if _is_waf_challenge(text):
            if attempt < WAF_MAX_RETRY - 1:
                time.sleep(1.5 * (attempt + 1) + random.uniform(0, 1))
            continue

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            raise RuntimeError(f"响应非 JSON（可能登录失效或反爬拦截）: {text[:200]}")

    raise RuntimeError(f"多次重试后仍被 WAF 拦截: {text[:200]}")


def quota_to_usd(quota) -> str:
    """new-api 里 quota 单位为 1 美元 = 500000。"""
    try:
        return f"${quota / 500000:.2f}"
    except (TypeError, ValueError):
        return str(quota)


def parse_accounts(raw: str):
    """解析 JSON 数组配置为 [(user_id, cookie, access_token), ...]。

    每个账号需有 user_id，且 cookie 与 access_token 至少提供其一：
      - access_token（推荐）：长效，不会像 session 那样很快过期
      - cookie：浏览器登录后的 session，会过期，需定期重抓
    """
    try:
        data = json.loads(raw.strip())
    except json.JSONDecodeError as e:
        print(f"[配置] JSON 解析失败，请使用数组格式 [{{...}}]: {e}")
        return []
    if not isinstance(data, list):
        print("[配置] 配置必须是 JSON 数组 [{...}]。")
        return []

    accounts = []
    for idx, item in enumerate(data, 1):
        if not isinstance(item, dict):
            print(f"[配置] 第 {idx} 项不是对象，已跳过。")
            continue
        user_id = str(item.get("user_id") or item.get("id") or item.get("uid") or "").strip()
        cookie = str(item.get("cookie") or item.get("session") or "").strip()
        access_token = str(item.get("access_token") or item.get("token") or "").strip()
        if not user_id:
            print(f"[配置] 第 {idx} 项缺少 user_id，已跳过。")
            continue
        if not cookie and not access_token:
            print(f"[配置] 第 {idx} 项 cookie 与 access_token 均为空，已跳过。")
            continue
        accounts.append((user_id, cookie, access_token))
    return accounts


def fetch_balance(headers: dict, jar: dict):
    """查询额度，返回 (显示名, 描述)；失败返回 (None, 提示)。"""
    try:
        result = http_json("GET", BASE_URL + SELF_PATH, headers, jar)
    except RuntimeError as e:
        return None, f"额度查询失败: {e}"

    if not result.get("success"):
        return None, f"额度查询失败: {result.get('message', '未知错误')}"

    data = result.get("data", {})
    name = data.get("display_name") or data.get("username") or "未知用户"
    desc = f"剩余 {quota_to_usd(data.get('quota'))} | 已用 {quota_to_usd(data.get('used_quota'))}"
    return name, desc


def process_account(index: int, user_id: str, cookie: str, access_token: str = "") -> str:
    """处理单个账号，返回用于通知的一段文本。"""
    headers = build_headers(user_id, access_token)
    jar = parse_cookie_str(cookie)  # 每个账号独立 cookie jar
    # 先预热 WAF cookie，再查额度/签到，减少首包直接撞挑战页
    warm_waf_cookies(jar)
    name, balance_desc = fetch_balance(headers, jar)
    prefix = f"账号{index}[{name or ('用户' + user_id)}]"

    if name is None:
        line = f"{prefix} ⚠️ {balance_desc}"  # 额度查不到，通常 Cookie 失效
        print(line)
        return line

    try:
        result = http_json("POST", BASE_URL + SIGN_IN_PATH, headers, jar)
    except RuntimeError as e:
        line = f"{prefix} ❌ 签到出错: {e} | {balance_desc}"
        print(line)
        return line

    # 签到可能会增加额度；重新查询一次，避免通知显示签到前的旧余额。
    refreshed_name, refreshed_balance_desc = fetch_balance(headers, jar)
    if refreshed_name is not None:
        balance_desc = refreshed_balance_desc

    if result.get("success"):
        status, message = "✅", result.get("message") or "签到成功"
    else:
        status, message = "ℹ️", result.get("message") or "已签到或未成功"
    line = f"{prefix} {status} {message} | {balance_desc}"
    print(line)
    return line


def build_summary(results: list[dict]) -> str:
    success_count = sum(1 for item in results if item.get("status") == "成功")
    lines = [f"共 {len(results)} 个账号，执行时间 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"]
    for item in results:
        lines.append("")
        lines.append(f"【{item.get('name', '未知账号')}】{item.get('status', '异常')}")
        lines.append(f"  · {item.get('message', '-')}")
    lines.append("")
    lines.append(f"成功 {success_count} 个，失败/异常 {len(results) - success_count} 个")
    return "\n".join(lines).strip()


def main() -> int:
    raw = os.environ.get(ENV_NAME, "").strip()
    if not raw:
        msg = f"未配置环境变量 {ENV_NAME}。请填入 JSON 数组：[{{\"user_id\":\"165045\",\"access_token\":\"xxx\"}}]"
        print(msg, file=sys.stderr)
        send("anyrouter签到", msg)
        return 2

    accounts = parse_accounts(raw)
    if not accounts:
        msg = f"{ENV_NAME} 已配置，但没有解析出有效账号，请检查格式。"
        print(msg, file=sys.stderr)
        send("anyrouter签到", msg)
        return 2

    print(f"共 {len(accounts)} 个账号，开始签到...")
    lines = []
    results = []
    for i, (uid, ck, tok) in enumerate(accounts, 1):
        if i > 1:
            time.sleep(SLEEP_SECONDS)  # 账号之间间隔，避免请求过密
        line = process_account(i, uid, ck, tok)
        lines.append(line)
        status = "成功" if "✅" in line else ("异常" if "⚠️" in line or "❌" in line else "失败")
        results.append({
            "name": f"账号{i}[{uid}]",
            "status": status,
            "quota_text": "-",
            "message": line,
        })
    send("anyrouter签到", build_summary(results))
    return 0


if __name__ == "__main__":
    sys.exit(main())
