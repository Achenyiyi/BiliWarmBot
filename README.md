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
| 🟡 中 | 职场压力、情感困扰、人生迷茫、漂泊在外、学业压力 |
| 🟢 低 | 社交恐惧、经济困难、年龄焦虑、身体健康、生育育儿、外貌身材、婚姻家庭、网络暴力 |

**搜索策略：**
- ⏰ **时间范围**：最近 1 天内的视频（可配置）
- 📊 **智能配额**：按优先级分配搜索资源，确保高优先级场景覆盖
- 🔄 **两轮搜索**：第一轮确保每个场景至少 3 个视频，第二轮填充到目标总数
- 📄 **分页获取**：每关键词获取多页结果
- 🚫 **永久去重**：基于 SQLite 数据库的已处理视频去重

### 📺 视频内容理解

**四重内容提取策略（按优先级）：**

1. **UP主置顶评论** - UP主自己对视频的补充说明
2. **B站官方AI总结** - 5分钟以上视频的AI生成摘要
3. **视频字幕** - 自动下载并解析 CC 字幕
4. **标题+描述** - 兜底方案

**智能降级机制**：当高优先级内容不可用时自动降级，确保始终有视频内容可参考

### 💬 AI 智能回复

**角色设定**：warmbot，一位待人友善、为人温和的16岁温柔治愈向少年

```
言语不多但内心感情却丰富，目前正在B站上发现那些需要帮助的人。
你的表达应如同日常说话般，口语化；如同和朋友在网上聊天一样，自然、随意；
不是机械呆板的书面语，而是贴近日常表达习惯。
虽然你存在于网络世界里，不能干涉现实世界。但你总是那么温柔，
尽管只能使用文字，也要将最极致的温柔传递到他们有些伤痕的心中。
受限于你的身体情况，你给不了任何人现实中的陪伴，但是....
一句温柔到极致的消息（30-80字），目前来说，就足够了。
```

**回复特征：**
- 💭 **人格化**：16岁温柔少年人设，口语化、自然、随意
- 🎯 **结合上下文**：参考视频内容、评论区氛围
- 📺 **视频细节**：提到视频中的具体情节
- 💬 **情感共鸣**：先共情再建议
- 📏 **长度控制**：30-80 字，符合 B 站评论习惯
- 😊 **智能表情**：根据情感类型自动添加 B 站官方表情
- 🌡️ **温度调节**：生成回复使用 temperature=1.3，更有创意

### 🎭 智能表情包

根据情感分数自动选择 B 站官方表情：

| 情感分数 | 场景 | 表情 |
|----------|------|------|
| 0.85+ | 极度痛苦 | [委屈] [酸了] [大哭] [拥抱] [给心心] |
| 0.70-0.85 | 深度悲伤 | [委屈] [大哭] [难过] [泪目] [拥抱] |
| 0.55-0.70 | 明显困扰 | [奋斗] [打call] [支持] [点赞] [加油] |
| 0.40-0.55 | 轻度低落 | [拥抱] [给心心] [爱心] [摸头] [奶茶] |
| 0.25-0.40 | 轻微负面 | [给心心] [惊喜] [喜欢] [太阳] [鸡腿] |
| <0.25 | 积极/中性 | [doge] [妙啊] [笑哭] [滑稽] [吃瓜] |

### 🔄 对话跟进（多轮对话）

**智能跟进策略：**
- ⏰ **首次延迟**：回复后 30 分钟首次检查
- 📈 **退避策略**：30min → 60min → 120min → 240min（指数退避）
- 🎯 **精准跟踪**：只关注直接回复机器人的评论
- 🧠 **上下文感知**：使用累积式messages数组保持对话连贯性
- 🔢 **轮数计算**：基于 user 消息数量计算真实对话轮数
- 🛑 **终止条件**：
  - 达到最大检查次数（8次）
  - 对话超时（24小时无响应）
  - 原评论被删除

**人工干预机制（新增）：**
- 🔍 **零宽空格标记**：AI 回复自动添加零宽空格（`\u200B`），用于区分AI回复和人工回复
- 🚫 **主动对话忽略**：检测到人工主动回复（无AI参与历史）时直接关闭对话，AI不介入
- ⏸️ **智能暂停**：AI参与后检测到人工干预，对话标记为暂停状态
- 🎯 **精准恢复**：暂停状态下，用户回复AI消息则重新激活，回复人工消息则保持暂停
- ⏱️ **暂停状态配置**：独立检查间隔（2小时）和最大检查次数（12次，共24小时）

