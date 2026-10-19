"""
飞牛 NAS 论坛签到 - 青龙脚本

环境变量:
  FNNAS_COOKIE       - 飞牛论坛 Cookie
  QYWX_AM            - 企业微信应用，格式：corpid,corpsecret,touser,agentid
  QYWX_CORPID        - 企业微信企业 ID（未配置 QYWX_AM 时使用）
  QYWX_CORPSECRET    - 企业微信应用 Secret
  QYWX_TOUSER        - 接收成员，多个用 | 分隔，默认 @all
  QYWX_AGENTID       - 企业微信应用 AgentId
  QYWX_ORIGIN        - 企业微信 API 地址，默认 https://qyapi.weixin.qq.com
  HITOKOTO           - 可选，false 时关闭每日一言
"""

import json
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

NOTIFY_TITLE = "飞牛NAS论坛签到"
HITOKOTO_CACHE = None

DEFAULT_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Priority": "u=0, i",
    "Referer": "https://club.fnnas.com/plugin.php?id=zqlj_sign",
    "Sec-CH-UA": '"Chromium";v="146", "Not-A.Brand";v="24", "Google Chrome";v="146"',
    "Sec-CH-UA-Mobile": "?0",
    "Sec-CH-UA-Platform": '"Windows"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
    "Upgrade-Insecure-Requests": "1",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36",
}


def hitokoto_parts():
    global HITOKOTO_CACHE
    if HITOKOTO_CACHE is not None:
        return HITOKOTO_CACHE
    if os.getenv("HITOKOTO", "true").lower() == "false":
        HITOKOTO_CACHE = ("", "")
        return HITOKOTO_CACHE
    try:
        response = requests.get("https://v1.hitokoto.cn/", timeout=5)
        response.raise_for_status()
        data = response.json()
        HITOKOTO_CACHE = (data.get("hitokoto", "").strip(), data.get("from", "").strip())
    except Exception as e:
        print(f"每日一语获取失败: {e}")
        HITOKOTO_CACHE = ("", "")
    return HITOKOTO_CACHE


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
        response = requests.post(url, params=params, timeout=30, **kwargs)
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
        print(f"\n===== {title} =====\n{content}")
        return False
    try:
        access_token = qywx_access_token(config)
    except Exception as e:
        print(f"企业微信应用通知获取 token 异常: {e}")
        print(f"\n===== {title} =====\n{content}")
        return False

    try:
        chunks = qywx_text_chunks(f"{title}\n\n{content}")
        for chunk in chunks or [""]:
            _, access_token = qywx_send_text(config, access_token, chunk)
        print(f"企业微信应用文字通知发送成功（{max(1, len(chunks))} 条）")
        return True
    except Exception as e:
        print(f"企业微信应用文字通知异常: {e}")
        print(f"\n===== {title} =====\n{content}")
        return False


