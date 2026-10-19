#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
彩票AI预测 - 青龙面板脚本
每次运行自动：获取最新开奖 → 核对上期预测 → 预测下一期 → 青龙通知

环境变量:
  LOTTERY_API_KEY        - AI接口密钥
  LOTTERY_BASE_URL       - AI接口地址 (OpenAI兼容)
  LOTTERY_MODEL          - 模型名称 (默认 gpt-5.5)
  LOTTERY_FALLBACK_MODEL - 容错模型名称
  LOTTERY_MAX_TOKENS     - AI最大输出token数
  LOTTERY_TEMPERATURE    - AI温度
  LOTTERY_SEED           - AI随机种子，留空则不传
  LOTTERY_ENABLE_TYPES   - 启用彩种，逗号分隔：dlt,ssq,qxc,pl3,fc3d,qlc；留空处理全部
  QYWX_AM                - 企业微信应用，格式：corpid,corpsecret,touser,agentid
  QYWX_CORPID            - 企业微信企业 ID（未配置 QYWX_AM 时使用）
  QYWX_CORPSECRET        - 企业微信应用 Secret
  QYWX_TOUSER            - 接收成员，多个用 | 分隔，默认 @all
  QYWX_AGENTID           - 企业微信应用 AgentId
  QYWX_ORIGIN            - 企业微信 API 地址，默认 https://qyapi.weixin.qq.com
