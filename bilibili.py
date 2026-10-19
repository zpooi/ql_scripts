"""
Bilibili 青龙签到脚本
环境变量:
  BILIBILI_COOKIE      - B站 Cookie，多账号用 ### 分隔
  TASK_CONFIG          - 任务列表：manga_sign,share_video,add_coin；live_sign 已失效，脚本会自动忽略
  COIN_ADD_NUM         - 每日投币数量，默认 1，填 0 跳过
  COIN_SELECT_LIKE     - 投币时是否点赞，1 是，0 否
  COIN_VIDEO_SOURCE    - 投币视频来源：dynamic 或 ranking
  WATCH_SECONDS        - 观看视频上报秒数，默认 30
  QYWX_AM              - 企业微信应用，格式：corpid,corpsecret,touser,agentid
  QYWX_CORPID          - 企业微信企业 ID（未配置 QYWX_AM 时使用）
  QYWX_CORPSECRET      - 企业微信应用 Secret
  QYWX_TOUSER          - 接收成员，多个用 | 分隔，默认 @all
  QYWX_AGENTID         - 企业微信应用 AgentId
  QYWX_ORIGIN          - 企业微信 API 地址，默认 https://qyapi.weixin.qq.com
  HITOKOTO             - 是否在通知末尾附带每日一语，默认 true
"""

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
IGNORE_FAIL_KEYWORDS = ["未配置", "跳过", "已下线"]


class BilibiliTask:
    def __init__(self, cookie):
        self.cookie = cookie
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/86.0.4240.198 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Referer": "https://www.bilibili.com/",
            "Cookie": cookie,
        }
        self.csrf = self._get_csrf()

    def _get_csrf(self):
        for item in self.cookie.split(";"):
            item = item.strip()
            if item.startswith("bili_jct"):
                return item.split("=", 1)[1]
        return None

    def get_user_info(self):
        try:
            response = requests.get("https://api.bilibili.com/x/web-interface/nav", headers=self.headers, timeout=20)
            response.raise_for_status()
            data = response.json()
            if data.get("code") == 0:
                return data.get("data") or {}
            print(f"获取用户信息失败: {data.get('message')}")
        except Exception as e:
            print(f"请求用户信息API异常: {e}")
        return None

    def get_dynamic_videos(self):
        try:
            response = requests.get("https://api.bilibili.com/x/web-interface/dynamic/region?ps=5&rid=1", headers=self.headers, timeout=20)
            response.raise_for_status()
            data = response.json()
            if data.get("code") == 0:
                return [video["bvid"] for video in data.get("data", {}).get("archives", []) if video.get("bvid")]
        except Exception as e:
            print(f"请求动态视频API异常: {e}")
        return []

    def get_ranking_videos(self):
        try:
            response = requests.get("https://api.bilibili.com/x/web-interface/ranking/v2?rid=0&type=all", headers=self.headers, timeout=20)
            response.raise_for_status()
            data = response.json()
            if data.get("code") == 0:
                return [video["bvid"] for video in data.get("data", {}).get("list", []) if video.get("bvid")]
        except Exception as e:
            print(f"请求排行榜视频API异常: {e}")
        return []

    def get_video_title(self, bvid):
        try:
            response = requests.get(
                f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}",
                headers=self.headers,
                timeout=20,
            )
            response.raise_for_status()
            data = response.json()
            if data.get("code") == 0:
                return data.get("data", {}).get("title") or bvid
        except Exception as e:
            print(f"请求视频信息API异常: {e}")
        return bvid

    def add_coin(self, bvid, num=1, select_like=1):
        if not self.csrf:
            return False, "bili_jct(csrf) 未找到"
        try:
            response = requests.post(
                "https://api.bilibili.com/x/web-interface/coin/add",
                headers=self.headers,
                data={"bvid": bvid, "multiply": num, "select_like": select_like, "csrf": self.csrf},
                timeout=20,
            )
            data = response.json()
            if data.get("code") == 0:
                return True, "投币成功"
            return False, data.get("message", "投币失败")
        except Exception as e:
            return False, str(e)

    def share_video(self, bvid):
        if not self.csrf:
            return False, "bili_jct(csrf) 未找到"
        try:
            response = requests.post(
                "https://api.bilibili.com/x/web-interface/share/add",
                headers=self.headers,
                data={"bvid": bvid, "csrf": self.csrf},
                timeout=20,
            )
            data = response.json()
            if data.get("code") == 0:
                return True, "分享成功"
            return False, data.get("message", "分享失败")
        except Exception as e:
            return False, str(e)

    def watch_video(self, bvid, played_time=30, title=None):
        video_title = title or bvid
        try:
            response = requests.post(
                "https://api.bilibili.com/x/click-interface/web/heartbeat",
                headers=self.headers,
                data={"bvid": bvid, "played_time": played_time, "csrf": self.csrf},
                timeout=20,
            )
            data = response.json()
            detail = f"{video_title}（{bvid}），观看 {played_time} 秒"
            if data.get("code") == 0:
                return True, detail
            return False, f"{data.get('message', '观看失败')}；{detail}"
        except Exception as e:
            return False, str(e)

    def live_sign(self):
        try:
            response = requests.get("https://api.live.bilibili.com/xlive/web-ucenter/v1/sign/DoSign", headers=self.headers, timeout=20)
            data = response.json()
            if data.get("code") == 0:
                return True, data.get("data", {}).get("text", "直播签到成功")
            return False, data.get("message", "直播签到失败")
        except Exception as e:
            return False, str(e)

    def manga_sign(self):
        try:
            headers = dict(self.headers)
            headers["Referer"] = "https://manga.bilibili.com/"
            headers["Origin"] = "https://manga.bilibili.com"
            response = requests.post(
                "https://manga.bilibili.com/twirp/activity.v1.Activity/ClockIn",
                headers=headers,
                data={"platform": "ios"},
                timeout=20,
            )
            data = response.json()
            code = data.get("code")
            message = str(data.get("msg") or data.get("message") or "")
            if code == 0:
                return True, "漫画签到成功"
            # 已签到：接口返回非 0，msg 含 duplicate，视为成功
            if "duplicate" in message.lower() or "重复" in message or "已签到" in message or "已经签到" in message:
                return True, "今日已签到"
            print(f"漫画签到接口返回: code={code}, msg={message or data}")
            return False, message or "漫画签到失败"
        except Exception as e:
            return False, str(e)