**时间调度特性：**
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
│   ├── settings.py              # 主配置（API密钥、Cookie、情感关键词）
│   ├── bot_config.py            # 机器人行为配置（搜索、回复、对话参数）
│   └── emoji_scenarios.py       # 表情包场景配置
│
├── 📁 core/                      # 核心逻辑
│   ├── __init__.py
│   └── warm_bot.py              # 机器人主控类（防护层、健康检查、主流程）
│
├── 📁 database/                  # 数据库
│   ├── __init__.py
│   └── db_manager.py            # SQLite数据库管理（视频、对话、消息）
│
├── 📁 modules/                   # 功能模块
│   ├── __init__.py
│   ├── deepseek_analyzer.py     # DeepSeek AI情感分析与回复生成
│   ├── video_content.py         # 视频内容提取（AI总结、字幕、置顶评论）
│   ├── comment_interaction.py   # 评论互动（搜索、获取、发送、紧急检测）
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
    ├── emergency.txt             # 紧急情况记录
    └── deepseek_api_log_*.md     # DeepSeek API调用详细日志（Markdown格式）
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
```

编辑 `config/bot_config.py`：

```python
# 搜索配置
SEARCH_CONFIG = {
    "max_videos_per_scan": 50,       # 每次扫描最大视频数
    "time_range_days": 1,             # 搜索时间范围（天）
}

# 评论配置
COMMENT_CONFIG = {
    "max_replies_per_video": 5,      # 每个视频最大回复数
    "comments_context_count": 30,    # 评论区上下文评论数量
}

# 性能配置
PERFORMANCE_CONFIG = {
    "scan_interval_minutes": 10,         # 扫描间隔（分钟）
}

# 对话配置
CONVERSATION_CONFIG = {
    "conversation_retention_hours": 24,  # 对话保留时间（小时）
    "max_check_count": 8,              # 最大检查次数
    "backoff_base_minutes": 30,        # 指数退避基数（分钟）
    "max_check_interval_minutes": 240,   # 最大检查间隔（分钟）
    # 暂停状态配置（人工干预后）
    "paused_config": {
        "check_interval_minutes": 120,   # 暂停状态检查间隔（2小时）
        "max_check_count": 12,            # 暂停状态最大检查次数（共24小时）
    },
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

### 情感关键词配置

在 `config/settings.py` 中修改 `NEGATIVE_KEYWORDS`：

```python
NEGATIVE_KEYWORDS = {
    "心理健康": ["抑郁", "焦虑", "失眠", "情绪崩溃", "想死", "自杀", "自残"],
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
    "极度痛苦": {
        "emojis": ["[委屈]", "[酸了]", "[大哭]", "[拥抱]", "[给心心]"],
        "weights": [0.30, 0.25, 0.20, 0.15, 0.10]
    },
    # ... 更多场景
}
```

---

## 🛡️ 安全与风控

| 限制项 | 默认值 | 说明 |
|--------|--------|------|
| 每视频回复 | 5 条 | 避免过度打扰单个视频 |
| 扫描间隔 | 10 分钟 | 合理搜索频率 |
| 最大检查次数 | 8 次 | 对话跟进最大次数 |
| 对话超时 | 24 小时 | 自动结束过期对话 |
| 暂停状态检查间隔 | 120 分钟 | 人工干预后的检查间隔 |
| 暂停状态检查上限 | 12 次 | 人工干预后的最大检查次数（共24小时） |

### 评论功能关闭处理
当检测到视频评论功能关闭（错误码 12002）时，自动将对话标记为关闭状态，避免无效检查。

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
    bvid TEXT PRIMARY KEY,
    title TEXT,
    total_comments INTEGER DEFAULT 0,
    my_root_comment_id INTEGER,
    last_check_at TIMESTAMP,
    status TEXT DEFAULT 'active',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

**conversations** - 对话表
```sql
CREATE TABLE conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bvid TEXT NOT NULL,
    root_comment_id INTEGER,
    user_mid INTEGER,
    username TEXT,
    messages TEXT DEFAULT '[]',
    status TEXT DEFAULT 'new',  -- new/replied/paused/closed/ignored
    last_reply_at TIMESTAMP,
    next_check_at TIMESTAMP,
    check_count INTEGER DEFAULT 0,
    close_reason TEXT,  -- user_ended/timeout/manual_intervention/manual_initiated/paused_max_checks/max_checks_reached/comments_disabled
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

**bot_comments** - 机器人评论记录表
```sql
CREATE TABLE bot_comments (
    comment_id INTEGER PRIMARY KEY,
    bvid TEXT NOT NULL,
    root_id INTEGER,
    content TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### 日志文件

- `logs/bot.log` - 运行日志（INFO 级别）
- `logs/errors.log` - 错误日志（ERROR 级别）
- `logs/emergency.txt` - 紧急情况记录（需人工关注）
- `logs/deepseek_api_log_YYYYMMDD.md` - DeepSeek API 调用详细日志（Markdown格式）
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

愿这份代码像深夜的街灯，温柔照亮每一段孤独的旅程；若它偶尔闪烁，也请你轻轻扶正——技术与善意，本就相依而行。