"""

import argparse
import hashlib
import json
import os
import re
import time
from collections import Counter
from datetime import datetime, timedelta
from io import BytesIO
from math import comb

import requests
from bs4 import BeautifulSoup

# ============================
# 配置
# ============================

LOTTERY_TYPES = {
    "dlt": {
        "name": "大乐透",
        "category": "体彩",
        "draw_days": [0, 2, 5],       # 周一=0, 周三=2, 周六=5
        "mode": "set",
        "front_label": "前区",
        "back_label": "后区",
        "front_range": (1, 35),
        "front_count": 5,
        "back_range": (1, 12),
        "back_count": 2,
        "front_indexes": [1, 2, 3, 4, 5],
        "back_indexes": [6, 7],
        "allow_duplicate": False,
        "ordered": False,
        "number_width": 2,
    },
    "ssq": {
        "name": "双色球",
        "category": "福彩",
        "draw_days": [1, 3, 6],       # 周二=1, 周四=3, 周日=6
        "mode": "set",
        "front_label": "红球",
        "back_label": "蓝球",
        "front_range": (1, 33),
        "front_count": 6,
        "back_range": (1, 16),
        "back_count": 1,
        "front_indexes": [1, 2, 3, 4, 5, 6],
        "back_indexes": [7],
        "allow_duplicate": False,
        "ordered": False,
        "number_width": 2,
    },
    "qxc": {
        "name": "7星彩",
        "category": "体彩",
        "draw_days": [1, 4, 6],       # 周二=1, 周五=4, 周日=6
        "mode": "position",
        "front_label": "基本号",
        "back_label": "特别号",
        "front_range": (0, 9),
        "front_count": 6,
        "back_range": (0, 14),
        "back_count": 1,
        "number_cell_index": 1,
        "front_indexes": [1, 2, 3, 4, 5, 6],
        "back_indexes": [7],
        "allow_duplicate": True,
        "ordered": True,
        "number_width": 1,
        "show_shape": False,
    },
    "pl3": {
        "name": "排列3",
        "category": "体彩",
        "draw_days": [0, 1, 2, 3, 4, 5, 6],
        "mode": "position",
        "front_label": "号码",
        "back_label": "",
        "front_range": (0, 9),
        "front_count": 3,
        "back_range": None,
        "back_count": 0,
        "number_cell_index": 1,
        "front_indexes": [1, 2, 3],
        "back_indexes": [],
        "allow_duplicate": True,
        "ordered": True,
        "number_width": 1,
        "show_shape": True,
    },
    "fc3d": {
        "name": "福彩3D",
        "category": "福彩",
        "draw_days": [0, 1, 2, 3, 4, 5, 6],
        "mode": "position",
        "front_label": "号码",
        "back_label": "",
        "front_range": (0, 9),
        "front_count": 3,
        "back_range": None,
        "back_count": 0,
        "number_cell_index": 1,
        "front_indexes": [1, 2, 3],
        "back_indexes": [],
        "allow_duplicate": True,
        "ordered": True,
        "number_width": 1,
        "show_shape": True,
        "period_format": "full_year",
    },
    "qlc": {
        "name": "七乐彩",
        "category": "福彩",
        "draw_days": [0, 2, 4],       # 周一=0, 周三=2, 周五=4
        "mode": "set",
        "front_label": "基本号",
        "back_label": "特别号",
        "front_range": (1, 30),
        "front_count": 7,
        "back_range": (1, 30),
        "back_count": 1,
        "predict_back_count": 0,
        "number_cell_index": 1,
        "number_token_width": 2,
        "front_indexes": [1, 2, 3, 4, 5, 6, 7],
        "back_indexes": [8],
        "allow_duplicate": False,
        "ordered": False,
        "number_width": 2,
    },
}

def enabled_lottery_items():
    raw = os.getenv("LOTTERY_ENABLE_TYPES", "").strip()
    if not raw:
        return list(LOTTERY_TYPES.items())

    aliases = {}
    for code, info in LOTTERY_TYPES.items():
        aliases[code.lower()] = code
        aliases[info["name"].lower()] = code
    aliases.update({"3d": "fc3d", "fucai3d": "fc3d", "7xc": "qxc", "qilecai": "qlc"})

    enabled = []
    invalid = []
    for token in re.split(r"[,，;；\s]+", raw):
        token = token.strip()
        if not token:
            continue
        code = aliases.get(token.lower())
        if not code:
            invalid.append(token)
            continue
        if code not in enabled:
            enabled.append(code)

    if invalid:
        print(f"忽略未知彩种: {', '.join(invalid)}")
    if enabled:
        print("本次启用彩种: " + ", ".join(LOTTERY_TYPES[code]["name"] for code in enabled))
    else:
        print("LOTTERY_ENABLE_TYPES 未匹配任何彩种，本次不处理任何彩种")
    return [(code, LOTTERY_TYPES[code]) for code in enabled]


CHART_URLS = {
    "dlt": "https://datachart.500.com/dlt/history/newinc/history.php",
    "ssq": "https://datachart.500.com/ssq/history/newinc/history.php",
    "qxc": "https://datachart.500.com/qxc/history/inc/history.php",
    "pl3": "https://datachart.500.com/pls/history/inc/history.php",
    "fc3d": "https://datachart.500.com/sd/history/inc/history.php",
    "qlc": "https://datachart.500.com/qlc/history/newinc/history.php",
}


def _period_range(lottery_type):
    """动态计算期号范围，覆盖当前年份前后"""
    year = datetime.now().year
    if LOTTERY_TYPES.get(lottery_type, {}).get("period_format") == "full_year":
        return f"{year - 1}001", f"{year + 2}999"
    prefix = year % 100
    start = f"{prefix - 1}001"
    end = f"{prefix + 2}999"
    return start, end

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
}

def env_int(name, default):
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def env_float(name, default):
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


API_KEY = os.getenv("LOTTERY_API_KEY", "")
BASE_URL = os.getenv("LOTTERY_BASE_URL", "")
MODEL = os.getenv("LOTTERY_MODEL", "gpt-5.5")
FALLBACK_MODEL = os.getenv("LOTTERY_FALLBACK_MODEL", "gemini-3-flash-preview")
AI_MAX_TOKENS = env_int("LOTTERY_MAX_TOKENS", 1200)
AI_TEMPERATURE = env_float("LOTTERY_TEMPERATURE", 0.2)
AI_SEED = os.getenv("LOTTERY_SEED", "42").strip()
DEVIATION_REVIEW_TOTAL = 20
DEVIATION_SHORT_WINDOW = 5
DEVIATION_MIN_SAMPLE = 5

# ============================
# 数据持久化 (JSON文件)
# ============================

DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lottery_data.json")


def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_data(data):
    text = json.dumps(data, ensure_ascii=False, indent=2)
    tmp_file = f"{DATA_FILE}.tmp"
    with open(tmp_file, "w", encoding="utf-8") as f:
        f.write(text)
        f.write("\n")
    os.replace(tmp_file, DATA_FILE)


def period_key(period):
    try:
        return int(str(period))
    except (TypeError, ValueError):
        return 0


def normalize_history(records, limit=100):
    return sorted(records, key=lambda r: period_key(r.get("period")), reverse=True)[:limit]


def prediction_back_count(lt):
    return lt.get("predict_back_count", lt.get("back_count", 0))


def is_position_lottery(lt):
    return lt.get("mode") == "position"


def lottery_numbers(record):
    return list(record.get("front") or []) + list(record.get("back") or [])


def validate_draw_numbers(front, back, lt):
    if len(front) != lt["front_count"] or len(back) != lt.get("back_count", 0):
        return False
    if not all(lt["front_range"][0] <= n <= lt["front_range"][1] for n in front):
        return False
    if lt.get("back_count", 0):
        br = lt["back_range"]
        if not all(br[0] <= n <= br[1] for n in back):
            return False
    if not lt.get("allow_duplicate", False):
        if len(set(front)) != len(front) or len(set(back)) != len(back):
            return False
    return True


def draw_record(draw):
    return {
        "period": str(draw["period"]),
        "front": draw["front"],
        "back": draw["back"],
        "date": draw.get("date", ""),
    }


def find_draw_by_period(records, period, latest_draw=None):
    period = str(period)
    if latest_draw and str(latest_draw.get("period")) == period:
        return draw_record(latest_draw)
    for record in records:
        if str(record.get("period")) == period:
            return record
    return None


# ============================
# 通知 (青龙 notify.py)
# ============================

WEEKDAY_CN = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
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
QYWX_IMAGE_LIMIT = 2 * 1024 * 1024
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


def qywx_upload_image(config, access_token, image_bytes):
    if not image_bytes:
        return None, access_token
    if len(image_bytes) > QYWX_IMAGE_LIMIT:
        print("企业微信应用图片超过 2MB，改为发送文字通知")
        return None, access_token
    data, access_token = qywx_api_post(
        config,
        f"{config['origin']}/cgi-bin/media/upload",
        access_token,
        params={"type": "image"},
        files={"media": ("lottery.jpg", image_bytes, "image/jpeg")},
    )
    if data.get("errcode") != 0:
        print(f"企业微信应用图片上传失败: {data.get('errcode')} {data.get('errmsg')}")
        return None, access_token
    return data.get("media_id"), access_token


def qywx_send_image(config, access_token, media_id):
    data, access_token = qywx_api_post(
        config,
        f"{config['origin']}/cgi-bin/message/send",
        access_token,
        json={
            "touser": config["touser"],
            "msgtype": "image",
            "agentid": config["agentid"],
            "image": {"media_id": media_id},
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


def send_notify(title, content, image_bytes=None):
    """优先发送图片通知；图片不可用时回退为文字通知（超长自动分片）。"""
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

    if image_bytes:
        try:
            media_id, access_token = qywx_upload_image(config, access_token, image_bytes)
            if media_id:
                qywx_send_image(config, access_token, media_id)
                print("企业微信应用图片通知发送成功")
                return True
        except Exception as e:
            print(f"企业微信应用图片通知异常: {e}")

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


def load_notify_font(size, bold=False):
    from PIL import ImageFont

    env_font = os.getenv("LOTTERY_FONT_PATH") or os.getenv("NEW_API_FONT_PATH", "")
    font_paths = [
        env_font,
        "/ql/data/scripts/msyh.ttc",
        "/ql/data/scripts/simhei.ttf",
        "/ql/data/scripts/NotoSansCJK-Regular.ttc",
        "/ql/data/scripts/wqy-microhei.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc" if bold else "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc" if bold else "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
        "/usr/share/fonts/truetype/arphic/uming.ttc",
        "C:/Windows/Fonts/msyhbd.ttc" if bold else "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/simhei.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for path in font_paths:
        if not path:
            continue
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            pass
    print("未找到中文字体，彩票图片可能显示方块；请安装中文字体或设置 LOTTERY_FONT_PATH")
    return ImageFont.load_default()


def notify_text_size(draw, text, font):
    box = draw.textbbox((0, 0), text, font=font)
    return box[2] - box[0], box[3] - box[1]


def wrap_notify_text(draw, text, font, max_width, max_lines=6):
    text = str(text or "").replace("\t", " ")
    lines = []
    for part in text.splitlines() or [""]:
        current = ""
        for char in part:
            candidate = current + char
            if notify_text_size(draw, candidate, font)[0] <= max_width:
                current = candidate
                continue
            if current:
                lines.append(current)
            current = char
            if len(lines) >= max_lines:
                break
        if current and len(lines) < max_lines:
            lines.append(current)
        if len(lines) >= max_lines:
            break
    if len(lines) == max_lines:
        rendered = "".join(line.rstrip("...") for line in lines)
        if len(rendered) < len(text.replace("\n", "")):
            lines[-1] = lines[-1].rstrip("。,.，:：;； ") + "..."
    return lines or [""]


def draw_dashed_rounded_rectangle(draw, xy, radius, fill, outline, width=2, dash=10, gap=7):
    x1, y1, x2, y2 = xy
    draw.rounded_rectangle(xy, radius=radius, fill=fill)

    def dashed_line(start, end):
        sx, sy = start
        ex, ey = end
        length = ((ex - sx) ** 2 + (ey - sy) ** 2) ** 0.5
        if length == 0:
            return
        dx = (ex - sx) / length
        dy = (ey - sy) / length
        pos = 0
        while pos < length:
            seg_end = min(pos + dash, length)
            draw.line(
                (sx + dx * pos, sy + dy * pos, sx + dx * seg_end, sy + dy * seg_end),
                fill=outline,
                width=width,
            )
            pos += dash + gap

    dashed_line((x1 + radius, y1), (x2 - radius, y1))
    dashed_line((x2, y1 + radius), (x2, y2 - radius))
    dashed_line((x2 - radius, y2), (x1 + radius, y2))
    dashed_line((x1, y2 - radius), (x1, y1 + radius))

    for box, start, end in [
        ((x1, y1, x1 + radius * 2, y1 + radius * 2), 180, 270),
        ((x2 - radius * 2, y1, x2, y1 + radius * 2), 270, 360),
        ((x2 - radius * 2, y2 - radius * 2, x2, y2), 0, 90),
        ((x1, y2 - radius * 2, x1 + radius * 2, y2), 90, 180),
    ]:
        draw.arc(box, start, end, fill=outline, width=width)


def parse_lottery_notification_sections(content):
    label_map = {
        "上期开奖号码：": "上期开奖",
        "上期预测号码：": "上期预测",
        "中奖结果：": "中奖结果",
        "偏差复盘：": "偏差复盘",
        "下一期预测：": "下一期预测",
    }
    sections = []
    current_title = None
    current_lines = []
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if line in label_map:
            if current_title:
                sections.append((current_title, current_lines))
            current_title = label_map[line]
            current_lines = []
            continue
        if not line:
            continue
        if current_title:
            current_lines.append(line)
    if current_title:
        sections.append((current_title, current_lines))
    return sections or [("通知内容", [line for line in content.splitlines() if line.strip()])]


def build_lottery_notify_image(title, content):
    try:
        from PIL import Image, ImageDraw
    except Exception as e:
        print(f"图片通知依赖 Pillow 不可用，跳过图片生成: {e}")
        return None

    width = 960
    margin = 48
    card_x = margin
    card_w = width - margin * 2
    header_h = 138
    footer_h = 112
    section_gap = 18
    section_pad_x = 28
    section_pad_y = 22
    line_height = 34
    body_w = card_w - section_pad_x * 2

    title_font = load_notify_font(42, True)
    sub_font = load_notify_font(22)
    section_font = load_notify_font(28, True)
    body_font = load_notify_font(24)
    small_font = load_notify_font(20)

    probe = Image.new("RGB", (width, 100), "white")
    draw = ImageDraw.Draw(probe)
    sections = []
    for section_title, lines in parse_lottery_notification_sections(content):
        wrapped_lines = []
        for line in lines:
            wrapped_lines.extend(wrap_notify_text(draw, line, body_font, body_w, 4))
        if not wrapped_lines:
            wrapped_lines = ["无"]
        section_h = section_pad_y * 2 + 36 + len(wrapped_lines) * line_height
        sections.append((section_title, wrapped_lines, section_h))

    hitokoto_content, hitokoto_source = hitokoto_parts()
    footer_lines = wrap_notify_text(draw, hitokoto_content, small_font, card_w - 84, 3) if hitokoto_content else []
    source_line = f"----{hitokoto_source}" if hitokoto_source else ""
    quote_box_h = 28 + (len(footer_lines) + (1 if source_line else 0)) * 26 if footer_lines or source_line else 0
    footer_h = 76 + quote_box_h
    content_h = sum(section_h for _, _, section_h in sections) + section_gap * max(0, len(sections) - 1)
    height = margin + header_h + section_gap + content_h + footer_h + margin
    image = Image.new("RGB", (width, height), "#eef3f9")
    draw = ImageDraw.Draw(image)

    draw.rounded_rectangle((card_x, margin, card_x + card_w, height - margin), radius=34, fill="#ffffff")
    draw.rounded_rectangle((card_x, margin, card_x + card_w, margin + header_h), radius=34, fill="#7c3aed")
    draw.rectangle((card_x, margin + header_h - 34, card_x + card_w, margin + header_h), fill="#7c3aed")
    draw.text((card_x + 42, margin + 30), title, font=title_font, fill="#ffffff")
    draw.text((card_x + 44, margin + 92), datetime.now().strftime("%Y-%m-%d %H:%M:%S"), font=sub_font, fill="#ede9fe")

    colors = {
        "上期开奖": ("#eff6ff", "#2563eb"),
        "上期预测": ("#f8fafc", "#475569"),
        "中奖结果": ("#fff7ed", "#ea580c"),
        "偏差复盘": ("#f0fdf4", "#16a34a"),
        "下一期预测": ("#faf5ff", "#9333ea"),
    }
    y = margin + header_h + section_gap
    for section_title, lines, section_h in sections:
        bg, accent = colors.get(section_title, ("#f8fafc", "#475569"))
        draw.rounded_rectangle((card_x + 24, y, card_x + card_w - 24, y + section_h), radius=22, fill=bg)
        draw.rounded_rectangle((card_x + 24, y, card_x + 34, y + section_h), radius=5, fill=accent)
        draw.text((card_x + 52, y + 20), section_title, font=section_font, fill=accent)
        text_y = y + 62
        for line in lines:
            draw.text((card_x + 52, text_y), line, font=body_font, fill="#1f2937")
            text_y += line_height
        y += section_h + section_gap

    quote_x1 = card_x + 34
    quote_x2 = card_x + card_w - 34
    quote_y1 = height - margin - footer_h + 18
    quote_y2 = quote_y1 + quote_box_h
    if quote_box_h:
        draw_dashed_rounded_rectangle(
            draw,
            (quote_x1, quote_y1, quote_x2, quote_y2),
            radius=18,
            fill="#fbfdff",
            outline="#cbd5e1",
            width=2,
        )
        footer_y = quote_y1 + 16
        for line in footer_lines:
            draw.text((quote_x1 + 18, footer_y), line, font=small_font, fill="#64748b")
            footer_y += 26
        if source_line:
            source_w, _ = notify_text_size(draw, source_line, small_font)
            draw.text((quote_x2 - 18 - source_w, footer_y), source_line, font=small_font, fill="#64748b")
    warning_y = height - margin - 42
    triangle = [
        (card_x + 45, warning_y + 22),
        (card_x + 42, warning_y + 19),
        (card_x + 54, warning_y + 2),
        (card_x + 58, warning_y + 2),
        (card_x + 70, warning_y + 19),
        (card_x + 67, warning_y + 22),
    ]
    draw.polygon(triangle, fill="#ef4444")
    draw.rounded_rectangle((card_x + 54, warning_y + 7, card_x + 58, warning_y + 15), radius=2, fill="#ffffff")
    draw.ellipse((card_x + 54, warning_y + 17, card_x + 58, warning_y + 21), fill="#ffffff")
    draw.text((card_x + 82, warning_y + 1), "彩票结果具有随机性，预测仅作娱乐参考。", font=small_font, fill="#ef4444")

    output = BytesIO()
    image.save(output, format="JPEG", quality=85, optimize=True)
    return output.getvalue()


def notification_fingerprint(title, content):
    return hashlib.sha256(f"{title}\n{content}".encode("utf-8")).hexdigest()


def send_notify_once(data, lottery_type, title, content):
    if "notifications" not in data:
        data["notifications"] = {}
    fingerprint = notification_fingerprint(title, content)
    last = data["notifications"].get(lottery_type, {})
    if last.get("fingerprint") == fingerprint:
        print(f"  {LOTTERY_TYPES[lottery_type]['name']}通知内容未变化，跳过推送")
        return False
    image_bytes = build_lottery_notify_image(title, content)
    if send_notify(title, content, image_bytes):
        data["notifications"][lottery_type] = {
            "fingerprint": fingerprint,
            "sent_at": datetime.now().isoformat(),
        }
        return True
    return False


def fmt_date(date_str):
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    return dt.strftime("%y.%m.%d") + "-" + WEEKDAY_CN[dt.weekday()]


# ============================
# 数据抓取 (500.com)
# ============================

def parse_number_cell(text, lt):
    token_width = lt.get("number_token_width")
    if token_width:
        return [int(n) for n in re.findall(rf"\d{{{token_width}}}", text)]
    return [int(n) for n in re.findall(r"\d+", text)]


def parse_draw_values(vals, lottery_type):
    lt = LOTTERY_TYPES[lottery_type]
    if not vals:
        return None
    try:
        if "number_cell_index" in lt:
            cell_index = lt["number_cell_index"]
            if len(vals) <= cell_index:
                return None
            numbers = parse_number_cell(vals[cell_index], lt)
            front = numbers[:lt["front_count"]]
            back = numbers[lt["front_count"]:lt["front_count"] + lt.get("back_count", 0)]
        else:
            indexes = lt.get("front_indexes", []) + lt.get("back_indexes", [])
            if not indexes or len(vals) <= max(indexes):
                return None
            front = [int(vals[i]) for i in lt.get("front_indexes", [])]
            back = [int(vals[i]) for i in lt.get("back_indexes", [])]
    except (TypeError, ValueError, IndexError):
        return None
    if not validate_draw_numbers(front, back, lt):
        return None
    return {"period": vals[0], "front": front, "back": back, "date": vals[-1]}


def fetch_latest(lottery_type):
    """获取最新一期开奖结果"""
    url = CHART_URLS.get(lottery_type)
    if not url:
        return None
    start, end = _period_range(lottery_type)
    params = {"start": start, "end": end}
    try:
        resp = requests.get(url, params=params, headers=HEADERS, timeout=30)
        resp.encoding = resp.apparent_encoding or "utf-8"
        soup = BeautifulSoup(resp.text, "html.parser")
        tables = soup.find_all("table")
        if not tables:
            return None
        rows = tables[0].find_all("tr")
        if len(rows) < 5:
            return None
        for row in rows:
            vals = [c.get_text(strip=True) for c in row.find_all("td")]
            record = parse_draw_values(vals, lottery_type)
            if record:
                return record
    except Exception as e:
        print(f"获取{lottery_type}最新开奖失败: {e}")
    return None


def fetch_history(lottery_type, count=100):
    """获取历史开奖数据"""
    url = CHART_URLS.get(lottery_type)
    if not url:
        return []
    start, end = _period_range(lottery_type)
    params = {"start": start, "end": end, "limit": count}
    try:
        resp = requests.get(url, params=params, headers=HEADERS, timeout=30)
        resp.encoding = resp.apparent_encoding or "utf-8"
        soup = BeautifulSoup(resp.text, "html.parser")
        tables = soup.find_all("table")
        if not tables:
            return []
        rows = tables[0].find_all("tr")
        records = []
        for row in rows:
            vals = [c.get_text(strip=True) for c in row.find_all("td")]
            record = parse_draw_values(vals, lottery_type)
            if record:
                records.append(record)
        return normalize_history(records, count)
    except Exception as e:
        print(f"获取{lottery_type}历史数据失败: {e}")
    return []


def get_cached_history(data, lottery_type, latest_draw):
    """获取历史数据，优先使用缓存，仅在有新数据时增量更新"""
    if "history" not in data:
        data["history"] = {}

    cached = normalize_history(data["history"].get(lottery_type, []), 100)

    if not cached:
        print(f"  首次获取{lottery_type}历史数据（全量100期）...")
        records = fetch_history(lottery_type, 100)
        if records:
            data["history"][lottery_type] = records
        return data["history"].get(lottery_type, [])

    if latest_draw:
        latest_period = str(latest_draw.get("period", ""))
        newest_period = cached[0].get("period", "") if cached else ""
        if period_key(latest_period) - period_key(newest_period) > 1:
            print(f"  检测到{lottery_type}历史缓存缺期，重新获取最近100期...")
            records = fetch_history(lottery_type, 100)
            if records:
                data["history"][lottery_type] = records
                return records
        if latest_period and not any(str(r.get("period")) == latest_period for r in cached):
            cached.insert(0, draw_record(latest_draw))
            cached = normalize_history(cached, 100)
            print(f"  历史缓存已更新（+1期，当前{len(cached)}期）")

    data["history"][lottery_type] = cached
    return data["history"][lottery_type]


def format_history_text(records, lottery_type):
    """格式化历史数据为AI提示文本（全部100期 + 频率统计）"""
    if not records:
        return ""
    lt = LOTTERY_TYPES[lottery_type]
    if is_position_lottery(lt):
        return format_position_history_text(records, lottery_type)
    return format_set_history_text(records, lottery_type)


def format_set_history_text(records, lottery_type):
    lt = LOTTERY_TYPES[lottery_type]
    width = lt.get("number_width", 2)
    front_label = lt["front_label"]
    back_label = lt.get("back_label", "")
    all_front = [n for r in records for n in r["front"]]
    all_back = [n for r in records for n in r.get("back", [])]
    front_freq = Counter(all_front)
    back_freq = Counter(all_back)
    top_front = sorted(front_freq.items(), key=lambda x: -x[1])[:10]
    top_back = sorted(back_freq.items(), key=lambda x: -x[1])[:5]

    def line(record):
        front_text = format_number_list(record["front"], width)
        if back_label and record.get("back"):
            return f"第{record['period']}期: {front_text} | {format_number_list(record['back'], width)}"
        return f"第{record['period']}期: {front_text}"

    all_text = "\n".join(line(r) for r in reversed(records))
    text = (
        f"以下是最近{len(records)}期开奖号码（从旧到新）:\n{all_text}\n\n"
        f"频率统计:\n"
        f"{front_label}频率TOP10: {', '.join(f'{n}({c}次)' for n, c in top_front)}"
    )
    if back_label and top_back:
        text += f"\n{back_label}频率TOP5: {', '.join(f'{n}({c}次)' for n, c in top_back)}"
    return text


def format_position_history_text(records, lottery_type):
    lt = LOTTERY_TYPES[lottery_type]
    width = lt.get("number_width", 1)
    all_text = "\n".join(
        f"第{r['period']}期: {format_number_list(lottery_numbers(r), width)}"
        for r in reversed(records)
    )
    position_lines = []
    total_count = lt["front_count"] + lt.get("back_count", 0)
    for index in range(total_count):
        freq = Counter(lottery_numbers(r)[index] for r in records if len(lottery_numbers(r)) > index)
        top = sorted(freq.items(), key=lambda x: -x[1])[:5]
        position_lines.append(f"第{index + 1}位TOP5: {', '.join(f'{n}({c}次)' for n, c in top)}")

    sums = [sum(lottery_numbers(r)) for r in records]
    spans = [calc_span(lottery_numbers(r)) for r in records]
    sum_top = sorted(Counter(sums).items(), key=lambda x: -x[1])[:8]
    span_top = sorted(Counter(spans).items(), key=lambda x: -x[1])[:8]
    text = (
        f"以下是最近{len(records)}期开奖号码（从旧到新）:\n{all_text}\n\n"
        f"按位频率统计:\n" + "\n".join(position_lines) + "\n"
        f"和值TOP8: {', '.join(f'{n}({c}次)' for n, c in sum_top)}\n"
        f"跨度TOP8: {', '.join(f'{n}({c}次)' for n, c in span_top)}"
    )
    if lt.get("show_shape"):
        shape_top = sorted(Counter(calc_digit_shape(lottery_numbers(r)) for r in records).items(), key=lambda x: -x[1])
        text += f"\n形态统计: {', '.join(f'{shape}({count}次)' for shape, count in shape_top)}"
    return text


# ============================
# AI 预测
# ============================

def ai_seed_value():
    if not AI_SEED:
        return None
    try:
        return int(AI_SEED)
    except ValueError:
        return AI_SEED


def add_unique_payload(payloads, payload):
    marker = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    if marker not in {p[0] for p in payloads}:
        payloads.append((marker, payload))


def build_ai_payloads(model_name, messages):
    payloads = []
    seed = ai_seed_value()
    base = {"model": model_name, "messages": messages, "temperature": AI_TEMPERATURE}

    payload = dict(base)
    payload["max_tokens"] = AI_MAX_TOKENS
    if seed is not None:
        payload["seed"] = seed
    add_unique_payload(payloads, payload)

    if seed is not None:
        payload = dict(base)
        payload["max_tokens"] = AI_MAX_TOKENS
        add_unique_payload(payloads, payload)

    payload = dict(base)
    payload["max_completion_tokens"] = AI_MAX_TOKENS
    add_unique_payload(payloads, payload)

    add_unique_payload(payloads, dict(base))
    add_unique_payload(payloads, {"model": model_name, "messages": messages})
    return [payload for _, payload in payloads]


def content_to_text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                value = item.get("text", item.get("content", ""))
                if isinstance(value, str):
                    parts.append(value)
        return "".join(parts)
    return ""


def extract_ai_content(data):
    choices = data.get("choices") or []
    if not choices:
        return ""
    choice = choices[0]
    message = choice.get("message", {})
    if isinstance(message, dict):
        content = content_to_text(message.get("content", ""))
    else:
        content = content_to_text(message)
    return content or content_to_text(choice.get("text", ""))


def call_ai(prompt):
    url = BASE_URL.rstrip("/") + "/chat/completions"

    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }

    messages = [
        {
            "role": "system",
            "content": (
                "你根据给定的彩票历史数据生成一注合规号码。"
                "彩票结果具有随机性，历史统计仅作启发式参考。"
                "只输出用户要求的 JSON，不输出解释。"
            )
        },
        {
            "role": "user",
            "content": prompt
        }
    ]

    last_error = None
    models = [MODEL]
    if FALLBACK_MODEL and FALLBACK_MODEL not in models:
        models.append(FALLBACK_MODEL)

    for model_name in models:
        model_error = None
        for payload in build_ai_payloads(model_name, messages):
            try:
                resp = requests.post(
                    url,
                    headers=headers,
                    json=payload,
                    timeout=120
                )

                if resp.status_code != 200:
                    try:
                        err = resp.json()
                    except Exception:
                        err = resp.text[:300]
                    raise RuntimeError(f"AI接口错误 (HTTP {resp.status_code}): {err}")

                data = resp.json()
                content = extract_ai_content(data)

                if not content:
                    raise RuntimeError("AI返回为空")

                if model_name != MODEL:
                    print(f"  主模型 {MODEL} 失败，已切换容错模型 {model_name}")

                return content, model_name
            except Exception as e:
                model_error = e
                last_error = e

        print(f"  模型 {model_name} 调用失败: {model_error}")

    raise RuntimeError(f"所有模型调用失败: {last_error}")


def normalize_numbers(numbers, num_range, count, allow_duplicate=False, ordered=False):
    if count == 0:
        return []
    if not num_range:
        return None
    cleaned = []
    for value in numbers:
        try:
            n = int(value)
        except (TypeError, ValueError):
            continue
        if num_range[0] <= n <= num_range[1] and (allow_duplicate or n not in cleaned):
            cleaned.append(n)
        if len(cleaned) == count:
            break
    if len(cleaned) != count:
        return None
    return cleaned if ordered else sorted(cleaned)


def numbers_from_value(value, lt=None):
    if isinstance(value, list):
        return value
    if isinstance(value, int):
        return [value]
    if isinstance(value, str):
        tokens = re.findall(r"\d+", value)
        if lt and is_position_lottery(lt) and len(tokens) == 1:
            total = lt["front_count"] + prediction_back_count(lt)
            if len(tokens[0]) == total:
                return list(tokens[0])
        return tokens
    return []


def extract_numbers_from_text(text, lt):
    tokens = re.findall(r"\d+", text)
    if is_position_lottery(lt) and len(tokens) == 1:
        total = lt["front_count"] + prediction_back_count(lt)
        if len(tokens[0]) == total:
            return [int(n) for n in tokens[0]]
    return [int(n) for n in tokens]


def split_prediction_numbers(numbers, lt):
    fc = lt["front_count"]
    bc = prediction_back_count(lt)
    if is_position_lottery(lt) and bc and len(numbers) == fc + bc:
        return numbers[:fc], numbers[fc:]
    return numbers, []


def normalize_prediction_parts(front_numbers, back_numbers, lt):
    allow_duplicate = lt.get("allow_duplicate", False)
    ordered = lt.get("ordered", False)
    fc = lt["front_count"]
    bc = prediction_back_count(lt)
    if not back_numbers:
        front_numbers, split_back = split_prediction_numbers(front_numbers, lt)
        if split_back:
            back_numbers = split_back
    front = normalize_numbers(front_numbers, lt["front_range"], fc, allow_duplicate, ordered)
    back = normalize_numbers(back_numbers, lt.get("back_range"), bc, allow_duplicate, ordered)
    if front is not None and back is not None:
        return front, back
    return None, None


def first_present(data, keys):
    for key in keys:
        if key in data:
            return data[key]
    return None


def parse_json_numbers(text, lt):
    candidates = [text.strip()]
    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        candidates.append(match.group(0))

    for candidate in candidates:
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict):
            continue
        front_value = first_present(data, ["front", "red", "digits", "numbers", "number", "前区", "红球", "基本号", "号码"])
        back_value = first_present(data, ["back", "blue", "special", "后区", "蓝球", "特别号"])
        front_numbers = numbers_from_value(front_value, lt)
        back_numbers = numbers_from_value(back_value, lt)
        front, back = normalize_prediction_parts(front_numbers, back_numbers, lt)
        if front is not None and back is not None:
            return [(front, back)]
    return []


def parse_numbers(text, lt):
    """从AI回复解析号码"""
    json_results = parse_json_numbers(text, lt)
    if json_results:
        return json_results

    results = []
    current_front = None
    allow_duplicate = lt.get("allow_duplicate", False)
    ordered = lt.get("ordered", False)
    fc = lt["front_count"]
    bc = prediction_back_count(lt)
    front_pattern = r"(?:前区|红球|基本号|号码)\s*[:：]?\s*(.*)"
    back_pattern = r"(?:后区|蓝球|特别号)\s*[:：]?\s*(.*)"

    for line in text.strip().splitlines():
        if not line.strip():
            continue

        front_m = re.search(front_pattern, line)
        if front_m:
            front_part = re.split(r"(?:后区|蓝球|特别号)", front_m.group(1), maxsplit=1)[0]
            nums = extract_numbers_from_text(front_part, lt)
            if is_position_lottery(lt) and bc and len(nums) == fc + bc:
                front, back = normalize_prediction_parts(nums, [], lt)
                if front is not None and back is not None:
                    results.append((front, back))
                current_front = None
            else:
                current_front = normalize_numbers(nums, lt["front_range"], fc, allow_duplicate, ordered)
                if current_front is not None and bc == 0:
                    results.append((current_front, []))
                    current_front = None

        back_m = re.search(back_pattern, line)
        if back_m and current_front is not None:
            back = normalize_numbers(
                extract_numbers_from_text(back_m.group(1), lt),
                lt.get("back_range"),
                bc,
                allow_duplicate,
                ordered,
            )
            if back is not None:
                results.append((current_front, back))
                current_front = None

    if results:
        return results

    all_nums = extract_numbers_from_text(text, lt)
    step = fc + bc
    for i in range(0, len(all_nums), step or 1):
        chunk = all_nums[i:i + step]
        if len(chunk) != step:
            continue
        front, back = normalize_prediction_parts(chunk[:fc], chunk[fc:], lt)
        if front is not None and back is not None:
            results.append((front, back))
    return results


def format_number_list(numbers, width=2):
    if not numbers:
        return "无"
    if width <= 1:
        return " ".join(str(n) for n in numbers)
    return " ".join(f"{n:0{width}d}" for n in numbers)


def format_area_line(front_label, front_numbers, back_label="", back_numbers=None, lottery_type=None, include_empty_back=True):
    lt = LOTTERY_TYPES.get(lottery_type, {}) if lottery_type else {}
    width = lt.get("number_width", 2)
    line = f"{front_label}：{format_number_list(front_numbers, width)}"
    if back_label and (include_empty_back or back_numbers):
        line += f"    {back_label}：{format_number_list(back_numbers or [], width)}"
    return line


def format_lottery_numbers(lottery_type, numbers):
    width = LOTTERY_TYPES[lottery_type].get("number_width", 2)
    return format_number_list(numbers, width)


def format_draw_or_prediction_line(lottery_type, front, back=None, include_empty_back=False):
    lt = LOTTERY_TYPES[lottery_type]
    return format_area_line(
        lt["front_label"],
        front,
        lt.get("back_label", ""),
        back or [],
        lottery_type,
        include_empty_back,
    )


def calc_odd_even(numbers):
    odd = sum(1 for n in numbers if n % 2 == 1)
    even = len(numbers) - odd
    return odd, even


def calc_big_small(numbers, num_range):
    midpoint = (num_range[0] + num_range[1]) // 2
    small = sum(1 for n in numbers if n <= midpoint)
    big = len(numbers) - small
    return small, big


def position_value_range(lt):
    if lt.get("back_range"):
        return (min(lt["front_range"][0], lt["back_range"][0]), max(lt["front_range"][1], lt["back_range"][1]))
    return lt["front_range"]


def calc_span(numbers):
    return max(numbers) - min(numbers) if numbers else 0


def calc_digit_shape(numbers):
    if len(numbers) != 3:
        return "非三位"
    unique = len(set(numbers))
    if unique == 1:
        return "豹子"
    if unique == 2:
        return "组三"
    return "组六"


def calc_position_hits(pred_numbers, actual_numbers):
    same_positions = [i + 1 for i, (p, a) in enumerate(zip(pred_numbers, actual_numbers)) if p == a]
    same = len(same_positions)
    common = sum((Counter(pred_numbers) & Counter(actual_numbers)).values())
    misplaced = max(0, common - same)
    return same, misplaced, same_positions


def format_position_indexes(indexes):
    if not indexes:
        return "无"
    return "、".join(f"第{i}位" for i in indexes)


def calc_consecutive_groups(numbers):
    if not numbers:
        return []
    nums = sorted(numbers)
    groups = []
    current = [nums[0]]
    for n in nums[1:]:
        if n == current[-1] + 1:
            current.append(n)
        else:
            if len(current) >= 2:
                groups.append(current)
            current = [n]
    if len(current) >= 2:
        groups.append(current)
    return groups


def format_consecutive_groups(numbers, width=2):
    groups = calc_consecutive_groups(numbers)
    if not groups:
        return "无连号"
    return "，".join("-".join(format_number_list([n], width) for n in group) for group in groups)


def average(values):
    return sum(values) / len(values) if values else 0


def format_avg(value, digits=1):
    text = f"{value:.{digits}f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def format_signed_avg(value, digits=1):
    return f"{value:+.{digits}f}"


def describe_average_direction(value, positive_text, negative_text, neutral_text, threshold):
    if value >= threshold:
        return positive_text
    if value <= -threshold:
        return negative_text
    return neutral_text


def format_top_counter(counter, width=2, limit=5):
    items = counter.most_common(limit)
    if not items:
        return "无"
    return "、".join(f"{format_number_list([n], width)}({c}次)" for n, c in items)


def remove_single_review_instruction(text):
    marker = "\n请将这些偏差作为内部约束参考，最终只输出主提示要求的 JSON。"
    return text.replace(marker, "")


def sample_size_note(count):
    if count < DEVIATION_MIN_SAMPLE:
        return f"- 样本提示：当前仅复盘{count}期，统计方向仅作弱参考。"
    return ""


def comb_count(n, k):
    if k < 0 or n < 0 or k > n:
        return 0
    return comb(n, k)


def hypergeom_pmf(population, success_count, draw_count, hit_count):
    denominator = comb_count(population, draw_count)
    if denominator == 0:
        return 0
    return comb_count(success_count, hit_count) * comb_count(population - success_count, draw_count - hit_count) / denominator


def binomial_pmf(trials, probability, hit_count):
    return comb_count(trials, hit_count) * (probability ** hit_count) * ((1 - probability) ** (trials - hit_count))


def generate_legal_random_numbers(lottery_type, rng):
    lt = LOTTERY_TYPES[lottery_type]
    fc = lt["front_count"]
    bc = prediction_back_count(lt)
    if is_position_lottery(lt):
        fr = lt["front_range"]
        front = [rng.randint(fr[0], fr[1]) for _ in range(fc)]
        back = []
        if bc:
            br = lt["back_range"]
            back = [rng.randint(br[0], br[1]) for _ in range(bc)]
        return front, back

    fr = lt["front_range"]
    front = sorted(rng.sample(range(fr[0], fr[1] + 1), fc))
    back = []
    if bc:
        br = lt["back_range"]
        back = sorted(rng.sample(range(br[0], br[1] + 1), bc))
    return front, back


def build_random_baseline_for_result(result, lottery_type):
    if lottery_type in ("dlt", "ssq"):
        return build_two_area_set_random_baseline(lottery_type)
    if lottery_type == "qlc":
        return build_qlc_random_baseline()
    if lottery_type == "qxc":
        return build_qxc_random_baseline()
    if lottery_type in ("pl3", "fc3d"):
        return build_position3_random_baseline(result, lottery_type)
    return {"expected_match_f": 0, "expected_match_b": 0, "expected_prize": 0}


def build_two_area_set_random_baseline(lottery_type):
    lt = LOTTERY_TYPES[lottery_type]
    front_population = lt["front_range"][1] - lt["front_range"][0] + 1
    back_population = lt["back_range"][1] - lt["back_range"][0] + 1
    fc = lt["front_count"]
    bc = prediction_back_count(lt)
    expected_prize = 0
    check_level = _check_ssq if lottery_type == "ssq" else _check_dlt
    for mf in range(fc + 1):
        front_prob = hypergeom_pmf(front_population, fc, fc, mf)
        for mb in range(bc + 1):
            back_prob = hypergeom_pmf(back_population, bc, bc, mb)
            if check_level(mf, mb):
                expected_prize += front_prob * back_prob
    return {
        "expected_match_f": fc * fc / front_population,
        "expected_match_b": bc * bc / back_population,
        "expected_prize": expected_prize,
    }


def build_qlc_random_baseline():
    lt = LOTTERY_TYPES["qlc"]
    front_population = lt["front_range"][1] - lt["front_range"][0] + 1
    fc = lt["front_count"]
    expected_prize = 0
    denominator = comb_count(front_population, fc)
    for mf in range(fc + 1):
        for mb in range(2):
            other_count = fc - mf - mb
            probability = comb_count(fc, mf) * comb_count(1, mb) * comb_count(front_population - fc - 1, other_count) / denominator
            if _check_qlc(mf, mb):
                expected_prize += probability
    return {
        "expected_match_f": fc * fc / front_population,
        "expected_match_b": fc / front_population,
        "expected_prize": expected_prize,
    }


def build_qxc_random_baseline():
    lt = LOTTERY_TYPES["qxc"]
    fc = lt["front_count"]
    front_probability = 1 / (lt["front_range"][1] - lt["front_range"][0] + 1)
    back_probability = 1 / (lt["back_range"][1] - lt["back_range"][0] + 1)
    expected_prize = 0
    for mf in range(fc + 1):
        front_prob = binomial_pmf(fc, front_probability, mf)
        for mb in range(2):
            back_prob = back_probability if mb else 1 - back_probability
            if _check_qxc_counts(mf, mb):
                expected_prize += front_prob * back_prob
    return {
        "expected_match_f": fc * front_probability,
        "expected_match_b": back_probability,
        "expected_prize": expected_prize,
    }


def build_position3_random_baseline(result, lottery_type):
    actual_front = result.get("actual_front") or []
    total = 0
    same_sum = 0
    misplaced_sum = 0
    prize_count = 0
    for a in range(10):
        for b in range(10):
            for c in range(10):
                mf, mb, level = check_win([a, b, c], [], actual_front, [], lottery_type)
                total += 1
                same_sum += mf
                misplaced_sum += mb
                prize_count += int(bool(level))
    return {
        "expected_match_f": same_sum / total,
        "expected_match_b": misplaced_sum / total,
        "expected_prize": prize_count / total,
    }


def build_random_baseline_summary(check_results, lottery_type):
    if not check_results:
        return None
    baselines = [build_random_baseline_for_result(result, lottery_type) for result in check_results]
    return {
        "lottery_type": lottery_type,
        "count": len(check_results),
        "ai_avg_match_f": average([result.get("match_f", 0) for result in check_results]),
        "ai_avg_match_b": average([result.get("match_b", 0) for result in check_results]),
        "ai_prize_count": sum(1 for result in check_results if result.get("prize")),
        "random_avg_match_f": average([baseline["expected_match_f"] for baseline in baselines]),
        "random_avg_match_b": average([baseline["expected_match_b"] for baseline in baselines]),
        "random_expected_prize_count": sum(baseline["expected_prize"] for baseline in baselines),
    }


def build_random_baseline_review_lines(check_results, lottery_type):
    summary = build_random_baseline_summary(check_results, lottery_type)
    if not summary:
        return []
    lt = LOTTERY_TYPES[lottery_type]
    front_label = lt["front_label"]
    back_label = lt.get("back_label", "")
    if lottery_type == "qlc":
        text = (
            f"- 随机基准对照：AI{front_label}平均命中{format_avg(summary['ai_avg_match_f'], 2)}个，随机期望{format_avg(summary['random_avg_match_f'], 2)}个；"
            f"{back_label}覆盖{format_avg(summary['ai_avg_match_b'], 2)}期，随机期望{format_avg(summary['random_avg_match_b'], 2)}期；"
            f"AI中奖{summary['ai_prize_count']}期，随机期望{format_avg(summary['random_expected_prize_count'], 2)}期。随机基准仅作能力对照。"
        )
    elif is_position_lottery(lt):
        second_label = back_label if lottery_type == "qxc" else "错位"
        text = (
            f"- 随机基准对照：AI同位平均命中{format_avg(summary['ai_avg_match_f'], 2)}个，随机期望{format_avg(summary['random_avg_match_f'], 2)}个；"
            f"AI{second_label}平均{format_avg(summary['ai_avg_match_b'], 2)}个，随机期望{format_avg(summary['random_avg_match_b'], 2)}个；"
            f"AI中奖{summary['ai_prize_count']}期，随机期望{format_avg(summary['random_expected_prize_count'], 2)}期。随机基准仅作能力对照。"
        )
    else:
        text = (
            f"- 随机基准对照：AI{front_label}平均命中{format_avg(summary['ai_avg_match_f'], 2)}个，随机期望{format_avg(summary['random_avg_match_f'], 2)}个；"
            f"AI{back_label}平均命中{format_avg(summary['ai_avg_match_b'], 2)}个，随机期望{format_avg(summary['random_avg_match_b'], 2)}个；"
            f"AI中奖{summary['ai_prize_count']}期，随机期望{format_avg(summary['random_expected_prize_count'], 2)}期。随机基准仅作能力对照。"
        )
    return [text]


def format_random_baseline_summary_line(summary, lottery_type):
    if not summary:
        return ""
    lt = LOTTERY_TYPES[lottery_type]
    front_label = lt["front_label"]
    back_label = lt.get("back_label", "")
    if lottery_type == "qlc":
        return f"随机基准：{front_label}{format_avg(summary['random_avg_match_f'], 2)}，{back_label}覆盖{format_avg(summary['random_avg_match_b'], 2)}，中奖期望{format_avg(summary['random_expected_prize_count'], 2)}期"
    if is_position_lottery(lt):
        second_label = back_label if lottery_type == "qxc" else "错位"
        return f"随机基准：同位{format_avg(summary['random_avg_match_f'], 2)}，{second_label}{format_avg(summary['random_avg_match_b'], 2)}，中奖期望{format_avg(summary['random_expected_prize_count'], 2)}期"
    return f"随机基准：{front_label}{format_avg(summary['random_avg_match_f'], 2)}，{back_label}{format_avg(summary['random_avg_match_b'], 2)}，中奖期望{format_avg(summary['random_expected_prize_count'], 2)}期"


def build_random_baseline_summary_line(check_results, lottery_type):
    return format_random_baseline_summary_line(build_random_baseline_summary(check_results, lottery_type), lottery_type)


def top_counter_items(counter, limit=5):
    return [{"number": number, "count": count} for number, count in counter.most_common(limit)]


def build_structured_statistical_review(check_results, lottery_type):
    if not check_results:
        return {
            "lottery_type": lottery_type,
            "kind": "empty",
            "count": 0,
            "sample_note": sample_size_note(0),
            "random_baseline": None,
            "latest": None,
        }
    lt = LOTTERY_TYPES[lottery_type]
    if is_position_lottery(lt):
        return build_position_structured_stats(check_results, lottery_type)
    return build_set_structured_stats(check_results, lottery_type)


def build_set_structured_stats(check_results, lottery_type):
    lt = LOTTERY_TYPES[lottery_type]
    front_label = lt["front_label"]
    back_label = lt.get("back_label", "")
    count = len(check_results)
    front_hits = []
    back_hits = []
    sum_diffs = []
    abs_sum_diffs = []
    odd_diffs = []
    big_diffs = []
    lost_front_counter = Counter()
    miss_front_counter = Counter()
    lost_back_counter = Counter()
    miss_back_counter = Counter()
    actual_consecutive_count = 0
    pred_consecutive_count = 0
    missed_consecutive_count = 0
    special_cover_count = 0

    for result in check_results:
        pred_front = sorted(result.get("pred_front") or [])
        pred_back = sorted(result.get("pred_back") or [])
        actual_front = sorted(result.get("actual_front") or [])
        actual_back = sorted(result.get("actual_back") or [])
        front_hits.append(result.get("match_f", 0))
        back_hits.append(result.get("match_b", 0))

        sum_diff = sum(pred_front) - sum(actual_front)
        sum_diffs.append(sum_diff)
        abs_sum_diffs.append(abs(sum_diff))

        pred_odd, _ = calc_odd_even(pred_front)
        actual_odd, _ = calc_odd_even(actual_front)
        odd_diffs.append(pred_odd - actual_odd)

        _, pred_big = calc_big_small(pred_front, lt["front_range"])
        _, actual_big = calc_big_small(actual_front, lt["front_range"])
        big_diffs.append(pred_big - actual_big)

        pred_has_consecutive = bool(calc_consecutive_groups(pred_front))
        actual_has_consecutive = bool(calc_consecutive_groups(actual_front))
        pred_consecutive_count += int(pred_has_consecutive)
        actual_consecutive_count += int(actual_has_consecutive)
        missed_consecutive_count += int(actual_has_consecutive and not pred_has_consecutive)

        lost_front_counter.update(set(actual_front) - set(pred_front))
        miss_front_counter.update(set(pred_front) - set(actual_front))

        if lottery_type == "qlc":
            special_cover_count += int(bool(actual_back) and actual_back[0] in pred_front)
        else:
            lost_back_counter.update(set(actual_back) - set(pred_back))
            miss_back_counter.update(set(pred_back) - set(actual_back))

    avg_front_hit = average(front_hits)
    avg_back_hit = average(back_hits)
    avg_sum_diff = average(sum_diffs)
    avg_odd_diff = average(odd_diffs)
    avg_big_diff = average(big_diffs)
    sum_direction = describe_average_direction(avg_sum_diff, "和值整体偏高", "和值整体偏低", "和值重心接近", 3)
    odd_direction = describe_average_direction(avg_odd_diff, "奇号偏多", "奇号覆盖不足", "奇偶接近", 0.4)
    big_direction = describe_average_direction(avg_big_diff, "大号偏多", "大号覆盖不足", "大小接近", 0.4)
    consecutive_direction = "连号覆盖接近"
    if missed_consecutive_count >= max(1, count // 4):
        consecutive_direction = "连号覆盖不足"
    elif pred_consecutive_count - actual_consecutive_count >= max(1, count // 4):
        consecutive_direction = "连号倾向偏重"

    window = None
    if count > DEVIATION_SHORT_WINDOW:
        window = {
            "short_size": DEVIATION_SHORT_WINDOW,
            "short_avg_front": average(front_hits[:DEVIATION_SHORT_WINDOW]),
            "short_avg_sum_diff": average(sum_diffs[:DEVIATION_SHORT_WINDOW]),
            "long_avg_front": avg_front_hit,
            "long_avg_sum_diff": avg_sum_diff,
        }

    latest = check_results[0]
    return {
        "lottery_type": lottery_type,
        "kind": "set",
        "count": count,
        "sample_note": sample_size_note(count),
        "labels": {"front": front_label, "back": back_label},
        "hit": {
            "avg_front": avg_front_hit,
            "avg_back": avg_back_hit,
            "prize_count": sum(1 for result in check_results if result.get("prize")),
            "special_cover_count": special_cover_count,
        },
        "window": window,
        "bias": {
            "avg_sum_diff": avg_sum_diff,
            "avg_abs_sum_diff": average(abs_sum_diffs),
            "sum_direction": sum_direction,
            "avg_odd_diff": avg_odd_diff,
            "odd_direction": odd_direction,
            "avg_big_diff": avg_big_diff,
            "big_direction": big_direction,
            "actual_consecutive_count": actual_consecutive_count,
            "pred_consecutive_count": pred_consecutive_count,
            "missed_consecutive_count": missed_consecutive_count,
            "consecutive_direction": consecutive_direction,
        },
        "frequency": {
            "lost_front": top_counter_items(lost_front_counter),
            "miss_front": top_counter_items(miss_front_counter),
            "lost_back": top_counter_items(lost_back_counter),
            "miss_back": top_counter_items(miss_back_counter),
        },
        "random_baseline": build_random_baseline_summary(check_results, lottery_type),
        "latest": {
            "period": latest.get("period"),
            "match_f": latest.get("match_f", 0),
            "match_b": latest.get("match_b", 0),
            "prize": latest.get("prize"),
        },
    }


def build_position_structured_stats(check_results, lottery_type):
    lt = LOTTERY_TYPES[lottery_type]
    count = len(check_results)
    same_hits = []
    second_hits = []
    sum_diffs = []
    abs_sum_diffs = []
    span_diffs = []
    abs_span_diffs = []
    odd_diffs = []
    big_diffs = []
    zero_same_count = 0
    half_same_count = 0
    total_positions = lt["front_count"] + prediction_back_count(lt)
    position_hit_counts = [0] * total_positions
    shape_match_count = 0
    pred_shape_counter = Counter()
    actual_shape_counter = Counter()
    second_hit_label = lt.get("back_label") if lottery_type == "qxc" else "错位"

    for result in check_results:
        pred_numbers = list(result.get("pred_front") or []) + list(result.get("pred_back") or [])
        actual_numbers = list(result.get("actual_front") or []) + list(result.get("actual_back") or [])
        if lottery_type == "qxc":
            same = result.get("match_f", 0)
            second_hit = result.get("match_b", 0)
        else:
            same, second_hit, _ = calc_position_hits(pred_numbers, actual_numbers)
        same_hits.append(same)
        second_hits.append(second_hit)
        zero_same_count += int(same == 0)
        half_same_count += int(same >= max(1, len(actual_numbers) // 2))

        for index, (pred, actual) in enumerate(zip(pred_numbers, actual_numbers)):
            if index < total_positions and pred == actual:
                position_hit_counts[index] += 1

        sum_diff = sum(pred_numbers) - sum(actual_numbers)
        span_diff = calc_span(pred_numbers) - calc_span(actual_numbers)
        sum_diffs.append(sum_diff)
        abs_sum_diffs.append(abs(sum_diff))
        span_diffs.append(span_diff)
        abs_span_diffs.append(abs(span_diff))

        pred_odd, _ = calc_odd_even(pred_numbers)
        actual_odd, _ = calc_odd_even(actual_numbers)
        odd_diffs.append(pred_odd - actual_odd)

        _, pred_big = calc_big_small(pred_numbers, position_value_range(lt))
        _, actual_big = calc_big_small(actual_numbers, position_value_range(lt))
        big_diffs.append(pred_big - actual_big)

        if lt.get("show_shape"):
            pred_shape = calc_digit_shape(pred_numbers)
            actual_shape = calc_digit_shape(actual_numbers)
            pred_shape_counter.update([pred_shape])
            actual_shape_counter.update([actual_shape])
            shape_match_count += int(pred_shape == actual_shape)

    avg_same = average(same_hits)
    avg_second = average(second_hits)
    avg_sum_diff = average(sum_diffs)
    avg_span_diff = average(span_diffs)
    avg_odd_diff = average(odd_diffs)
    avg_big_diff = average(big_diffs)
    sum_threshold = max(1, total_positions // 2)
    sum_direction = describe_average_direction(avg_sum_diff, "和值整体偏高", "和值整体偏低", "和值接近", sum_threshold)
    span_direction = describe_average_direction(avg_span_diff, "跨度偏大", "跨度偏小", "跨度接近", 1)
    odd_direction = describe_average_direction(avg_odd_diff, "奇号偏多", "奇号覆盖不足", "奇偶接近", 0.4)
    big_direction = describe_average_direction(avg_big_diff, "大号偏多", "大号覆盖不足", "大小接近", 0.4)
    weakest_positions = sorted(range(total_positions), key=lambda index: (position_hit_counts[index], index))[:2]
    weakest_labels = [
        {
            "index": index,
            "label": format_stat_position_label(lt, index),
            "hit_rate": position_hit_counts[index] / count,
        }
        for index in weakest_positions
    ]
    pred_shape = pred_shape_counter.most_common(1)[0][0] if pred_shape_counter else None
    actual_shape = actual_shape_counter.most_common(1)[0][0] if actual_shape_counter else None
    window = None
    if count > DEVIATION_SHORT_WINDOW:
        window = {
            "short_size": DEVIATION_SHORT_WINDOW,
            "short_avg_same": average(same_hits[:DEVIATION_SHORT_WINDOW]),
            "short_avg_sum_diff": average(sum_diffs[:DEVIATION_SHORT_WINDOW]),
            "long_avg_same": avg_same,
            "long_avg_sum_diff": avg_sum_diff,
        }

    latest = check_results[0]
    return {
        "lottery_type": lottery_type,
        "kind": "position",
        "count": count,
        "sample_note": sample_size_note(count),
        "labels": {"front": lt["front_label"], "back": lt.get("back_label", ""), "second_hit": second_hit_label},
        "hit": {
            "avg_same": avg_same,
            "avg_second": avg_second,
            "prize_count": sum(1 for result in check_results if result.get("prize")),
            "zero_same_count": zero_same_count,
            "half_same_count": half_same_count,
        },
        "window": window,
        "position": {
            "total_positions": total_positions,
            "hit_counts": position_hit_counts,
            "weakest_indexes": weakest_positions,
            "weakest_labels": weakest_labels,
        },
        "bias": {
            "avg_sum_diff": avg_sum_diff,
            "avg_abs_sum_diff": average(abs_sum_diffs),
            "sum_direction": sum_direction,
            "avg_span_diff": avg_span_diff,
            "avg_abs_span_diff": average(abs_span_diffs),
            "span_direction": span_direction,
            "avg_odd_diff": avg_odd_diff,
            "odd_direction": odd_direction,
            "avg_big_diff": avg_big_diff,
            "big_direction": big_direction,
        },
        "shape": {
            "enabled": bool(lt.get("show_shape")),
            "match_count": shape_match_count,
            "top_pred": pred_shape,
            "top_actual": actual_shape,
        },
        "random_baseline": build_random_baseline_summary(check_results, lottery_type),
        "latest": {
            "period": latest.get("period"),
            "match_f": latest.get("match_f", 0),
            "match_b": latest.get("match_b", 0),
            "prize": latest.get("prize"),
        },
    }


def build_deviation_review_text_from_results(check_results, lottery_type):
    if not check_results:
        return "无可用的上期预测复盘数据，本次仅基于历史开奖数据进行预测。"
    lt = LOTTERY_TYPES[lottery_type]
    if is_position_lottery(lt):
        return build_position_statistical_deviation_review_text(check_results, lottery_type)
    return build_set_statistical_deviation_review_text(check_results, lottery_type)


def build_set_statistical_deviation_review_text(check_results, lottery_type):
    lt = LOTTERY_TYPES[lottery_type]
    width = lt.get("number_width", 2)
    front_label = lt["front_label"]
    back_label = lt.get("back_label", "")
    count = len(check_results)
    front_hits = []
    back_hits = []
    sum_diffs = []
    abs_sum_diffs = []
    odd_diffs = []
    big_diffs = []
    lost_front_counter = Counter()
    miss_front_counter = Counter()
    lost_back_counter = Counter()
    miss_back_counter = Counter()
    actual_consecutive_count = 0
    pred_consecutive_count = 0
    missed_consecutive_count = 0
    special_cover_count = 0

    for result in check_results:
        pred_front = sorted(result.get("pred_front") or [])
        pred_back = sorted(result.get("pred_back") or [])
        actual_front = sorted(result.get("actual_front") or [])
        actual_back = sorted(result.get("actual_back") or [])
        front_hits.append(result.get("match_f", 0))
        back_hits.append(result.get("match_b", 0))

        sum_diff = sum(pred_front) - sum(actual_front)
        sum_diffs.append(sum_diff)
        abs_sum_diffs.append(abs(sum_diff))

        pred_odd, _ = calc_odd_even(pred_front)
        actual_odd, _ = calc_odd_even(actual_front)
        odd_diffs.append(pred_odd - actual_odd)

        _, pred_big = calc_big_small(pred_front, lt["front_range"])
        _, actual_big = calc_big_small(actual_front, lt["front_range"])
        big_diffs.append(pred_big - actual_big)

        pred_has_consecutive = bool(calc_consecutive_groups(pred_front))
        actual_has_consecutive = bool(calc_consecutive_groups(actual_front))
        pred_consecutive_count += int(pred_has_consecutive)
        actual_consecutive_count += int(actual_has_consecutive)
        missed_consecutive_count += int(actual_has_consecutive and not pred_has_consecutive)

        lost_front_counter.update(set(actual_front) - set(pred_front))
        miss_front_counter.update(set(pred_front) - set(actual_front))

        if lottery_type == "qlc":
            special_cover_count += int(bool(actual_back) and actual_back[0] in pred_front)
        else:
            lost_back_counter.update(set(actual_back) - set(pred_back))
            miss_back_counter.update(set(pred_back) - set(actual_back))

    avg_front_hit = average(front_hits)
    avg_back_hit = average(back_hits)
    avg_sum_diff = average(sum_diffs)
    avg_abs_sum_diff = average(abs_sum_diffs)
    avg_odd_diff = average(odd_diffs)
    avg_big_diff = average(big_diffs)
    prize_count = sum(1 for result in check_results if result.get("prize"))
    sum_direction = describe_average_direction(avg_sum_diff, "和值整体偏高", "和值整体偏低", "和值重心接近", 3)
    odd_direction = describe_average_direction(avg_odd_diff, "奇号偏多", "奇号覆盖不足", "奇偶接近", 0.4)
    big_direction = describe_average_direction(avg_big_diff, "大号偏多", "大号覆盖不足", "大小接近", 0.4)
    consecutive_direction = "连号覆盖接近"
    if missed_consecutive_count >= max(1, count // 4):
        consecutive_direction = "连号覆盖不足"
    elif pred_consecutive_count - actual_consecutive_count >= max(1, count // 4):
        consecutive_direction = "连号倾向偏重"

    hit_line = f"- 总体命中：{front_label}平均命中{format_avg(avg_front_hit)}个"
    if lottery_type == "qlc" and back_label:
        hit_line += f"，{back_label}被预测{front_label}覆盖{special_cover_count}期，中奖{prize_count}期"
    elif back_label:
        hit_line += f"，{back_label}平均命中{format_avg(avg_back_hit)}个，中奖{prize_count}期"
    else:
        hit_line += f"，中奖{prize_count}期"

    lines = [f"近期预测偏差统计复盘（最近{count}期）:"]
    note = sample_size_note(count)
    if note:
        lines.append(note)
    if count > DEVIATION_SHORT_WINDOW:
        short_front_hit = average(front_hits[:DEVIATION_SHORT_WINDOW])
        short_sum_diff = average(sum_diffs[:DEVIATION_SHORT_WINDOW])
        lines.append(
            f"- 窗口对比：近{DEVIATION_SHORT_WINDOW}期{front_label}平均命中{format_avg(short_front_hit)}个，和值差{format_signed_avg(short_sum_diff)}；"
            f"近{count}期平均命中{format_avg(avg_front_hit)}个，和值差{format_signed_avg(avg_sum_diff)}"
        )
    lines.append(hit_line)
    lines.extend(build_random_baseline_review_lines(check_results, lottery_type))
    lines.extend([
        f"- 和值偏差：{front_label}预测和值平均差值{format_signed_avg(avg_sum_diff)}，平均绝对偏差{format_avg(avg_abs_sum_diff)}，{sum_direction}",
        f"- 奇偶偏差：预测奇号平均差值{format_signed_avg(avg_odd_diff)}，{odd_direction}",
        f"- 大小偏差：预测大号平均差值{format_signed_avg(avg_big_diff)}，{big_direction}",
        f"- 连号偏差：实际连号{actual_consecutive_count}期，预测连号{pred_consecutive_count}期，漏覆盖{missed_consecutive_count}期，{consecutive_direction}",
        f"- 高频遗漏：实际开出但预测未覆盖较多的{front_label}号码：{format_top_counter(lost_front_counter, width)}",
        f"- 高频落空：预测较多但未开出的{front_label}号码：{format_top_counter(miss_front_counter, width)}",
    ])
    if back_label and lottery_type != "qlc":
        lines.extend([
            f"- {back_label}高频遗漏：{format_top_counter(lost_back_counter, width)}",
            f"- {back_label}高频落空：{format_top_counter(miss_back_counter, width)}",
        ])
    lines.extend([
        "- 修正建议：按以上统计微调和值、奇偶、大小和连号覆盖，避免机械追冷。",
        "",
        "最近一期细节：",
        remove_single_review_instruction(build_set_deviation_review_text(check_results[0], lottery_type)),
        "请将以上多期统计偏差和最近一期细节作为内部约束参考，最终只输出主提示要求的 JSON。",
    ])
    return "\n".join(lines)


def format_stat_position_label(lt, index):
    if index < lt["front_count"]:
        return f"第{index + 1}位"
    return lt.get("back_label") or f"第{index + 1}位"


def build_position_statistical_deviation_review_text(check_results, lottery_type):
    lt = LOTTERY_TYPES[lottery_type]
    width = lt.get("number_width", 1)
    count = len(check_results)
    same_hits = []
    misplaced_hits = []
    sum_diffs = []
    abs_sum_diffs = []
    span_diffs = []
    abs_span_diffs = []
    odd_diffs = []
    big_diffs = []
    zero_same_count = 0
    half_same_count = 0
    total_positions = lt["front_count"] + prediction_back_count(lt)
    position_hit_counts = [0] * total_positions
    shape_match_count = 0
    pred_shape_counter = Counter()
    actual_shape_counter = Counter()

    for result in check_results:
        pred_numbers = list(result.get("pred_front") or []) + list(result.get("pred_back") or [])
        actual_numbers = list(result.get("actual_front") or []) + list(result.get("actual_back") or [])
        if lottery_type == "qxc":
            same = result.get("match_f", 0)
            misplaced = result.get("match_b", 0)
        else:
            same, misplaced, _ = calc_position_hits(pred_numbers, actual_numbers)
        same_hits.append(same)
        misplaced_hits.append(misplaced)
        zero_same_count += int(same == 0)
        half_same_count += int(same >= max(1, len(actual_numbers) // 2))

        for index, (pred, actual) in enumerate(zip(pred_numbers, actual_numbers)):
            if index < total_positions and pred == actual:
                position_hit_counts[index] += 1

        sum_diff = sum(pred_numbers) - sum(actual_numbers)
        span_diff = calc_span(pred_numbers) - calc_span(actual_numbers)
        sum_diffs.append(sum_diff)
        abs_sum_diffs.append(abs(sum_diff))
        span_diffs.append(span_diff)
        abs_span_diffs.append(abs(span_diff))

        pred_odd, _ = calc_odd_even(pred_numbers)
        actual_odd, _ = calc_odd_even(actual_numbers)
        odd_diffs.append(pred_odd - actual_odd)

        _, pred_big = calc_big_small(pred_numbers, position_value_range(lt))
        _, actual_big = calc_big_small(actual_numbers, position_value_range(lt))
        big_diffs.append(pred_big - actual_big)

        if lt.get("show_shape"):
            pred_shape = calc_digit_shape(pred_numbers)
            actual_shape = calc_digit_shape(actual_numbers)
            pred_shape_counter.update([pred_shape])
            actual_shape_counter.update([actual_shape])
            shape_match_count += int(pred_shape == actual_shape)

    avg_same = average(same_hits)
    avg_misplaced = average(misplaced_hits)
    avg_sum_diff = average(sum_diffs)
    avg_span_diff = average(span_diffs)
    avg_odd_diff = average(odd_diffs)
    avg_big_diff = average(big_diffs)
    prize_count = sum(1 for result in check_results if result.get("prize"))
    sum_threshold = max(1, total_positions // 2)
    sum_direction = describe_average_direction(avg_sum_diff, "和值整体偏高", "和值整体偏低", "和值接近", sum_threshold)
    span_direction = describe_average_direction(avg_span_diff, "跨度偏大", "跨度偏小", "跨度接近", 1)
    odd_direction = describe_average_direction(avg_odd_diff, "奇号偏多", "奇号覆盖不足", "奇偶接近", 0.4)
    big_direction = describe_average_direction(avg_big_diff, "大号偏多", "大号覆盖不足", "大小接近", 0.4)
    weakest_positions = sorted(
        range(total_positions),
        key=lambda index: (position_hit_counts[index], index),
    )[:2]
    weakest_text = "、".join(
        f"{format_stat_position_label(lt, index)}{format_avg(position_hit_counts[index] * 100 / count, 0)}%"
        for index in weakest_positions
    )

    lines = [f"近期预测偏差统计复盘（最近{count}期）:"]
    note = sample_size_note(count)
    if note:
        lines.append(note)
    if count > DEVIATION_SHORT_WINDOW:
        short_same = average(same_hits[:DEVIATION_SHORT_WINDOW])
        short_sum_diff = average(sum_diffs[:DEVIATION_SHORT_WINDOW])
        lines.append(
            f"- 窗口对比：近{DEVIATION_SHORT_WINDOW}期同位平均命中{format_avg(short_same)}个，和值差{format_signed_avg(short_sum_diff)}；"
            f"近{count}期同位平均命中{format_avg(avg_same)}个，和值差{format_signed_avg(avg_sum_diff)}"
        )
    second_hit_label = lt.get("back_label") if lottery_type == "qxc" else "错位"
    lines.append(f"- 总体命中：同位平均命中{format_avg(avg_same)}个，{second_hit_label}平均命中{format_avg(avg_misplaced)}个，中奖{prize_count}期")
    lines.extend(build_random_baseline_review_lines(check_results, lottery_type))
    lines.extend([
        f"- 定位稳定性：0同位{zero_same_count}期，半数以上同位{half_same_count}期，薄弱位置：{weakest_text}",
        f"- 和值偏差：预测和值平均差值{format_signed_avg(avg_sum_diff)}，平均绝对偏差{format_avg(average(abs_sum_diffs))}，{sum_direction}",
        f"- 跨度偏差：预测跨度平均差值{format_signed_avg(avg_span_diff)}，平均绝对偏差{format_avg(average(abs_span_diffs))}，{span_direction}",
        f"- 奇偶偏差：预测奇号平均差值{format_signed_avg(avg_odd_diff)}，{odd_direction}",
        f"- 大小偏差：预测大号平均差值{format_signed_avg(avg_big_diff)}，{big_direction}",
    ])
    if lt.get("show_shape"):
        pred_shape = pred_shape_counter.most_common(1)[0][0] if pred_shape_counter else "无"
        actual_shape = actual_shape_counter.most_common(1)[0][0] if actual_shape_counter else "无"
        lines.append(f"- 形态偏差：形态命中{shape_match_count}/{count}期，预测多为{pred_shape}，实际多为{actual_shape}")
    lines.extend([
        "- 修正建议：优先修正薄弱位置和和值/跨度方向，避免机械固定某一形态。",
        "",
        "最近一期细节：",
        remove_single_review_instruction(build_position_deviation_review_text(check_results[0], lottery_type)),
        "请将以上多期统计偏差和最近一期细节作为内部约束参考，最终只输出主提示要求的 JSON。",
    ])
    return "\n".join(lines)


def build_deviation_review_text(check_result, lottery_type):
    if not check_result:
        return "无可用的上期预测复盘数据，本次仅基于历史开奖数据进行预测。"
    lt = LOTTERY_TYPES[lottery_type]
    if is_position_lottery(lt):
        return build_position_deviation_review_text(check_result, lottery_type)
    return build_set_deviation_review_text(check_result, lottery_type)


def build_set_deviation_review_text(check_result, lottery_type):
    lt = LOTTERY_TYPES[lottery_type]
    width = lt.get("number_width", 2)
    front_label = lt["front_label"]
    back_label = lt.get("back_label", "")
    pred_front = sorted(check_result["pred_front"])
    pred_back = sorted(check_result["pred_back"])
    actual_front = sorted(check_result["actual_front"])
    actual_back = sorted(check_result["actual_back"])

    hit_front = sorted(set(pred_front) & set(actual_front))
    miss_front = sorted(set(pred_front) - set(actual_front))
    lost_front = sorted(set(actual_front) - set(pred_front))
    if lottery_type == "qlc":
        hit_back = actual_back if actual_back and actual_back[0] in pred_front else []
        miss_back = []
        lost_back = actual_back if not hit_back else []
    else:
        hit_back = sorted(set(pred_back) & set(actual_back))
        miss_back = sorted(set(pred_back) - set(actual_back))
        lost_back = sorted(set(actual_back) - set(pred_back))

    pred_front_odd, pred_front_even = calc_odd_even(pred_front)
    actual_front_odd, actual_front_even = calc_odd_even(actual_front)
    pred_front_small, pred_front_big = calc_big_small(pred_front, lt["front_range"])
    actual_front_small, actual_front_big = calc_big_small(actual_front, lt["front_range"])
    prize_text = check_result.get("prize") or "未中奖"
    back_prediction_text = "不预测" if prediction_back_count(lt) == 0 else format_number_list(pred_back, width)

    lines = [
        f"上期预测偏差复盘（第{check_result['period']}期）:",
        f"- 预测号码：{front_label} {format_number_list(pred_front, width)}" + (f" | {back_label} {back_prediction_text}" if back_label else ""),
        f"- 开奖号码：{front_label} {format_number_list(actual_front, width)}" + (f" | {back_label} {format_number_list(actual_back, width)}" if back_label else ""),
        f"- 命中情况：{front_label}命中{check_result['match_f']}个（{format_number_list(hit_front, width)}）"
        + (f"，{back_label}命中{check_result['match_b']}个（{format_number_list(hit_back, width)}）" if back_label else "")
        + f"，结果：{prize_text}",
        f"- {front_label}预测落空号码：{format_number_list(miss_front, width)}",
        f"- {front_label}实际遗漏号码：{format_number_list(lost_front, width)}",
    ]
    if back_label:
        lines.extend([
            f"- {back_label}预测落空号码：{format_number_list(miss_back, width)}",
            f"- {back_label}实际遗漏号码：{format_number_list(lost_back, width)}",
        ])
    lines.extend([
        f"- {front_label}和值偏差：预测{sum(pred_front)}，实际{sum(actual_front)}，差值{sum(pred_front) - sum(actual_front):+d}",
        f"- {front_label}奇偶偏差：预测奇{pred_front_odd}/偶{pred_front_even}，实际奇{actual_front_odd}/偶{actual_front_even}",
        f"- {front_label}大小偏差：预测小{pred_front_small}/大{pred_front_big}，实际小{actual_front_small}/大{actual_front_big}",
        f"- {front_label}连号偏差：预测{format_consecutive_groups(pred_front, width)}，实际{format_consecutive_groups(actual_front, width)}",
        "请将这些偏差作为内部约束参考，最终只输出主提示要求的 JSON。",
    ])
    return "\n".join(lines)


def build_position_deviation_review_text(check_result, lottery_type):
    lt = LOTTERY_TYPES[lottery_type]
    width = lt.get("number_width", 1)
    pred_numbers = check_result["pred_front"] + check_result["pred_back"]
    actual_numbers = check_result["actual_front"] + check_result["actual_back"]
    if lottery_type == "qxc":
        same = check_result.get("match_f", 0)
        misplaced = check_result.get("match_b", 0)
        same_positions = [i + 1 for i, (p, a) in enumerate(zip(check_result["pred_front"], check_result["actual_front"])) if p == a]
    else:
        same, misplaced, same_positions = calc_position_hits(pred_numbers, actual_numbers)
    pred_odd, pred_even = calc_odd_even(pred_numbers)
    actual_odd, actual_even = calc_odd_even(actual_numbers)
    pred_small, pred_big = calc_big_small(pred_numbers, position_value_range(lt))
    actual_small, actual_big = calc_big_small(actual_numbers, position_value_range(lt))
    prize_text = check_result.get("prize") or "未中奖"
    if lottery_type == "qxc":
        hit_text = f"{lt['front_label']}同位命中{same}个（{format_position_indexes(same_positions)}），{lt['back_label']}命中{misplaced}个"
    else:
        hit_text = f"同位命中{same}个（{format_position_indexes(same_positions)}），错位命中{misplaced}个"
    lines = [
        f"上期预测偏差复盘（第{check_result['period']}期）:",
        f"- 预测号码：{format_number_list(pred_numbers, width)}",
        f"- 开奖号码：{format_number_list(actual_numbers, width)}",
        f"- 命中情况：{hit_text}，结果：{prize_text}",
        f"- 和值偏差：预测{sum(pred_numbers)}，实际{sum(actual_numbers)}，差值{sum(pred_numbers) - sum(actual_numbers):+d}",
        f"- 跨度偏差：预测{calc_span(pred_numbers)}，实际{calc_span(actual_numbers)}，差值{calc_span(pred_numbers) - calc_span(actual_numbers):+d}",
        f"- 奇偶偏差：预测奇{pred_odd}/偶{pred_even}，实际奇{actual_odd}/偶{actual_even}",
        f"- 大小偏差：预测小{pred_small}/大{pred_big}，实际小{actual_small}/大{actual_big}",
    ]
    if lt.get("show_shape"):
        lines.append(f"- 形态偏差：预测{calc_digit_shape(pred_numbers)}，实际{calc_digit_shape(actual_numbers)}")
    lines.append("请将这些偏差作为内部约束参考，最终只输出主提示要求的 JSON。")
    return "\n".join(lines)


def prediction_has_actual(prediction):
    if not prediction or not prediction.get("checked") or not prediction.get("actual_front"):
        return False
    lt = LOTTERY_TYPES.get(prediction.get("lottery_type"), {})
    if lt.get("back_count", 0) == 0:
        return prediction.get("actual_back") is not None
    return bool(prediction.get("actual_back"))


def build_check_result_from_prediction(prediction):
    if not prediction_has_actual(prediction):
        return None
    return {
        "period": prediction["period"],
        "pred_front": prediction["numbers"][0]["front"],
        "pred_back": prediction["numbers"][0]["back"],
        "actual_front": prediction["actual_front"],
        "actual_back": prediction["actual_back"],
        "match_f": prediction.get("match_front", 0),
        "match_b": prediction.get("match_back", 0),
        "prize": prediction.get("prize_level"),
    }


def collect_recent_check_results(data, lottery_type, latest_period=None, check_result=None, limit=DEVIATION_REVIEW_TOTAL):
    by_period = {}
    if check_result:
        by_period[str(check_result["period"])] = check_result

    for prediction in data.get("predictions", {}).values():
        if prediction.get("lottery_type") != lottery_type:
            continue
        if latest_period is not None and period_key(prediction.get("period")) > period_key(latest_period):
            continue
        built = build_check_result_from_prediction(prediction)
        if not built:
            continue
        key = str(built["period"])
        if key not in by_period:
            by_period[key] = built

    return sorted(
        by_period.values(),
        key=lambda result: period_key(result.get("period")),
        reverse=True,
    )[:limit]


def get_latest_check_result(data, lottery_type, latest_period, check_result=None):
    if check_result:
        return check_result
    stored = get_stored_prediction(data, lottery_type, latest_period)
    return build_check_result_from_prediction(stored)


def get_latest_review_text(data, lottery_type, latest_period, check_result=None):
    recent_results = collect_recent_check_results(data, lottery_type, latest_period, check_result)
    return build_deviation_review_text_from_results(recent_results, lottery_type)



def predict_numbers(history_text, lottery_type, review_text, count=1):
    """
    AI直接输出最终预测号码
    不再使用Python随机选号
    """

    lt = LOTTERY_TYPES[lottery_type]
    fr = lt["front_range"]
    br = lt.get("back_range")
    fc = lt["front_count"]
    bc = prediction_back_count(lt)
    front_label = lt["front_label"]
    back_label = lt.get("back_label", "")

    if is_position_lottery(lt):
        duplicate_rule = "允许重复数字，必须保留顺序，不能排序"
        if bc:
            rules = (
                f"{front_label}{fc}位，每位{fr[0]}-{fr[1]}；"
                f"{back_label}{bc}位，每位{br[0]}-{br[1]}；{duplicate_rule}"
            )
        else:
            rules = f"{front_label}{fc}位，每位{fr[0]}-{fr[1]}；{duplicate_rule}；back 固定输出空数组"
        reference_dimensions = """1. 各位置热门数字走势
