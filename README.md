# 🌟 温暖陪伴机器人 (BiliWarmBot)

[![Python](https://img.shields.io/badge/Python-3.8%2B-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Bilibili](https://img.shields.io/badge/Bilibili-API-pink)](https://github.com/nemo2011/bilibili-api)

一个基于 Bilibili API 和 DeepSeek AI 的温暖陪伴机器人，自动发现需要情感支持的用户，并给予自然、温暖的回复。

> 💡 **项目理念**：在这个快节奏的社会中，很多人在网上倾诉自己的困扰和痛苦。这个机器人希望能给那些孤独的人一点温暖，让那些被忽视的声音被听见，在冰冷的互联网中传递一点人情味。

---

## ✨ 核心功能

### 🎯 智能视频发现

**覆盖 16 大类情感场景：**

| 优先级 | 场景类别 |
|--------|----------|
| 🔴 高 | 心理健康、原生家庭、失去 |
| 🟡 中 | 职场压力、情感困扰、人生迷茫、漂泊在外 |
| 🟢 低 | 学业压力、社交恐惧、经济困难、身体健康、年龄焦虑、生育育儿、外貌身材、婚姻家庭、网络暴力 |

**搜索策略：**
- ⏰ **时间范围**：最近 1-7 天内的视频（可配置）
- 📊 **智能配额**：按优先级分配搜索资源，确保高优先级场景覆盖
- 🔍 **关键词轮换**：每场景最多使用 N 个关键词，避免过度搜索
- 📄 **分页获取**：每关键词获取多页结果
- 🚫 **永久去重**：基于 SQLite 数据库的已处理视频去重

### 📺 视频内容理解

**四重内容提取策略（按优先级）：**

1. **UP主置顶评论** - UP主自己对视频的补充说明
2. **B站官方AI总结** - 5分钟以上视频的AI生成摘要
3. **视频字幕** - 自动下载并解析 CC 字幕
4. **标题+描述** - 兜底方案

### 💬 AI 智能回复

**角色设定**：19-25岁B站老用户

```
平时就爱刷情感区、吐槽区、树洞视频，评论区发言超随性。
不是机器人，不是客服，就是一个普通的B站用户。
说话方式：
- 语气词很多（啊、呢、吧、啦）
- 用B站常见表达（破防了、泪目、真实）
- 偶尔带点小吐槽
- 结合视频细节（up主表情、BGM、台词）
- 分享一点点自己的"小破事"
- 回复短小精悍（10-50字），自然结束，无鸡汤
```

**回复特征：**
- 💭 **人格化**：模拟真实 B 站用户说话方式
- 🎯 **结合上下文**：参考视频内容、UP主置顶评论
- 📺 **视频细节**：提到视频中的具体情节
- 💬 **情感共鸣**：先共情再建议
- 📏 **长度控制**：10-50 字，符合 B 站评论习惯
- 😊 **智能表情**：根据情感类型自动添加 B 站官方表情

**示例：**
```
视频：关于原生家庭创伤的倾诉
评论：我爸妈从小就对我很严格，考不好就骂，现在工作了还是这样

回复：啊这…太真实了[委屈] 我爸妈也是永远不满意 up主说的"连呼吸都是错"真的破防了
```

### 🎭 智能表情包

根据情感类型自动选择 B 站官方表情：

| 场景 | 表情 |
|------|------|
| 悲伤共情 | [委屈] [大哭] [难过] [酸了] [捂脸] [生病] [泪目] [哭泣] [伤心] |
| 心疼理解 | [委屈] [酸了] [大哭] [难过] [生病] [疼] [拥抱] [给心心] [泪目] |
| 安慰陪伴 | [拥抱] [给心心] [爱心] [害羞] [脸红] [惊喜] [摸头] [奶茶] [汤圆] |
| 鼓励加油 | [奋斗] [打call] [支持] [点赞] [墨镜] [胜利] [加油] [锦鲤] [干杯] |
| 温暖治愈 | [给心心] [惊喜] [星星眼] [喜欢] [害羞] [脸红] [爱心] [太阳] [鸡腿] |
| 轻松幽默 | [doge] [妙啊] [脱单doge] [笑哭] [喜极而泣] [偷笑] [滑稽] [吃瓜] [歪嘴] |

### 🔄 对话跟进（多轮对话）

**智能跟进策略**：
- ⏰ **首次延迟**：回复后 30 分钟首次检查
- 📈 **退避策略**：30min → 60min → 120min → 240min（指数退避）
- 🎯 **精准跟踪**：只关注直接回复机器人的评论
- 👥 **上下文感知**：收集评论区其他用户讨论作为 AI 参考
- 🛑 **终止条件**：
  - 达到最大检查次数（8次）
  - 对话超时（24小时无响应）
  - 原评论被删除

**时间调度特性**：
- 基于实际系统时间计算
- 项目停止后重启也能保持正确间隔
- 使用数据库记录下次检查时间，确保不遗漏检查

---

## 🖥️ 运行示例

```
============================================================
🚀 温暖陪伴机器人启动
============================================================

📋 检查待跟进对话...
   发现 3 个对话需要检查
   💬 对话 15: 收到 1 条新回复
   ⏳ 对话 22: 无新回复，60分钟后再次检查(第2次)
   🔒 对话 8: 超过24小时未回复，已关闭

🔍 开始扫描新视频...
   搜索范围: 最近1天
   场景覆盖: 16个类别

搜索: 心理健康:3关键词 | 原生家庭:3关键词 | ...

结果: 心理健康:10 | 原生家庭:8 | 职场压力:12 | 共30个

📺 [1/30] [心理健康] 关于抑郁，我想说说... | BV1xx411x7xx
   来源: UP主置顶评论
   评论: 6/20条已扫描
   来了... | 跳过
   我每天都... | 已回复: 我懂这种感觉...
   完成: 1回复 0错
```

---

## 📁 项目结构

```
warm_bot/
├── 📄 main.py                    # 主入口
├── 📄 requirements.txt           # 依赖
├── 📄 README.md                  # 项目文档
├── 📄 LICENSE                    # 开源协议 (MIT)
├── 📄 .gitignore                 # Git忽略文件
│
├── 📁 config/                    # 配置文件
│   ├── __init__.py
│   ├── settings.py              # 主配置（API密钥、Cookie、搜索参数）
│   ├── bot_config.py            # 机器人行为配置
│   └── emoji_scenarios.py       # 表情包场景配置
│
├── 📁 core/                      # 核心逻辑
│   ├── __init__.py
│   └── warm_bot.py              # 机器人主控类
│
├── 📁 database/                  # 数据库
│   ├── __init__.py
│   └── db_manager.py            # SQLite数据库管理
│
├── 📁 modules/                   # 功能模块
│   ├── __init__.py
│   ├── deepseek_analyzer.py     # DeepSeek AI情感分析与回复生成
│   ├── video_content.py         # 视频内容提取（字幕、AI总结、置顶评论）
│   ├── comment_interaction.py   # 评论互动（搜索、获取、发送）
│   └── comment_context.py       # 评论区上下文获取
│
├── 📁 utils/                     # 工具类
│   ├── __init__.py
│   ├── circuit_breaker.py       # 熔断器（API故障保护）
│   ├── rate_limiter.py          # 限流器（防止请求过快）
│   └── retry_handler.py         # 重试机制
│
└── 📁 logs/                      # 日志目录（不会被Git跟踪）
    ├── bot.log                   # 运行日志
    ├── errors.log                # 错误日志
    └── emergency.txt             # 紧急情况记录
```

---

## 🚀 快速开始

### 1. 环境要求

- Python 3.8+
- pip

### 2. 安装依赖

```bash
git clone https://github.com/yourusername/BiliWarmBot.git
cd BiliWarmBot
pip install -r requirements.txt
```

### 3. 配置

编辑 `config/settings.py`：

```python
# DeepSeek API 配置
DEEPSEEK_API_KEY = "your-api-key-here"

# B站 Cookie 配置（从浏览器开发者工具复制）
BILIBILI_COOKIE = """SESSDATA=xxx; bili_jct=xxx; buvid3=xxx; DedeUserID=xxx; ..."""

# 搜索配置
SEARCH_CONFIG = {
    "scan_interval_minutes": 20,      # 扫描间隔（分钟）
    "max_videos_per_scan": 100,       # 每次扫描最大视频数
    "time_range_days": 1,             # 搜索时间范围（天）
    "keyword_per_scene": 3,           # 每场景最多使用关键词数
}

# 评论配置
COMMENT_CONFIG = {
    "max_comments_per_hour": 100,     # 每小时最大评论数
    "max_replies_per_video": 50,      # 每个视频最大回复数
    "reply_interval_min": 3,          # 回复间隔最小值（秒）
    "reply_interval_max": 5,          # 回复间隔最大值（秒）
    "max_conversation_rounds": 10,    # 最大对话轮数
    "conversation_timeout_hours": 48, # 对话超时时间（小时）
}
```

**获取 B 站 Cookie 方法：**
1. 登录 B 站网页版
2. 按 F12 打开开发者工具
3. 切换到 Network/网络标签
4. 刷新页面，找到任意请求
5. 在请求头中找到 Cookie，复制完整内容

### 4. 运行

```bash
python main.py
```

按 `Ctrl+C` 停止程序。

---

## ⚙️ 配置说明

### 关键词配置

在 `config/settings.py` 中修改 `NEGATIVE_KEYWORDS`：

```python
NEGATIVE_KEYWORDS = {
    "心理健康": ["抑郁", "焦虑", "失眠", "崩溃", "想死", "自杀", "自残"],
    "原生家庭": ["原生家庭", "父母控制", "童年阴影", "情感忽视", "家暴"],
    "职场压力": ["996", "加班", "裁员", "失业", "职场PUA", "内卷"],
    # ... 更多场景
}
```

### 紧急关键词

在 `config/settings.py` 中配置 `EMERGENCY_KEYWORDS`，当检测到这些关键词时会触发特殊关怀模式：

```python
EMERGENCY_KEYWORDS = [
    "自杀", "想死", "活不下去", "结束生命", "不想活了",
    "自残", "割腕", "跳楼", "安眠药", "死了算了",
    # ... 更多关键词
]
```

### 表情包配置

在 `config/emoji_scenarios.py` 中配置：

```python
SCENARIO_EMOJIS = {
    "悲伤共情": {
        "emojis": ["[委屈]", "[大哭]", "[难过]", "[酸了]"],
        "weights": [0.35, 0.25, 0.20, 0.20]
    },
    # ... 更多场景
}
```

---

## 🛡️ 安全与风控

| 限制项 | 默认值 | 说明 |
|--------|--------|------|
| 每小时评论 | 100 条 | 防止频繁操作触发风控 |
| 每视频回复 | 50 条 | 避免过度打扰单个视频 |
| 评论间隔 | 3-5 秒 | 模拟真人操作间隔 |
| 扫描间隔 | 20 分钟 | 合理搜索频率 |
| 最大检查次数 | 8 次 | 对话跟进最大次数 |
| 对话超时 | 24 小时 | 自动结束过期对话 |
| AI 并发处理 | 10 个 | 控制 API 调用成本 |

### 紧急关键词检测

当检测到以下关键词时，会标记为紧急情况：
- 自杀、想死、不想活了、活着没意思
- 自残、割腕、跳楼、安眠药

**处理方式：**
- 使用更温暖、更陪伴的语气回复
- 记录到 `logs/emergency.txt` 供人工关注
- 避免直接建议打热线（可能让用户反感）

---

## 💾 数据存储

### 数据库表结构

**tracked_videos** - 视频追踪表
```sql
CREATE TABLE tracked_videos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bvid TEXT UNIQUE NOT NULL,        -- 视频BV号
    title TEXT NOT NULL,              -- 视频标题
    category TEXT NOT NULL,           -- 情感场景分类
    summary TEXT,                     -- 视频摘要
    processed_at TIMESTAMP,           -- 处理时间
    total_comments INTEGER DEFAULT 0  -- 评论总数
);
```

**conversations** - 对话表
```sql
CREATE TABLE conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bvid TEXT NOT NULL,               -- 视频BV号
    root_comment_id INTEGER NOT NULL, -- 根评论ID
    user_mid INTEGER NOT NULL,        -- 用户MID
    username TEXT NOT NULL,           -- 用户名
    messages TEXT,                    -- 对话消息JSON
    status TEXT DEFAULT 'new',        -- 状态：new/replied/closed
    check_count INTEGER DEFAULT 0,    -- 检查次数
    next_check_at TIMESTAMP,          -- 下次检查时间
    last_reply_at TIMESTAMP,          -- 最后回复时间
    close_reason TEXT                 -- 关闭原因
);
```

**bot_comments** - 机器人评论记录表
```sql
CREATE TABLE bot_comments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    comment_id INTEGER UNIQUE,        -- 评论ID
    bvid TEXT NOT NULL,               -- 视频BV号
    root_id INTEGER,                  -- 根评论ID
    content TEXT,                     -- 评论内容
    created_at TIMESTAMP              -- 创建时间
);
```

### 日志文件

- `logs/bot.log` - 运行日志（INFO 级别）
- `logs/errors.log` - 错误日志（ERROR 级别）
- `logs/emergency.txt` - 紧急情况记录（需人工关注）
- `database/warm_bot.db` - SQLite 数据库

---

## 🤝 贡献指南

欢迎提交 Issue 和 Pull Request！

### 开发流程

1. Fork 本仓库
2. 创建特性分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 打开 Pull Request

### 代码规范

- 遵循 PEP 8 规范
- 添加必要的注释和文档字符串
- 保持代码简洁清晰
- 提交前运行测试

---

## 📜 开源协议

本项目基于 [MIT](LICENSE) 协议开源。

---

## 🙏 致谢

- [bilibili-api](https://github.com/nemo2011/bilibili-api) - Bilibili API Python 封装
- [DeepSeek](https://deepseek.com/) - 国产大语言模型

---

## ⚠️ 免责声明

本项目仅供学习和研究使用。使用本工具时请遵守以下原则：

1. **遵守 B 站社区规则**，不要滥用 API
2. **尊重用户隐私**，不要收集敏感信息
3. **适度使用**，避免对服务器造成压力
4. **紧急情况**，当检测到严重心理危机时，建议人工介入

开发者不对因使用本工具造成的任何后果负责。
