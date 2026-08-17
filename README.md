# CS Pro Settings Agent

查询 CS2 职业选手游戏设置的命令行助手：用大模型（DeepSeek）驱动，从本地 SQLite 数据库回答选手的灵敏度、DPI、分辨率、准星等设置，支持昵称 / 真名 / 战队 / 别名搜索。

> 非官方项目，与 Valve、ProSettings、Liquipedia 均无隶属关系；数据仅供学习与个人查询使用。

## 功能

- 一行命令查询：`python main.py zywoo 灵敏度是多少`
- 交互式问答：`python main.py`
- 支持昵称、真实姓名、战队、别名（如 simple → s1mple）搜索
- 设置历史对比：`python main.py zywoo 之前的灵敏度是多少`
- 编程模式：`python main.py --coding 帮我修改 xxx`

## 安装

```powershell
python -m venv venv
venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

在项目根目录创建 `.env`，写入：

```
DEEPSEEK_API_KEY=你的密钥
```

## 使用

```powershell
# 单次查询
python main.py zywoo 灵敏度是多少

# 按真名 / 战队查
python main.py Mathieu Herbaut
python main.py Vitality

# 编程模式（可读写项目文件、跑测试）
python main.py --coding 帮我看看 main.py 写了什么

# 交互模式
python main.py
```

## 更新选手数据

要跟踪的选手写在 `database/players.txt`，每行一个昵称，`#` 开头是注释。想新增选手就加一行，然后：

```powershell
# 全量更新（默认抓取方式）
python database/update_all_players.py

# 使用 Liquipedia 官方批量 API（推荐，千名选手只需几十次请求）
python database/update_all_players.py --liquipedia-batch

# 只补抓缺少基本资料（真名 / 战队）的选手
python database/update_all_players.py --liquipedia-batch --fill-missing

# 补抓统计字段（Major 冠军 / HLTV MVP 等），旧数据里的 0 视为缺失
python database/update_all_players.py --liquipedia-batch --fill-stats
```

数据来自 ProSettings（游戏内设置）和 Liquipedia（姓名、战队、荣誉）。

## 数据来源与版权

- 游戏内设置数据来自 [ProSettings](https://prosettings.net)。
- 选手资料、战队、荣誉数据来自 [Liquipedia - Counter-Strike](https://liquipedia.net/counterstrike)。Liquipedia 内容按 [CC BY-SA 3.0](https://creativecommons.org/licenses/by-sa/3.0/) 授权，本项目已注明来源；若再分发源自 Liquipedia 的文本或汇编内容，请遵守该许可并保留署名。
- `database/players.json` 是少量选手的基线示例数据，仅供演示。
- 抓取遵循原网站要求：只使用官方 API、携带含联系方式的 User-Agent、限制请求频率（普通请求 ≥ 2 秒，parse 请求 ≥ 30 秒）。
- 详细声明见 [NOTICE](NOTICE)。

## 测试

```powershell
python -m pytest -q
```

测试会自动备份并恢复数据库，不会破坏真实数据。

## 数据库结构

四张表：

- `players` — 选手基础信息
- `settings` — 最新设置（含 `updated_at` 抓取时间、`hz` 回报率、`zoom_sensitivity` 开镜灵敏度等）
- `statistics` — 战绩（Major 冠军、HLTV MVP、Rating）
- `settings_history` — 设置历史快照，每名选手最多保留最近 20 条

## 注意事项

- 更新数据请用 `update_all_players.py`。
- `create_database.py` 会把数据库重置为 `players.json` 基线（会清空爬虫数据），只有确认要重置时才加 `--force` 运行。

## License

- 代码使用 MIT License，见 [LICENSE](LICENSE)。
- 数据来源声明见 [NOTICE](NOTICE)。