2. 各位置冷门数字回补
3. 同位重号规律
4. 和值走势
5. 跨度走势
6. 奇偶比例
7. 大小比例
8. 重复形态（豹子、组三、组六等，适用于三位玩法）
9. 最近10期短期趋势
10. 最近30期中期趋势
11. 最近100期长期趋势"""
    else:
        if bc:
            rules = f"{front_label}{fr[0]}-{fr[1]}选{fc}个，{back_label}{br[0]}-{br[1]}选{bc}个"
        else:
            rules = f"{front_label}{fr[0]}-{fr[1]}选{fc}个，不需要预测{back_label or '后区'}，back 固定输出空数组"
        reference_dimensions = """1. 热门号码走势
2. 冷门号码回补
3. 重号规律
4. 连号规律
5. 奇偶比例
6. 大小比例
7. 区间分布
8. 最近10期短期趋势
9. 最近30期中期趋势
10. 最近100期长期趋势"""

    example_back = list(range(br[0], br[0] + bc)) if bc and br else []
    example_json = json.dumps(
        {
            "front": list(range(fr[0], fr[0] + fc)),
            "back": example_back,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    duplicate_requirement = "front 和 back 内部可以重复，但必须保留位置顺序" if is_position_lottery(lt) else "front 和 back 内部不能重复，组合型号码按升序输出"

    prompt = f"""