def mask_string(value):
    value = str(value or "")
    if not value:
        return "账号"
    if len(value) <= 2:
        return value[0] + "*"
    return value[0] + "*" * (len(value) - 2) + value[-1]


def mask_uid(uid):
    uid = str(uid or "")
    if len(uid) <= 2:
        return uid[:1] + "*"
    return uid[:2] + "*" * (len(uid) - 2)


def env_int(name, default):
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def is_skip_message(message):
    return bool(message and any(keyword in message for keyword in IGNORE_FAIL_KEYWORDS))


def execute_coin_task(bili, user_info, config):
    coins_to_add = int(config["COIN_ADD_NUM"])
    if coins_to_add <= 0:
        return True, "配置为0，跳过"

    coin_balance = user_info.get("money", 0) or 0
    if coin_balance < 1:
        return True, f"硬币不足({coin_balance})，跳过"

    coins_to_add = min(coins_to_add, int(coin_balance), 5)
    # 按配置优先级取视频，任一来源为空则自动回退，最后兜底一个固定视频
    if config["COIN_VIDEO_SOURCE"] == "ranking":
        sources = [("排行榜", bili.get_ranking_videos), ("动态", bili.get_dynamic_videos)]
    else:
        sources = [("动态", bili.get_dynamic_videos), ("排行榜", bili.get_ranking_videos)]

    video_list = []
    for source_name, fetch in sources:
        print(f"尝试获取{source_name}视频作为投币目标")
        video_list = fetch()
        if video_list:
            print(f"使用{source_name}视频，共 {len(video_list)} 个")
            break

    if not video_list:
        video_list = ["BV1GJ411x7h7"]
        print("视频列表获取失败，使用兜底视频")

    added_coins = 0
    for bvid in video_list:
        if added_coins >= coins_to_add:
            break
        success, message = bili.add_coin(bvid, 1, int(config["COIN_SELECT_LIKE"]))
        if success:
            added_coins += 1
            print(f"为视频 {bvid} 投币成功")
        elif "已达到" in message:
            print("今日投币上限已满，终止投币")
            break
        else:
            print(f"为视频 {bvid} 投币失败: {message}")
            if "硬币不足" in message:
                break
    return True, f"投币 {added_coins} 枚"


