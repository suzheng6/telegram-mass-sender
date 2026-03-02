# Telegram群发小帮手

多账号 Telegram 消息群发工具，支持文本和语音消息。

## 功能特点

- 多账号管理与状态监控
- tdata 导入（支持 Telegram Desktop / AyuGram）
- 智能分配批量发送
- 实时账号状态检测（正常/受限/冻结/离线）
- 语音条消息发送（拖入 .ogg 文件）
- 自动检测更新

## 安装

### 方式一：直接下载 EXE（推荐）

从 [Releases](https://github.com/suzheng6/telegram-mass-sender/releases) 下载最新版本的 `TelegramSender.exe`，双击运行即可。

### 方式二：从源码运行

```bash
# 克隆仓库
git clone https://github.com/suzheng6/telegram-mass-sender.git
cd telegram-mass-sender

# 安装依赖
pip install -r requirements.txt

# 运行
python telegram_multi_sender_gui.py
```

## 使用说明
（程序会生成配置和登录文件，请新建一个文件夹放入使用，避免误删配置文件）
1. **导入账号**：点击「导入 tdata」选择 Telegram 的 tdata 文件夹
2. **选择分组**：点击账号卡片选中要使用的分组（支持多选）
3. **输入目标**：在「目标用户」框输入用户名或手机号（每行一个，不需要 @）
4. **输入消息**：在「消息内容」框输入要发送的文本，或拖入 .ogg 文件发送语音（支持多条语音）
5. **更改配置**：选择发送间隔（默认8000毫秒到15000毫秒）和发送消息数量（推荐1）
6. **开始发送**：点击「开始发送」按钮

## 注意事项

- 请合理控制发送频率，避免账号被限制
- 语音消息仅支持 .ogg 格式
- 拖入文件功能需要以普通权限运行（非管理员）

## 依赖

- customtkinter >= 5.2.0
- telethon >= 1.34.0
- opentele >= 1.15.1
- windnd >= 1.0.7

## 许可证

MIT License