请根据给定数据生成下一期的一注合规号码。

彩票开奖结果具有随机性，历史数据只能作为统计参考，不代表可预测或保证命中。

近期预测复盘：
{review_text}

内部参考维度：
{reference_dimensions}

生成要求：
1. 只生成1注
2. 号码必须严格符合规则：{rules}
3. front 表示{front_label}，back 表示{back_label or '空数组'}
4. {duplicate_requirement}
5. 数组内数字使用整数，不要使用字符串
6. 只输出 JSON 对象，不要 Markdown 代码块
7. 不要输出解释、分析过程、候选池或多个方案

历史数据：
{history_text}

输出格式示例：
{example_json}
"""

    text, used_model = call_ai(prompt)

    print(f"  AI原始回复: {text[:500]}")

    results = parse_numbers(text, lt)

    if not results:
        raise RuntimeError("AI号码解析失败")

    final_results = results[:count]

    for i, (front, back) in enumerate(final_results):
        print(f"  AI最终预测第{i+1}组: {format_draw_or_prediction_line(lottery_type, front, back, False)}")

    return final_results, [], [], used_model


# ============================
# 中奖判断
# ============================

def check_win(pred_front, pred_back, actual_front, actual_back, lottery_type):
    if lottery_type == "pl3" or lottery_type == "fc3d":
        return _check_position3(pred_front, actual_front)
    if lottery_type == "qxc":
        return _check_qxc(pred_front, pred_back, actual_front, actual_back)
    if lottery_type == "qlc":
        mf = len(set(pred_front) & set(actual_front))
        mb = 1 if actual_back and actual_back[0] in set(pred_front) else 0
        return mf, mb, _check_qlc(mf, mb)

    pf, pb = set(pred_front), set(pred_back)
    af, ab = set(actual_front), set(actual_back)
    mf, mb = len(pf & af), len(pb & ab)
    level = _check_ssq(mf, mb) if lottery_type == "ssq" else _check_dlt(mf, mb)
    return mf, mb, level


def _check_dlt(mf, mb):
    if mf == 5 and mb == 2: return "一等奖"
    if mf == 5 and mb == 1: return "二等奖"
    if mf == 5 and mb == 0: return "三等奖"
    if mf == 4 and mb == 2: return "四等奖"
    if mf == 4 and mb == 1: return "五等奖"
    if mf == 3 and mb == 2: return "六等奖"
    if mf == 4 and mb == 0: return "七等奖"
    if (mf == 3 and mb == 1) or (mf == 2 and mb == 2): return "八等奖"
    if (mf == 3 and mb == 0) or (mf == 2 and mb == 1) or (mf == 1 and mb == 2) or (mf == 0 and mb == 2): return "九等奖"
    return None


def _check_ssq(mf, mb):
    if mf == 6 and mb == 1: return "一等奖"
    if mf == 6 and mb == 0: return "二等奖"
    if mf == 5 and mb == 1: return "三等奖"
    if (mf == 5 and mb == 0) or (mf == 4 and mb == 1): return "四等奖"
    if (mf == 4 and mb == 0) or (mf == 3 and mb == 1): return "五等奖"
    if (mf == 2 and mb == 1) or (mf == 1 and mb == 1) or (mf == 0 and mb == 1): return "六等奖"
    return None


def _check_qlc(mf, mb):
    if mf == 7: return "一等奖"
    if mf == 6 and mb == 1: return "二等奖"
    if mf == 6 and mb == 0: return "三等奖"
    if mf == 5 and mb == 1: return "四等奖"
    if mf == 5 and mb == 0: return "五等奖"
    if mf == 4 and mb == 1: return "六等奖"
    if mf == 4 and mb == 0: return "七等奖"
    return None


def _check_position3(pred, actual):
    same, misplaced, _ = calc_position_hits(pred, actual)
    if pred == actual:
        return same, misplaced, "直选"
    if Counter(pred) == Counter(actual):
        shape = calc_digit_shape(actual)
        if shape == "组三":
            return same, misplaced, "组选三"
        if shape == "组六":
            return same, misplaced, "组选六"
    return same, misplaced, None


def _check_qxc_counts(mf, mb):
    if mf == 6 and mb == 1: return "一等奖"
    if mf == 6 and mb == 0: return "二等奖"
    if mf == 5 and mb == 1: return "三等奖"
    if mf == 5 and mb == 0: return "四等奖"
    if mf == 4 and mb == 1: return "五等奖"
    if mf == 4 and mb == 0: return "六等奖"
    if mf == 3 and mb == 1: return "七等奖"
    if mf == 2 and mb == 1: return "八等奖"
    if mb == 1: return "九等奖"
    return None


def _check_qxc(pred_front, pred_back, actual_front, actual_back):
    mf = sum(1 for p, a in zip(pred_front, actual_front) if p == a)
    mb = 1 if pred_back and actual_back and pred_back[0] == actual_back[0] else 0
    return mf, mb, _check_qxc_counts(mf, mb)


# ============================
# 辅助函数
# ============================

def next_draw_date(latest_date, draw_days):
    """根据最新开奖日期推算下一期开奖日期"""
    d = datetime.strptime(latest_date, "%Y-%m-%d") + timedelta(days=1)
    for _ in range(7):
        if d.weekday() in draw_days:
            return d.strftime("%Y-%m-%d")
        d += timedelta(days=1)
    return ""


def increment_period(period):
    period = str(period)
    try:
        return f"{int(period) + 1:0{len(period)}d}"
    except ValueError:
        return period


def next_draw_period(latest_period, latest_date, draw_days, lottery_type=None):
    next_period = increment_period(latest_period)
    try:
        latest_dt = datetime.strptime(latest_date, "%Y-%m-%d")
        next_date = next_draw_date(latest_date, draw_days)
        next_dt = datetime.strptime(next_date, "%Y-%m-%d")
    except (TypeError, ValueError):
        return next_period
    if next_dt.year > latest_dt.year:
        if lottery_type and LOTTERY_TYPES.get(lottery_type, {}).get("period_format") == "full_year":
            return f"{next_dt.year}001"
        return f"{next_dt.year % 100:02d}001"
    return next_period


def get_stored_prediction(data, lottery_type, period):
    key = f"{lottery_type}_{period}"
    return data.get("predictions", {}).get(key)


def store_prediction(data, lottery_type, period, numbers, draw_date, model):
    if "predictions" not in data:
        data["predictions"] = {}
    key = f"{lottery_type}_{period}"
    data["predictions"][key] = {
        "lottery_type": lottery_type,
        "period": period,
        "numbers": [{"front": f, "back": b} for f, b in numbers],
        "draw_date": draw_date,
        "model": model,
        "created_at": datetime.now().isoformat(),
        "checked": False,
    }


def build_prediction_data(prediction):
    if not prediction:
        return None
    return {
        "period": prediction.get("period", ""),
        "numbers": prediction.get("numbers", []),
        "draw_date": prediction.get("draw_date", ""),
        "recommended_front": prediction.get("recommended_front", []),
        "recommended_back": prediction.get("recommended_back", []),
        "used_model": prediction.get("model", MODEL),
    }


def deviation_review_count(data, lottery_type):
    count = sum(
        1 for prediction in data.get("predictions", {}).values()
        if prediction.get("lottery_type") == lottery_type and prediction_has_actual(prediction)
    )
    return min(count, DEVIATION_REVIEW_TOTAL)


def seed_fake_predictions(data):
    """首次运行时标记状态，不再用真开奖号冒充预测"""
    if data.get("predictions") is not None:
        return data
    data["predictions"] = {}
    data["first_run"] = True
    print("  首次运行，已初始化预测存储")
    return data


def format_period_line(period, date_value):
    line = f"期号：第{period}期"
    if date_value:
        line += f"（{fmt_date(date_value)}）"
    return line


def build_number_display_lines(lottery_type, front, back=None, include_metrics=True, include_empty_back=False):
    lt = LOTTERY_TYPES[lottery_type]
    back = back or []
    if is_position_lottery(lt):
        numbers = list(front) + list(back)
        lines = [f"号码：{format_lottery_numbers(lottery_type, numbers)}"]
        if lt.get("back_label") and back:
            lines.append(format_draw_or_prediction_line(lottery_type, front, back, include_empty_back))
        if include_metrics:
            if lt.get("show_shape"):
                lines.append(f"形态：{calc_digit_shape(numbers)}")
            lines.append(f"和值：{sum(numbers)}")
            lines.append(f"跨度：{calc_span(numbers)}")
        return lines
    return [format_draw_or_prediction_line(lottery_type, front, back, include_empty_back)]


def build_win_text(lottery_type, check_result):
    if not check_result:
        return "无上期预测数据"
    lt = LOTTERY_TYPES[lottery_type]
    prize_text = check_result["prize"] or "未中奖"
    if is_position_lottery(lt):
        if lottery_type == "qxc":
            return f"{prize_text}（{lt['front_label']}同位命中{check_result['match_f']}个，{lt['back_label']}命中{check_result['match_b']}个）"
        return f"{prize_text}（同位命中{check_result['match_f']}个，错位命中{check_result['match_b']}个）"
    return f"{prize_text}（{lt['front_label']}命中{check_result['match_f']}个，{lt.get('back_label', '后区')}命中{check_result['match_b']}个）"


def limit_review_text(text, limit=30):
    return text if len(text) <= limit else text[:limit]


def build_statistical_review_summary_lines(data, lottery_type, check_results):
    if not check_results:
        return ["暂无近期复盘"]

    stats = build_structured_statistical_review(check_results, lottery_type)
    count = stats["count"]
    latest = stats["latest"]
    prize = latest.get("prize") or "未中奖"
    sample_suffix = "，样本少" if count < DEVIATION_MIN_SAMPLE else ""
    baseline_line = format_random_baseline_summary_line(stats["random_baseline"], lottery_type)

    if stats["kind"] == "position":
        total_positions = stats["position"]["total_positions"]
        sum_direction = describe_average_direction(
            stats["bias"]["avg_sum_diff"],
            "和值偏高",
            "和值偏低",
            "和值接近",
            max(1, total_positions // 2),
        )
        second_label = stats["labels"]["second_hit"]
        return [
            limit_review_text(f"复盘{count}期，同位均中{format_avg(stats['hit']['avg_same'])}，{sum_direction}{sample_suffix}", 48),
            limit_review_text(baseline_line, 48),
            limit_review_text(f"上期同位中{latest.get('match_f', 0)}{second_label}中{latest.get('match_b', 0)}，{prize}", 48),
        ]

    front_label = stats["labels"]["front"]
    back_label = stats["labels"]["back"]
    avg_front_hit = stats["hit"]["avg_front"]
    sum_direction = describe_average_direction(stats["bias"]["avg_sum_diff"], "和值偏高", "和值偏低", "和值接近", 3)

    if lottery_type == "qlc" and back_label:
        special_cover_count = stats["hit"]["special_cover_count"]
        first_line = f"复盘{count}期，{front_label}均中{format_avg(avg_front_hit)}，{back_label}覆盖{special_cover_count}期{sample_suffix}"
        second_line = f"上期{front_label}中{latest.get('match_f', 0)}，{back_label}覆盖{latest.get('match_b', 0)}，{prize}"
    elif back_label:
        avg_back_hit = stats["hit"]["avg_back"]
        first_line = f"复盘{count}期，{front_label}均中{format_avg(avg_front_hit)}，{back_label}均中{format_avg(avg_back_hit)}，{sum_direction}{sample_suffix}"
        second_line = f"上期{front_label}中{latest.get('match_f', 0)}，{back_label}中{latest.get('match_b', 0)}，{prize}"
    else:
        first_line = f"复盘{count}期，{front_label}均中{format_avg(avg_front_hit)}，{sum_direction}{sample_suffix}"
        second_line = f"上期{front_label}中{latest.get('match_f', 0)}，{prize}"

    return [limit_review_text(first_line, 48), limit_review_text(baseline_line, 48), limit_review_text(second_line, 48)]


def build_review_summary_lines(data, lottery_type, check_result):
    recent_results = collect_recent_check_results(data, lottery_type, check_result=check_result)
    if not recent_results:
        return ["暂无近期复盘"]
    return build_statistical_review_summary_lines(data, lottery_type, recent_results)


def build_plain_review_summary(data, lottery_type, check_result):
    count = deviation_review_count(data, lottery_type)
    prefix = f"复盘{count}期，上期"
    prize = check_result.get("prize")
    if prize:
        return f"{prefix}中了{prize}，方向可留"

    lt = LOTTERY_TYPES[lottery_type]
    if is_position_lottery(lt):
        return build_position_plain_review(prefix, lt, check_result)
    return build_set_plain_review(prefix, lt, check_result)


def build_set_plain_review(prefix, lt, check_result):
    pred = check_result["pred_front"]
    actual = check_result["actual_front"]
    sum_diff = sum(pred) - sum(actual)
    pred_odd, _ = calc_odd_even(pred)
    actual_odd, _ = calc_odd_even(actual)
    _, pred_big = calc_big_small(pred, lt["front_range"])
    _, actual_big = calc_big_small(actual, lt["front_range"])

    if abs(sum_diff) >= 20:
        main = "整体偏小" if sum_diff < 0 else "整体偏大"
    elif abs(sum_diff) >= 8:
        main = "和值略低" if sum_diff < 0 else "和值略高"
    else:
        main = "和值接近"

    missing = []
    if actual_big - pred_big >= 2:
        missing.append("大号")
    elif pred_big - actual_big >= 2:
        missing.append("小号")
    if actual_odd - pred_odd >= 2:
        missing.append("奇号")
    elif pred_odd - actual_odd >= 2:
        missing.append("偶号")
    if calc_consecutive_groups(actual) and not calc_consecutive_groups(pred):
        missing.append("连号")

    if missing:
        return f"{prefix}{main}，少了{'和'.join(missing[:2])}"
    if calc_consecutive_groups(pred) and not calc_consecutive_groups(actual):
        return f"{prefix}{main}，连号想多了"
    return f"{prefix}{main}，下期微调"


def build_position_plain_review(prefix, lt, check_result):
    pred = check_result["pred_front"] + check_result["pred_back"]
    actual = check_result["actual_front"] + check_result["actual_back"]
    same, _, _ = calc_position_hits(pred, actual)
    sum_diff = sum(pred) - sum(actual)
    span_diff = calc_span(pred) - calc_span(actual)

    if same == 0:
        main = "同位全偏"
    elif same <= max(1, len(actual) // 3):
        main = "同位偏少"
    elif same >= max(1, len(actual) // 2):
        main = "同位还行"
    else:
        main = "同位一般"

    if abs(sum_diff) >= max(6, len(actual) * 2):
        second = "和值偏低" if sum_diff < 0 else "和值偏高"
    elif abs(span_diff) >= 3:
        second = "跨度偏小" if span_diff < 0 else "跨度偏大"
    elif lt.get("show_shape") and calc_digit_shape(pred) != calc_digit_shape(actual):
        second = "形态猜偏"
    else:
        second = "方向接近"
    return f"{prefix}{main}，{second}"


def build_notification_content(data, lottery_type, latest, latest_check_result, prediction_data):
    notif_lines = [
        "上期开奖号码：",
        format_period_line(latest["period"], latest.get("date", "")),
    ]
    notif_lines.extend(build_number_display_lines(lottery_type, latest["front"], latest.get("back", []), True, True))
    notif_lines.extend(["", "上期预测号码："])

    if latest_check_result:
        notif_lines.extend(build_number_display_lines(
            lottery_type,
            latest_check_result["pred_front"],
            latest_check_result["pred_back"],
            True,
            False,
        ))
    else:
        notif_lines.append("无")

    notif_lines.extend([
        "",
        "中奖结果：",
        build_win_text(lottery_type, latest_check_result),
        "",
        "偏差复盘：",
    ])
    notif_lines.extend(build_review_summary_lines(data, lottery_type, latest_check_result))
    notif_lines.extend(["", "下一期预测："])

    if prediction_data:
        notif_lines.append(format_period_line(prediction_data["period"], prediction_data.get("draw_date", "")))
        notif_lines.append(f"模型：{prediction_data.get('used_model', MODEL)}")
        for num in prediction_data["numbers"]:
            notif_lines.extend(build_number_display_lines(lottery_type, num["front"], num.get("back", []), True, False))
    else:
        notif_lines.append("未生成")

    return "\n".join(notif_lines)


def format_console_prediction(lottery_type, num):
    lt = LOTTERY_TYPES[lottery_type]
    if is_position_lottery(lt):
        return f"号码 {format_lottery_numbers(lottery_type, num['front'] + num.get('back', []))}"
    text = f"{lt['front_label']} {format_lottery_numbers(lottery_type, num['front'])}"
    if lt.get("back_label") and num.get("back"):
        text += f" {lt['back_label']} {format_lottery_numbers(lottery_type, num['back'])}"
    return text


def format_console_check(lottery_type, check_result):
    lt = LOTTERY_TYPES[lottery_type]
    prize = check_result["prize"] or "未中奖"
    if is_position_lottery(lt):
        if lottery_type == "qxc":
            return f"第{check_result['period']}期 {lt['front_label']}同位命中{check_result['match_f']} {lt['back_label']}命中{check_result['match_b']} → {prize}"
        return f"第{check_result['period']}期 同位命中{check_result['match_f']} 错位命中{check_result['match_b']} → {prize}"
    return f"第{check_result['period']}期 {lt['front_label']}命中{check_result['match_f']} {lt.get('back_label', '后区')}命中{check_result['match_b']} → {prize}"


def detect_and_process(data):
    """
    自动检测最新开奖 → 核对上期 → 预测下一期
    返回 (成功, 消息列表)
    """
    messages = []

    for lt_code, lt_info in enabled_lottery_items():
        today = datetime.now().weekday()
        is_draw_day = today in lt_info["draw_days"]
        if not is_draw_day:
            print(f"  今天不是{lt_info['name']}开奖日({WEEKDAY_CN[today]})，检查是否需要补处理")
        print(f"\n{'='*30}")
        print(f"处理 {lt_info['name']}...")

        # 获取最新开奖结果
        latest = fetch_latest(lt_code)
        if not latest:
            print(f"  获取{lt_info['name']}最新开奖失败")
            messages.append(f"{lt_info['name']}: 获取开奖结果失败")
            continue

        print(f"  最新开奖: 第{latest['period']}期 → {format_console_prediction(lt_code, latest)}")
        records = get_cached_history(data, lt_code, latest)
        if records:
            print(f"  历史缓存可用 {len(records)} 期")

        next_period = next_draw_period(latest["period"], latest.get("date", ""), lt_info["draw_days"], lt_code)
        existing = get_stored_prediction(data, lt_code, next_period)
        unchecked = [
            v for v in data.get("predictions", {}).values()
            if v["lottery_type"] == lt_code
            and not v.get("checked")
            and period_key(v.get("period")) <= period_key(latest["period"])
        ]

        if not is_draw_day and not unchecked and existing:
            print(f"  {lt_info['name']}无待核对预测，且第{next_period}期已预测，跳过")
            continue

        # 核对上期预测
        check_result = None
        checked_any = False
        for pred in unchecked:
            actual = find_draw_by_period(records, pred["period"], latest)
            if not actual:
                print(f"  第{pred['period']}期开奖号未找到，保留待核对")
                continue
            pred_front = pred["numbers"][0]["front"]
            pred_back = pred["numbers"][0]["back"]
            mf, mb, level = check_win(pred_front, pred_back, actual["front"], actual["back"], lt_code)
            pred["checked"] = True
            checked_any = True
            pred["actual_front"] = actual["front"]
            pred["actual_back"] = actual["back"]
            pred["match_front"] = mf
            pred["match_back"] = mb
            pred["prize_level"] = level
            prize_text = level or "未中奖"
            print(f"  核对{format_console_check(lt_code, {'period': pred['period'], 'match_f': mf, 'match_b': mb, 'prize': level})}")
            if str(pred["period"]) == str(latest["period"]):
                check_result = {
                    "period": pred["period"],
                    "pred_front": pred_front, "pred_back": pred_back,
                    "actual_front": actual["front"], "actual_back": actual["back"],
                    "match_f": mf, "match_b": mb, "prize": level,
                    "draw_date": actual.get("date", ""),
                }

        # 检查是否需要预测下一期
        prediction_data = build_prediction_data(existing)
        created_prediction = False
        if existing:
            print(f"  第{next_period}期已预测，跳过")
        else:
            if not API_KEY or not BASE_URL:
                print("  AI接口未配置，跳过预测")
                messages.append(f"{lt_info['name']}: AI接口未配置")
            elif not records:
                print("  获取历史数据失败")
                messages.append(f"{lt_info['name']}: 获取历史数据失败")
            else:
                print(f"  获取到 {len(records)} 期数据")
                history_text = format_history_text(records, lt_code)
                review_text = get_latest_review_text(data, lt_code, latest["period"], check_result)
                print(f"  近期复盘信息已生成，调用AI ({MODEL}) 预测第{next_period}期...")
                try:
                    results, recommended_f, recommended_b, used_model = predict_numbers(history_text, lt_code, review_text, 1)
                except Exception as e:
                    print(f"  AI预测失败: {e}")
                    results, recommended_f, recommended_b, used_model = [], [], [], MODEL

                if results:
                    draw_date = next_draw_date(latest.get("date", ""), lt_info["draw_days"])
                    store_prediction(data, lt_code, next_period, results, draw_date, used_model)
                    created_prediction = True
                    for i, (front, back) in enumerate(results):
                        print(f"  第{i+1}注: {format_console_prediction(lt_code, {'front': front, 'back': back})}")
                    print(f"  {lt_info['name']} 第{next_period}期预测完成，共{len(results)}注")

                    prediction_data = {
                        "period": next_period,
                        "numbers": [{"front": f, "back": b} for f, b in results],
                        "draw_date": draw_date,
                        "recommended_front": recommended_f,
                        "recommended_back": recommended_b,
                        "used_model": used_model,
                    }
                else:
                    print("  AI返回号码解析失败")
                    messages.append(f"{lt_info['name']}: AI预测失败")

        # 构建并发送该彩种的青龙通知
        latest_check_result = get_latest_check_result(data, lt_code, latest["period"], check_result)
        if not checked_any and not created_prediction:
            print(f"  {lt_info['name']}本次无新复盘或新预测，跳过通知")
            continue
        content = build_notification_content(data, lt_code, latest, latest_check_result, prediction_data)
        category_suffix = f"（{lt_info['category']}）" if lt_info.get("category") else ""
        title = f"{lt_info['name']}AI预测通知{category_suffix}"
        send_notify_once(data, lt_code, title, content)

        # 汇总消息（控制台打印用）
        msg_parts = [f"{lt_info['name']}:"]
        if latest_check_result:
            msg_parts.append(f"  {format_console_check(lt_code, latest_check_result)}")
        if prediction_data:
            for num in prediction_data["numbers"]:
                msg_parts.append(f"  第{prediction_data['period']}期预测: {format_console_prediction(lt_code, num)}")
        elif not latest_check_result:
            msg_parts.append("  无需处理")
        messages.append("\n".join(msg_parts))

    return True, messages


# ============================
# 离线自检
# ============================

def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="彩票AI预测 - 青龙面板脚本")
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="运行离线自检：不联网、不发通知、不保存数据、不要求 API 环境变量",
    )
    return parser.parse_args(argv)


def make_self_test_result(lottery_type, period, pred_front, pred_back, actual_front, actual_back):
    mf, mb, prize = check_win(pred_front, pred_back, actual_front, actual_back, lottery_type)
    return {
        "period": str(period),
        "pred_front": pred_front,
        "pred_back": pred_back,
        "actual_front": actual_front,
        "actual_back": actual_back,
        "match_f": mf,
        "match_b": mb,
        "prize": prize,
    }


def build_self_test_check_results(lottery_type):
    fixtures = {
        "dlt": [
            ([1, 2, 3, 4, 5], [1, 2], [1, 2, 6, 7, 8], [2, 3]),
            ([6, 7, 8, 9, 10], [3, 4], [11, 12, 13, 14, 15], [4, 5]),
            ([11, 12, 13, 14, 15], [5, 6], [11, 16, 17, 18, 19], [7, 8]),
        ],
        "ssq": [
            ([1, 2, 3, 4, 5, 6], [1], [1, 2, 7, 8, 9, 10], [1]),
            ([7, 8, 9, 10, 11, 12], [2], [13, 14, 15, 16, 17, 18], [3]),
            ([13, 14, 15, 16, 17, 18], [4], [13, 19, 20, 21, 22, 23], [4]),
        ],
        "qxc": [
            ([1, 2, 3, 4, 5, 6], [7], [1, 9, 3, 8, 5, 0], [7]),
            ([0, 1, 2, 3, 4, 5], [6], [9, 1, 8, 3, 7, 5], [10]),
            ([9, 8, 7, 6, 5, 4], [3], [0, 8, 0, 6, 0, 4], [2]),
        ],
        "pl3": [
            ([1, 2, 3], [], [1, 4, 3], []),
            ([4, 4, 5], [], [4, 5, 4], []),
            ([7, 7, 7], [], [7, 7, 7], []),
        ],
        "fc3d": [
            ([1, 2, 3], [], [3, 2, 1], []),
            ([4, 4, 5], [], [4, 5, 4], []),
            ([8, 8, 8], [], [8, 8, 0], []),
        ],
        "qlc": [
            ([1, 2, 3, 4, 5, 6, 7], [], [1, 2, 8, 9, 10, 11, 12], [7]),
            ([8, 9, 10, 11, 12, 13, 14], [], [1, 2, 3, 4, 5, 6, 7], [15]),
            ([15, 16, 17, 18, 19, 20, 21], [], [15, 22, 23, 24, 25, 26, 27], [21]),
        ],
    }
    return [
        make_self_test_result(lottery_type, index + 1, pred_front, pred_back, actual_front, actual_back)
        for index, (pred_front, pred_back, actual_front, actual_back) in enumerate(fixtures[lottery_type])
    ]


def run_self_test():
    print("运行离线自检：不联网、不发通知、不保存数据")
    for lottery_type in LOTTERY_TYPES:
        results = build_self_test_check_results(lottery_type)
        assert results, f"{lottery_type} fixture 为空"

        stats = build_structured_statistical_review(results, lottery_type)
        expected_kind = "position" if is_position_lottery(LOTTERY_TYPES[lottery_type]) else "set"
        assert stats["lottery_type"] == lottery_type
        assert stats["count"] == len(results)
        assert stats["kind"] == expected_kind
        assert stats["latest"] and stats["latest"]["period"] == results[0]["period"]
        baseline = stats.get("random_baseline")
        assert baseline and baseline["count"] == len(results)
        assert baseline["random_expected_prize_count"] >= 0

        review_text = build_deviation_review_text_from_results(results, lottery_type)
        assert isinstance(review_text, str) and review_text.strip()
        summary_lines = build_statistical_review_summary_lines({}, lottery_type, results)
        assert len(summary_lines) == 3
        assert all(isinstance(line, str) and line for line in summary_lines)
        assert all(len(line) <= 48 for line in summary_lines)
        baseline_lines = build_random_baseline_review_lines(results, lottery_type)
        assert baseline_lines and baseline_lines[0]
        baseline_line = build_random_baseline_summary_line(results, lottery_type)
        assert baseline_line

        combined_text = "\n".join([review_text, *summary_lines, *baseline_lines, baseline_line])
        if lottery_type == "qlc":
            assert "特别号覆盖" in combined_text
            assert "后区命中" not in combined_text
        if lottery_type == "qxc":
            assert "特别号" in combined_text
        if lottery_type in ("pl3", "fc3d"):
            assert "错位" in combined_text

        print(f"  {lottery_type}: OK")
    print("自检通过")
    return True


# ============================
# 主入口
# ============================

def main(argv=None):
    args = parse_args(argv)
    print(f"彩票AI预测 | 模型:{MODEL} | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    if args.self_test:
        try:
            run_self_test()
            return 0
        except AssertionError as e:
            print(f"自检失败: {e}")
            return 1
        except Exception as e:
            print(f"自检异常: {e}")
            return 1

    if not API_KEY or not BASE_URL:
        print("错误: 请设置环境变量 LOTTERY_API_KEY 和 LOTTERY_BASE_URL")
        return 1

    data = load_data()
    data = seed_fake_predictions(data)

    try:
        ok, messages = detect_and_process(data)
    except Exception as e:
        messages = [f"执行异常: {e}"]
        print(messages[0])
        ok = False

    # 保存数据
    save_data(data)

    # 打印汇总信息
    result = "\n".join(messages)
    print(f"\n{'='*30}")
    print(result)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