def level_metrics(user_info, tasks, config):
    level_info = user_info.get("level_info", {}) if user_info else {}
    current_exp = int(level_info.get("current_exp") or 0)
    next_exp = int(level_info.get("next_exp") or 0)
    current_level = level_info.get("current_level", "-")
    remaining_exp = max(0, next_exp - current_exp) if next_exp else 0

    daily_exp = 0
    watch_result = tasks.get("观看视频")
    if watch_result and watch_result[0]:
        daily_exp += 5
    share_result = tasks.get("分享视频")
    if share_result and share_result[0]:
        daily_exp += 5
    coin_result = tasks.get("投币任务")
    if coin_result and coin_result[0]:
        try:
            coin_count = int((coin_result[1] or "").split("投币 ", 1)[1].split(" 枚", 1)[0])
        except Exception:
            coin_count = int(config.get("COIN_ADD_NUM", 0))
        daily_exp += max(0, coin_count) * 10

    if daily_exp <= 0:
        daily_exp = 5 + (5 if "share_video" in config.get("TASK_CONFIG", "") else 0) + int(config.get("COIN_ADD_NUM", 0)) * 10
    days = (remaining_exp + daily_exp - 1) // daily_exp if remaining_exp and daily_exp else 0
    return {
        "level": current_level,
        "current_exp": current_exp,
        "next_exp": next_exp,
        "remaining_exp": remaining_exp,
        "daily_exp": daily_exp,
        "days": days,
    }


