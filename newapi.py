"""
New API 通用签到（支持多站点）

环境变量:
  NEW_API_TOKENS   - JSON 数组，每个元素含 name / website / user / session：
                     [{"name":"站点A","website":"https://a.example.com","user":"1234","session":"xxxx"}]
  QYWX_AM          - 企业微信应用，格式：corpid,corpsecret,touser,agentid
  QYWX_CORPID      - 企业微信企业 ID（未配置 QYWX_AM 时使用）
  QYWX_CORPSECRET  - 企业微信应用 Secret
  QYWX_TOUSER      - 接收成员，多个用 | 分隔，默认 @all
  QYWX_AGENTID     - 企业微信应用 AgentId
  QYWX_ORIGIN      - 企业微信 API 地址，默认 https://qyapi.weixin.qq.com
  HITOKOTO         - 是否在通知末尾附加每日一言，默认 true
"""

import json
import os
import time
from datetime import datetime

import requests

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    pass

HITOKOTO_CACHE = None


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



class L:
    def __init__(self, name) -> None:
        self.name = name if name else "unknown"
        self.logs = []

    def info(self, *args):
        message = " ".join(str(arg) for arg in args)
        text = f"【{self.name}】{message}"
        print(text)
        self.logs.append(text)

    @property
    def log(self):
        return "\n".join(self.logs)


def checkin(session: str, user: str, website: str, l: L):
    result = {"name": l.name, "status": "异常", "quota_text": "-", "message": "未知异常"}
    try:
        response = requests.post(
            f"{website}/api/user/checkin",
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
                "Accept": "application/json, text/plain, */*",
                "origin": website,
                "new-api-user": user,
                "referer": f"{website}/console/personal",
                "Cookie": f"session={session}",
            },
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        success = data.get("success", False)
        message = data.get("message", "unknown")
        quota = int(data.get("data", {}).get("quota_awarded", 0))
        usd = quota / 500000

        if success:
            result = {
                "name": l.name,
                "status": "成功",
                "quota_text": f"{usd:.4f}$",
                "message": f"获得额度: {quota} quota，约 ${usd:.4f}",
            }
            l.info(f"签到成功 | 获得额度: {quota} quota | 约 ${usd:.4f}")
        else:
            result = {
                "name": l.name,
                "status": "失败",
                "quota_text": "-",
                "message": message,
            }
            l.info(f"签到失败: {message}")
    except ValueError:
        result = {
            "name": l.name,
            "status": "异常",
            "quota_text": "-",
            "message": f"JSON解析失败: {response.text[:200]}",
        }
        l.info(result["message"])
    except Exception as e:
        result = {
            "name": l.name,
            "status": "异常",
            "quota_text": "-",
            "message": str(e),
        }
        l.info(f"签到异常: {e}")
    return result


def build_summary(results):
    success_count = sum(1 for item in results if item.get("status") == "成功")
    lines = [f"共 {len(results)} 个站点，执行时间 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"]
    for item in results:
        lines.append("")
        lines.append(f"【{item.get('name', '未知站点')}】{item.get('status', '异常')}")
        detail = item.get("message", "-")
        quota_text = item.get("quota_text", "-")
        if quota_text and quota_text != "-":
            detail = f"{detail}（{quota_text}）"
        lines.append(f"  · {detail}")
    lines.append("")
    lines.append(f"成功 {success_count} 个，失败/异常 {len(results) - success_count} 个")

    hitokoto_content, hitokoto_source = hitokoto_parts()
    if hitokoto_content:
        lines.append("")
        lines.append(f"—— {hitokoto_content}" + (f"「{hitokoto_source}」" if hitokoto_source else ""))
    return "\n".join(lines).strip()


def main():
    env_name = "NEW_API_TOKENS"
    results = []

    raw = os.getenv(env_name)
    if not raw:
        print(f"未获取到ck变量：请检查变量 {env_name} 是否填写")
        exit(0)

    items: list[dict] = json.loads(raw)
    for item in items:
        l = L(item.get("name", ""))
        results.append(checkin(
            item.get("session", ""), item.get("user", ""), item.get("website", ""), l
        ))
    send_notify("NewAPI 签到", build_summary(results))


if __name__ == "__main__":
    main()
