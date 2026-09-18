# 快速上手（零基础版） · Quick start in Chinese

不需要懂命令行，也不需要装任何第三方库。三步：跑起来 → 改一个文件 → 上传。

## 第 1 步 · 跑起来（看到分数和回放）

| 你的电脑 | 做什么 |
|---|---|
| macOS | 双击 `run_baseline.command`（系统自带的 Python 就够用；若提示"无法打开"，右键 → 打开） |
| Windows | 先到 https://www.python.org/downloads/ 安装 Python 3.12（安装时勾选 **Add python.exe to PATH**），然后双击 `run_baseline.bat` |
| Linux | 终端里运行 `./run_baseline.sh` |

大约 15 秒后会弹出一个网页：这是基线智能体在公开场景上 180 个观测夜的回放。
终端里最后一段是分数，基线约 **12287 分**，`termination_reason` 应为 `survey_complete`。

只想先看一眼的话，把上面的文件名换成 `run_demo_week`（`.command` / `.bat` / `.sh`）：同样的流程、同样的评分器，场景只有 7 个观测夜，约 2 秒跑完，回放页也更容易逐夜看清楚。结果写在 `demo_week_output/`。

## 第 2 步 · 改一个文件

打开 `agent/my_strategy.py`。整个比赛你只需要改这一个文件里的 `choose_action` 函数：

- 平台每次把"现在能观测的候选"排好序交给你（第 0 个是估计收益最高的），
- 你返回想观测的那个候选，或者返回 `None` 表示这一时隙先等待。

文件里已经写好了几个可以直接取消注释的思路（优先 REQUIRED 瓦片、优先观测请求、条件差就等待、用 `memory` 记住做过什么）。
每个候选带有的字段和含义也写在文件开头。

改完保存，再双击一次 `run_baseline`，看分数有没有变高。运行出错时，终端会直接打印 `agent.log` 的最后几行。

## 第 3 步 · 上传

1. 打开比赛网站 → 注册 → 创建队伍（一个人也可以）。
2. 「提交」页 → 选 **智能体运行** → 把 `agent/my_strategy.py` 这一个文件拖进上传框（也可以拖整个 `agent` 文件夹，网站会替你打包）。
3. 页面会显示排队位置和评测进度，通常一两分钟出分；分数分解、每晚回放、日志都在提交页。

平台会自动把你的 `my_strategy.py` 和入门包里其余标准文件组装成完整程序包，你不用打 zip。

## 想更进一步

- 想在本地试更多天气：`python3 make_scenario.py --out scenarios/mine --seed 7 --days 30`，再运行 `python3 local_runner.py --scenario scenarios/mine --agent agent/minimal_agent.py`。
- 想让大模型参与决策：复制 `agent/.env.example` 为 `agent/.env`，填 `MODEL_PROVIDER` 与对应 API key（网站「控制台」页可领取赞助额度），上传时把整个 `agent` 文件夹拖进去即可。
- 完整的数据格式、协议和评分公式见网站「文档」页；`README.md` 是给工程师看的详细版。
