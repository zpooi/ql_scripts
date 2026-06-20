# lottery.py

彩票 AI 预测青龙脚本：自动获取最新开奖数据，核对上期预测结果，生成下一期预测，并通过 NapCat QQ 群或青龙通知推送结果。

> 彩票开奖结果具有随机性，本脚本生成的预测仅供娱乐和技术研究参考，不构成任何投注建议。

## 通知示例

![大乐透 AI 预测通知示例](img/dlt.jpg)

## 功能特性

- 自动抓取 500.com 历史开奖数据。
- 支持多种彩票类型：大乐透、双色球、7 星彩、排列 3、福彩 3D、七乐彩。
- 调用 OpenAI 兼容接口生成下一期预测号码。
- 自动核对历史预测与实际开奖结果。
- 基于近期预测偏差生成复盘信息，用于辅助下一轮提示词。
- 将预测、复盘、中奖核对结果保存到本地 JSON 数据文件。
- 支持 NapCat QQ 群图片通知，并可回退到青龙 `notify.py`。
- 内置离线自检模式，便于验证核心逻辑是否正常。

## 环境要求

- Python 3.10+
- 青龙面板或其他可定时执行 Python 脚本的环境

安装依赖：

```bash
pip install requests beautifulsoup4 pillow python-dotenv
```

其中：

- `requests`：请求开奖数据、AI 接口和通知接口。
- `beautifulsoup4`：解析开奖历史页面。
- `pillow`：生成图片通知，可选但推荐安装。
- `python-dotenv`：本地调试时读取 `.env`，可选。

## 快速开始

运行脚本：

```bash
python lottery.py
```

运行离线自检：

```bash
python lottery.py --self-test
```

离线自检不会联网、不会发通知、不会保存数据，也不要求配置 AI API Key。

## 环境变量

### AI 接口配置

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `LOTTERY_API_KEY` | 无 | AI 接口密钥，必填。 |
| `LOTTERY_BASE_URL` | 无 | OpenAI 兼容接口地址，脚本会请求 `{LOTTERY_BASE_URL}/chat/completions`，必填。 |
| `LOTTERY_MODEL` | `gpt-5.5` | 主模型名称。 |
| `LOTTERY_FALLBACK_MODEL` | `gemini-3-flash-preview` | 主模型失败时使用的容错模型。 |
| `LOTTERY_MAX_TOKENS` | `1200` | AI 最大输出 token 数。 |
| `LOTTERY_TEMPERATURE` | `0.2` | AI 采样温度。 |
| `LOTTERY_SEED` | `42` | AI 随机种子；留空则不传。 |

### 彩种配置

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `LOTTERY_ENABLE_TYPES` | 全部彩种 | 启用的彩种，多个用逗号、分号或空格分隔。 |

支持的彩种代码：

| 代码 | 彩种 | 开奖类型 |
| --- | --- | --- |
| `dlt` | 大乐透 | 体彩 |
| `ssq` | 双色球 | 福彩 |
| `qxc` | 7 星彩 | 体彩 |
| `pl3` | 排列 3 | 体彩 |
| `fc3d` | 福彩 3D | 福彩 |
| `qlc` | 七乐彩 | 福彩 |

示例：

```bash
LOTTERY_ENABLE_TYPES=dlt,ssq,fc3d
```

### 通知配置

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `NAPCAT_URL` | 无 | NapCat HTTP 服务地址，例如 `http://127.0.0.1:6198`。 |
| `NAPCAT_TOKEN` | 无 | NapCat access_token，可选。 |
| `LOTTERY_QQ_GROUP_ID` | 无 | 彩票通知专用 QQ 群号，多个群号可用逗号、分号或空格分隔。 |
| `QQ_GROUP_ID` | 无 | 通用 QQ 群号；未设置 `LOTTERY_QQ_GROUP_ID` 时使用。 |
| `HITOKOTO` | `true` | 是否在图片通知中附加每日一言，设置为 `false` 可关闭。 |
| `LOTTERY_FONT_PATH` | 无 | 图片通知中文字体路径。 |

如果未配置 NapCat，脚本会尝试调用青龙环境中的 `notify.py` 发送文本通知。

如果图片通知出现中文乱码、方块字或字体显示异常，可以上传一个中文字体文件到青龙面板脚本目录，例如 `/ql/data/scripts/msyh.ttc`、`/ql/data/scripts/simhei.ttf` 或 `/ql/data/scripts/NotoSansCJK-Regular.ttc`，然后将 `LOTTERY_FONT_PATH` 设置为该字体文件的完整路径。

## 数据文件

脚本会在同目录下维护：

```text
lottery_data.json
```

该文件用于保存：

- 历史开奖缓存
- 预测记录
- 已核对的开奖结果
- 通知指纹，避免重复推送相同内容

`lottery_data.json` 包含运行缓存和预测记录，公开仓库通常不需要提交该文件。

## 青龙面板配置示例

定时任务命令：

```bash
python3 lottery.py
```

示例环境变量：

```bash
LOTTERY_API_KEY=your_api_key
LOTTERY_BASE_URL=https://your-openai-compatible-api.example.com/v1
LOTTERY_MODEL=gpt-5.5
LOTTERY_ENABLE_TYPES=dlt,ssq,pl3,fc3d
NAPCAT_URL=http://127.0.0.1:6198
LOTTERY_QQ_GROUP_ID=123456789
HITOKOTO=false
```

## 本地调试

脚本同目录可创建 `.env` 文件用于本地调试：

```env
LOTTERY_API_KEY=your_api_key
LOTTERY_BASE_URL=https://your-openai-compatible-api.example.com/v1
LOTTERY_MODEL=gpt-5.5
LOTTERY_ENABLE_TYPES=dlt,ssq
HITOKOTO=false
```

`.env` 通常包含密钥等敏感配置，不应提交到公开仓库。

## 免责声明

本项目仅用于 Python 脚本编写、自动化任务、数据抓取与 AI 接口调用等技术学习场景。彩票预测没有确定性，任何基于本脚本输出进行的决策均由使用者自行承担风险。

## 致谢

- [LINUX DO](https://linux.do) — 中文开发者社区，感谢社区里关于 AI 代理、技能、自媒体工作流程和内容生产实践的讨论。

## License

本项目基于 MIT License 开源，详见 [LICENSE](LICENSE)。
