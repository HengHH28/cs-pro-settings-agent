# CS Pro Settings Agent

CS2 职业选手设置查询 Agent：用 DeepSeek 大模型驱动，从本地 SQLite 数据库回答选手的灵敏度、DPI、分辨率、准星等游戏设置。

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
python database/update_all_players.py
```

数据来自 ProSettings（游戏内设置）和 Liquipedia（姓名、战队、荣誉）。

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
## License & Data Sources

- 本项目使用 MIT License，见 LICENSE。
- 选手数据来自 ProSettings 与 Liquipedia，版权归原网站所有，详见 NOTICE。