class FnNasClub:
    name = "飞牛NAS论坛"

    def __init__(self, cookie):
        self.cookie = cookie

    @staticmethod
    def get_sign_param_from_page(session):
        response = session.get("https://club.fnnas.com/plugin.php?id=zqlj_sign", timeout=15)
        response.raise_for_status()
        html = response.text
        sign_match = re.search(r'<a href="plugin.php\?id=zqlj_sign&sign=([0-9a-fA-F]+)" class="btna">点击打卡</a>', html)
        signed_match = re.search(r'<a href="plugin.php\?id=zqlj_sign&sign=([0-9a-fA-F]+)" class="btna">今日已打卡</a>', html)
        if sign_match:
            return sign_match.group(1)
        if signed_match:
            return signed_match.group(1)
        return ""

    @staticmethod
    def sign(session, sign_param):
        if not sign_param:
            return {"name": "签到结果", "status": "失败", "value": "签到失败，未能成功获取 sign 参数"}

        sign_url = f"https://club.fnnas.com/plugin.php?id=zqlj_sign&sign={sign_param}"
        response = session.get(sign_url, headers={"Referer": sign_url}, timeout=15)
        html = response.text
        if re.search(r"恭喜您，打卡成功！", html):
            return {"name": "签到结果", "status": "成功", "value": "签到成功"}
        if re.search(r"您今天已经打过卡了，请勿重复操作！", html):
            return {"name": "签到结果", "status": "成功", "value": "您已签到，请勿重复签到"}
        return {"name": "签到结果", "status": "异常", "value": "未知签到异常"}

    @staticmethod
    def get_info(session):
        response = session.get("https://club.fnnas.com/plugin.php?id=zqlj_sign", timeout=15)
        response.raise_for_status()
        html = response.text
        try:
            pattern = re.compile(
                r"<strong>\s*我的打卡动态\s*</strong>.*?" r'<div[^>]*class="bm_c"[^>]*>.*?</div>',
                re.S,
            )
            match = pattern.search(html)
            if not match:
                raise RuntimeError("没匹配到“我的打卡动态”")
            block_html = re.sub(r"</li\s*>", "</li>\n", match.group(0))
            text = re.sub(r"<[^>]+>", "", block_html).replace("我的打卡动态", "")
            rows = []
            for line in [line.strip() for line in text.splitlines() if line.strip()]:
                if "：" in line:
                    name, value = line.split("：", 1)
                elif ":" in line:
                    name, value = line.split(":", 1)
                else:
                    continue
                rows.append({"name": name.strip(), "status": "信息", "value": value.strip()})
            return rows
        except Exception as e:
            return [{"name": "获取打卡动态", "status": "异常", "value": str(e)}]

    def main(self):
        session = requests.Session()
        headers = DEFAULT_HEADERS.copy()
        headers["Cookie"] = self.cookie
        session.headers.update(headers)
        sign_param = self.get_sign_param_from_page(session)
        rows = [self.sign(session, sign_param)]
        rows.extend(self.get_info(session))
        return rows


def load_cookie_from_config():
    config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config.json")
    if not os.path.exists(config_path):
        return ""
    try:
        with open(config_path, encoding="utf-8") as file:
            data = json.loads(file.read())
        items = data.get("FNNASCLUB", [])
        if items:
            return items[0].get("cookie", "")
    except Exception as e:
        print(f"读取 config.json 失败: {e}")
    return ""


def cookie_value():
    return os.getenv("FNNAS_COOKIE", "").strip() or os.getenv("FNNASCLUB_COOKIE", "").strip() or load_cookie_from_config()


def rows_to_text(rows):
    return "\n".join(f"{row.get('name')}: {row.get('value')}" for row in rows)


def build_summary(rows):
    lines = [f"飞牛NAS论坛签到　{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"]
    for row in rows:
        lines.append("")
        lines.append(f"【{row.get('name', '-')}】{row.get('status', '信息')}")
        lines.append(f"  · {row.get('value', '-')}")
    success_count = sum(1 for row in rows if row.get("status") == "成功")
    abnormal_count = sum(1 for row in rows if row.get("status") in ("失败", "异常"))
    lines.append("")
    lines.append(f"成功 {success_count} 项，异常 {abnormal_count} 项")

    hitokoto_content, hitokoto_source = hitokoto_parts()
    if hitokoto_content:
        lines.append("")
        lines.append(f"—— {hitokoto_content}" + (f"「{hitokoto_source}」" if hitokoto_source else ""))
    return "\n".join(lines).strip()


def main():
    cookie = cookie_value()
    if not cookie:
        rows = [{"name": "配置检查", "status": "异常", "value": "未设置 FNNAS_COOKIE"}]
        print(rows_to_text(rows))
        send_notify(NOTIFY_TITLE, build_summary(rows))
        return 1

    try:
        rows = FnNasClub(cookie).main()
    except Exception as exc:
        rows = [{"name": "执行结果", "status": "异常", "value": f"执行异常: {exc}"}]
        print(rows_to_text(rows))
        send_notify(NOTIFY_TITLE, build_summary(rows))
        return 1

    print(rows_to_text(rows))
    send_notify(NOTIFY_TITLE, build_summary(rows))
    return 1 if any(row.get("status") in ("失败", "异常") for row in rows) else 0


if __name__ == "__main__":
    raise SystemExit(main())