def run_account(cookie, account_index, config):
    bili = BilibiliTask(cookie)
    user_info = bili.get_user_info()
    if not user_info:
        print(f"[账号{account_index}] 登录检查失败")
        return {
            "account_index": account_index,
            "user_info": None,
            "tasks": {"登录检查": (False, "Cookie失效或网络问题")},
            "failed": True,
        }

    account_name = mask_string(user_info.get("uname"))
    print(f"[账号{account_index}] 账号名称: {account_name}")
    tasks_to_run = [task.strip() for task in config["TASK_CONFIG"].split(",") if task.strip()]
    if not tasks_to_run:
        tasks_to_run = ["manga_sign", "share_video", "add_coin"]
    if "live_sign" in tasks_to_run:
        print("直播签到已失效，自动跳过")
        tasks_to_run = [task for task in tasks_to_run if task != "live_sign"]

    video_list = bili.get_ranking_videos() or bili.get_dynamic_videos()
    bvid_for_task = video_list[0] if video_list else "BV1GJ411x7h7"
    video_title = bili.get_video_title(bvid_for_task)
    watch_seconds = int(config.get("WATCH_SECONDS", 30))
    tasks = {}

    if "share_video" in tasks_to_run:
        tasks["分享视频"] = bili.share_video(bvid_for_task)
    if "live_sign" in tasks_to_run:
        tasks["直播签到"] = bili.live_sign()
    if "manga_sign" in tasks_to_run:
        tasks["漫画签到"] = bili.manga_sign()
    if "add_coin" in tasks_to_run:
        tasks["投币任务"] = execute_coin_task(bili, user_info, config)
    tasks["观看视频"] = bili.watch_video(bvid_for_task, watch_seconds, video_title)

    final_user_info = bili.get_user_info() or user_info
    valid_task_count = 0
    valid_success_count = 0
    for task_name, (success, message) in tasks.items():
        if is_skip_message(message):
            print(f"[账号{account_index}] {task_name}: 跳过，原因: {message}")
            continue
        valid_task_count += 1
        valid_success_count += int(success)
        if success:
            print(f"[账号{account_index}] {task_name}: 成功，{message}")
        else:
            print(f"[账号{account_index}] {task_name}: 失败，原因: {message}")

    return {
        "account_index": account_index,
        "user_info": final_user_info,
        "tasks": tasks,
        "metrics": level_metrics(final_user_info, tasks, config),
        "failed": valid_task_count == 0 or valid_success_count == 0,
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
        return False
    try:
        access_token = qywx_access_token(config)
    except Exception as e:
        print(f"企业微信应用通知获取 token 异常: {e}")
        return False

    try:
        text = f"{title}\n\n{content}"
        chunks = qywx_text_chunks(text)
        for chunk in chunks or [""]:
            _, access_token = qywx_send_text(config, access_token, chunk)
        print(f"企业微信应用文字通知发送成功（{max(1, len(chunks))} 条）")
        return True
    except Exception as e:
        print(f"企业微信应用文字通知异常: {e}")
    return False


def build_text_summary(results):
    lines = [f"共 {len(results)} 个账号，执行时间 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"]
    failed_accounts = 0
    for result in results:
        user_info = result.get("user_info") or {}
        account_name = mask_string(user_info.get("uname")) if user_info else "未知"
        metrics = result.get("metrics") or {}
        level = metrics.get("level", user_info.get("level_info", {}).get("current_level", "-"))
        if result.get("failed"):
            failed_accounts += 1
        lines.append("")
        lines.append(f"【账号{result['account_index']}】{account_name} Lv.{level}")
        for task_name, (success, message) in result.get("tasks", {}).items():
            if is_skip_message(message):
                status = "跳过"
            else:
                status = "成功" if success else "失败"
            lines.append(f"  · {task_name}：{status}｜{message or '-'}")
        if user_info:
            lines.append(
                f"  · 硬币 {user_info.get('money', '-')}｜经验 {metrics.get('current_exp', 0)}/{metrics.get('next_exp', 0)}"
                f"｜升级还需 {metrics.get('remaining_exp', 0)} 经验，约 {metrics.get('days', 0)} 天"
            )
    lines.append("")
    lines.append(f"成功 {len(results) - failed_accounts} 个，失败 {failed_accounts} 个")

    hitokoto_content, hitokoto_source = hitokoto_parts()
    if hitokoto_content:
        lines.append("")
        lines.append(f"—— {hitokoto_content}" + (f"「{hitokoto_source}」" if hitokoto_source else ""))
    return "\n".join(lines).strip()


def main():
    config = {
        "BILIBILI_COOKIE": os.getenv("BILIBILI_COOKIE", ""),
        "TASK_CONFIG": os.getenv("BILIBILI_TASK_CONFIG") or os.getenv("TASK_CONFIG") or "manga_sign,share_video,add_coin",
        "COIN_ADD_NUM": str(env_int("COIN_ADD_NUM", 1)),
        "COIN_SELECT_LIKE": str(env_int("COIN_SELECT_LIKE", 1)),
        "COIN_VIDEO_SOURCE": os.getenv("COIN_VIDEO_SOURCE", "dynamic"),
        "WATCH_SECONDS": str(env_int("WATCH_SECONDS", 30)),
    }
    if not config["BILIBILI_COOKIE"]:
        print("环境变量 BILIBILI_COOKIE 未设置，程序终止")
        return 1

    cookies = [cookie.strip() for cookie in config["BILIBILI_COOKIE"].split("###") if cookie.strip()]
    print(f"检测到 {len(cookies)} 个账号，开始执行任务")
    results = []
    for index, cookie in enumerate(cookies, 1):
        print(f"=== 账号{index} 任务开始 ===")
        results.append(run_account(cookie, index, config))
        print(f"--- 账号{index} 任务结束 ---")

    title = "Bilibili 任务通知"
    send_notify(title, build_text_summary(results))
    return 1 if any(result.get("failed") for result in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
