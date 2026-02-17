#!/usr/bin/env python3
"""Telegram群发小帮手

高端商业级界面设计，支持:
  - 多账号管理与状态监控
  - tdata 导入（Telegram Desktop / AyuGram）
  - 智能分配批量发送
  - 实时状态检测
  - 语音条消息发送（.ogg 文件拖拽）
  - 自动检测更新
"""
import asyncio
import os
import sys
import threading
import queue
from datetime import datetime
from typing import Optional, List, Dict, Tuple
from dataclasses import dataclass
from enum import Enum

# GUI 框架
try:
    import customtkinter as ctk
    from tkinter import filedialog, messagebox
    import tkinter as tk
    from tkinter import ttk
except ImportError:
    print("请先安装 customtkinter: pip install customtkinter")
    sys.exit(1)

# 拖拽支持（可选，pip install windnd）
try:
    import windnd
    WINDND_AVAILABLE = True
except ImportError:
    WINDND_AVAILABLE = False

# 导入核心功能
try:
    from telegram_multi_sender import (
        AccountManager, MultiSender, TelegramAccount,
        OPENTELE_AVAILABLE, OPENTELE_ERROR, SESSION_DIR
    )
except ImportError as e:
    print(f"导入 telegram_multi_sender 失败: {e}")
    sys.exit(1)

# 版本和更新
try:
    from version import VERSION, APP_NAME
    from updater import check_for_updates_on_startup
    UPDATER_AVAILABLE = True
except ImportError:
    VERSION = "1.0.0"
    APP_NAME = "Telegram群发小帮手"
    UPDATER_AVAILABLE = False


# ==================== 主题配置 ====================

class ThemeColors:
    """专业深色主题配色"""
    # 背景色
    BG_DARK = "#0d1117"
    BG_SECONDARY = "#161b22"
    BG_CARD = "#21262d"
    BG_HOVER = "#30363d"
    
    # 边框
    BORDER = "#30363d"
    BORDER_LIGHT = "#484f58"
    
    # 文字
    TEXT_PRIMARY = "#f0f6fc"
    TEXT_SECONDARY = "#8b949e"
    TEXT_MUTED = "#6e7681"
    
    # 强调色
    ACCENT_BLUE = "#58a6ff"
    ACCENT_GREEN = "#3fb950"
    ACCENT_YELLOW = "#d29922"
    ACCENT_RED = "#f85149"
    ACCENT_PURPLE = "#a371f7"
    ACCENT_ORANGE = "#db6d28"
    
    # 渐变起止色
    GRADIENT_START = "#238636"
    GRADIENT_END = "#2ea043"
    
    # 状态色
    STATUS_ONLINE = "#3fb950"
    STATUS_RESTRICTED = "#d29922"
    STATUS_FROZEN = "#f85149"
    STATUS_OFFLINE = "#6e7681"
    STATUS_CHECKING = "#58a6ff"


class AccountStatus(Enum):
    """账号状态枚举"""
    UNKNOWN = ("未知", ThemeColors.TEXT_MUTED, "○")
    CHECKING = ("检测中", ThemeColors.STATUS_CHECKING, "◐")
    ONLINE = ("正常", ThemeColors.STATUS_ONLINE, "●")
    RESTRICTED = ("受限", ThemeColors.STATUS_RESTRICTED, "◉")
    FROZEN = ("冻结", ThemeColors.STATUS_FROZEN, "✖")
    OFFLINE = ("离线", ThemeColors.STATUS_OFFLINE, "○")


# 配置 customtkinter
ctk.set_appearance_mode("dark")


# ==================== 异步辅助 ====================

class AsyncHelper:
    """异步任务辅助类"""
    
    def __init__(self):
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.thread: Optional[threading.Thread] = None
        self._start_loop()
    
    def _start_loop(self):
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()
    
    def _run_loop(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()
    
    def run(self, coro, callback=None):
        future = asyncio.run_coroutine_threadsafe(coro, self.loop)
        if callback:
            future.add_done_callback(lambda f: callback(f.result()))
        return future


# ==================== 自定义组件 ====================

class GradientFrame(ctk.CTkFrame):
    """带渐变效果的框架"""
    
    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        self.configure(
            fg_color=ThemeColors.BG_CARD,
            corner_radius=12,
            border_width=1,
            border_color=ThemeColors.BORDER
        )


class StatusBadge(ctk.CTkFrame):
    """状态徽章组件"""
    
    def __init__(self, master, status: AccountStatus = AccountStatus.UNKNOWN, **kwargs):
        super().__init__(master, **kwargs)
        self.configure(
            fg_color="transparent",
            corner_radius=8,
            height=28
        )
        
        self.status = status
        self.indicator = ctk.CTkLabel(
            self,
            text=status.value[2],
            text_color=status.value[1],
            font=ctk.CTkFont(size=14),
            width=18
        )
        self.indicator.pack(side="left", padx=(0, 4))
        
        self.label = ctk.CTkLabel(
            self,
            text=status.value[0],
            text_color=status.value[1],
            font=ctk.CTkFont(size=13),
        )
        self.label.pack(side="left")
    
    def set_status(self, status: AccountStatus):
        self.status = status
        self.indicator.configure(text=status.value[2], text_color=status.value[1])
        self.label.configure(text=status.value[0], text_color=status.value[1])


class AccountCard(ctk.CTkFrame):
    """账号卡片组件"""
    
    def __init__(self, master, account: TelegramAccount, 
                 on_select=None, on_delete=None, **kwargs):
        super().__init__(master, **kwargs)
        self.configure(
            fg_color=ThemeColors.BG_CARD,
            corner_radius=10,
            border_width=1,
            border_color=ThemeColors.BORDER,
            height=78
        )
        self.pack_propagate(False)
        
        self.account = account
        self.on_select = on_select
        self.on_delete = on_delete
        self.selected = False
        self.status = AccountStatus.UNKNOWN
        
        self._create_widgets()
        
        # 绑定点击事件
        self.bind("<Button-1>", self._on_click)
        for child in self.winfo_children():
            child.bind("<Button-1>", self._on_click)
    
    def _create_widgets(self):
        # 左侧选择指示器
        self.select_indicator = ctk.CTkFrame(
            self, width=4, height=54,
            fg_color="transparent",
            corner_radius=2
        )
        self.select_indicator.pack(side="left", padx=(8, 0), pady=10)
        
        # 头像占位（圆形）
        avatar_frame = ctk.CTkFrame(
            self, width=46, height=46,
            fg_color=ThemeColors.ACCENT_BLUE,
            corner_radius=23
        )
        avatar_frame.pack(side="left", padx=(12, 0))
        avatar_frame.pack_propagate(False)
        
        # 头像文字（取名字首字母）
        initial = (self.account.name[0] if self.account.name else 
                   self.account.phone[-2:])
        ctk.CTkLabel(
            avatar_frame,
            text=initial.upper(),
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color=ThemeColors.TEXT_PRIMARY
        ).place(relx=0.5, rely=0.5, anchor="center")
        
        # 信息区域
        info_frame = ctk.CTkFrame(self, fg_color="transparent")
        info_frame.pack(side="left", fill="both", expand=True, padx=12, pady=8)
        
        # 名称行
        name_frame = ctk.CTkFrame(info_frame, fg_color="transparent")
        name_frame.pack(fill="x")
        
        name = self.account.name or "未命名"
        self.name_label = ctk.CTkLabel(
            name_frame,
            text=name,
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color=ThemeColors.TEXT_PRIMARY,
            anchor="w"
        )
        self.name_label.pack(side="left")
        
        # 状态徽章
        self.status_badge = StatusBadge(name_frame, self.status)
        self.status_badge.pack(side="left", padx=(10, 0))
        
        # 用户名和电话
        username = f"@{self.account.username}" if self.account.username else ""
        phone = self.account.phone
        
        detail_text = f"{username}  {phone}" if username else phone
        self.detail_label = ctk.CTkLabel(
            info_frame,
            text=detail_text,
            font=ctk.CTkFont(size=14),
            text_color=ThemeColors.TEXT_SECONDARY,
            anchor="w"
        )
        self.detail_label.pack(fill="x", pady=(2, 0))
        
        # 右侧按钮区
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(side="right", padx=10)
        
        # 删除按钮
        self.del_btn = ctk.CTkButton(
            btn_frame,
            text="✕",
            width=34,
            height=34,
            corner_radius=17,
            fg_color="transparent",
            hover_color=ThemeColors.ACCENT_RED,
            text_color=ThemeColors.TEXT_MUTED,
            font=ctk.CTkFont(size=16),
            command=self._on_delete
        )
        self.del_btn.pack()
    
    def _on_click(self, event=None):
        self.toggle_select()
        if self.on_select:
            self.on_select(self.account.phone, self.selected)
    
    def toggle_select(self):
        self.selected = not self.selected
        self._update_visual()
    
    def set_selected(self, selected: bool):
        self.selected = selected
        self._update_visual()
    
    def _update_visual(self):
        if self.selected:
            self.configure(border_color=ThemeColors.ACCENT_BLUE)
            self.select_indicator.configure(fg_color=ThemeColors.ACCENT_BLUE)
        else:
            self.configure(border_color=ThemeColors.BORDER)
            self.select_indicator.configure(fg_color="transparent")
    
    def _on_delete(self):
        if self.on_delete:
            self.on_delete(self.account.phone)
    
    def set_status(self, status: AccountStatus):
        self.status = status
        self.status_badge.set_status(status)


class ModernLogBox(ctk.CTkFrame):
    """现代化日志显示框"""
    
    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        self.configure(
            fg_color=ThemeColors.BG_DARK,
            corner_radius=10,
            border_width=1,
            border_color=ThemeColors.BORDER
        )
        
        # 头部
        header = ctk.CTkFrame(self, fg_color=ThemeColors.BG_SECONDARY, height=42, corner_radius=0)
        header.pack(fill="x")
        header.pack_propagate(False)
        
        ctk.CTkLabel(
            header,
            text="  操作日志",
            font=ctk.CTkFont(size=15, weight="bold"),
            text_color=ThemeColors.TEXT_PRIMARY
        ).pack(side="left", padx=10, pady=8)
        
        ctk.CTkButton(
            header,
            text="清空",
            width=65,
            height=30,
            corner_radius=6,
            fg_color=ThemeColors.BG_HOVER,
            hover_color=ThemeColors.BORDER_LIGHT,
            text_color=ThemeColors.TEXT_SECONDARY,
            font=ctk.CTkFont(size=13),
            command=self.clear
        ).pack(side="right", padx=10, pady=6)
        
        # 日志区域
        self.text = ctk.CTkTextbox(
            self,
            fg_color="transparent",
            text_color=ThemeColors.TEXT_SECONDARY,
            font=ctk.CTkFont(family="Consolas", size=13),
            wrap="word",
            state="disabled"
        )
        self.text.pack(fill="both", expand=True, padx=2, pady=2)
    
    def log(self, message: str, level: str = "info"):
        self.text.configure(state="normal")
        
        timestamp = datetime.now().strftime("%H:%M:%S")
        
        # 根据级别选择颜色和图标
        icons = {
            "info": ("ℹ", ThemeColors.ACCENT_BLUE),
            "success": ("✓", ThemeColors.ACCENT_GREEN),
            "warning": ("⚠", ThemeColors.ACCENT_YELLOW),
            "error": ("✗", ThemeColors.ACCENT_RED)
        }
        icon, color = icons.get(level, icons["info"])
        
        # 插入带颜色的文本
        self.text.insert("end", f"[{timestamp}] {icon} {message}\n")
        self.text.see("end")
        self.text.configure(state="disabled")
    
    def clear(self):
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.configure(state="disabled")


class StatsCard(ctk.CTkFrame):
    """统计卡片"""
    
    def __init__(self, master, title: str, value: str, 
                 icon: str, color: str, **kwargs):
        super().__init__(master, **kwargs)
        self.configure(
            fg_color=ThemeColors.BG_CARD,
            corner_radius=12,
            border_width=1,
            border_color=ThemeColors.BORDER,
            height=100
        )
        self.pack_propagate(False)
        
        # 图标
        icon_label = ctk.CTkLabel(
            self,
            text=icon,
            font=ctk.CTkFont(size=32),
            text_color=color
        )
        icon_label.pack(pady=(15, 5))
        
        # 数值
        self.value_label = ctk.CTkLabel(
            self,
            text=value,
            font=ctk.CTkFont(size=28, weight="bold"),
            text_color=ThemeColors.TEXT_PRIMARY
        )
        self.value_label.pack()
        
        # 标题
        ctk.CTkLabel(
            self,
            text=title,
            font=ctk.CTkFont(size=13),
            text_color=ThemeColors.TEXT_SECONDARY
        ).pack()
    
    def set_value(self, value: str):
        self.value_label.configure(text=value)


# ==================== 主应用 ====================

class TelegramSenderPro(ctk.CTk):
    """Telegram群发小帮手"""
    
    def __init__(self):
        super().__init__()
        
        # 窗口配置
        self.title(f"{APP_NAME} v{VERSION}")
        self.geometry("1400x900")
        self.minsize(1200, 800)
        self.configure(fg_color=ThemeColors.BG_DARK)
        
        # 初始化
        self.async_helper = AsyncHelper()
        self.manager = AccountManager()
        self.sender = MultiSender(self.manager)
        self.task_queue = queue.Queue()
        self.sending = False
        
        # 语音文件
        self.voice_file_path: Optional[str] = None
        
        # 账号卡片映射
        self.account_cards: Dict[str, AccountCard] = {}
        self.selected_accounts: set = set()
        
        # 创建界面
        self._create_header()
        self._create_main_layout()
        self._load_accounts()
        
        # 设置文件拖拽（需要 windnd: pip install windnd）
        if WINDND_AVAILABLE:
            windnd.hook_dropfiles(self, func=self._on_voice_drop)
        
        # 定时检查任务队列
        self._check_queue()
        
        # 关闭事件
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        
        # 启动后检查更新
        if UPDATER_AVAILABLE:
            self.after(1000, lambda: check_for_updates_on_startup(self))
    
    def _create_header(self):
        """创建顶部导航栏"""
        header = ctk.CTkFrame(
            self,
            fg_color=ThemeColors.BG_SECONDARY,
            height=66,
            corner_radius=0
        )
        header.pack(fill="x")
        header.pack_propagate(False)
        
        # Logo 和标题
        logo_frame = ctk.CTkFrame(header, fg_color="transparent")
        logo_frame.pack(side="left", padx=20)
        
        ctk.CTkLabel(
            logo_frame,
            text="📨",
            font=ctk.CTkFont(size=32)
        ).pack(side="left")
        
        title_frame = ctk.CTkFrame(logo_frame, fg_color="transparent")
        title_frame.pack(side="left", padx=10)
        
        ctk.CTkLabel(
            title_frame,
            text=APP_NAME,
            font=ctk.CTkFont(size=24, weight="bold"),
            text_color=ThemeColors.TEXT_PRIMARY
        ).pack(anchor="w")
        
        ctk.CTkLabel(
            title_frame,
            text="Multi-Account Messaging System",
            font=ctk.CTkFont(size=13),
            text_color=ThemeColors.TEXT_MUTED
        ).pack(anchor="w")
        
        # 右侧状态
        status_frame = ctk.CTkFrame(header, fg_color="transparent")
        status_frame.pack(side="right", padx=20)
        
        self.connection_status = ctk.CTkLabel(
            status_frame,
            text="● 系统就绪",
            font=ctk.CTkFont(size=14),
            text_color=ThemeColors.STATUS_ONLINE
        )
        self.connection_status.pack(side="right")
    
    def _create_main_layout(self):
        """创建主布局"""
        main = ctk.CTkFrame(self, fg_color="transparent")
        main.pack(fill="both", expand=True, padx=20, pady=20)
        
        # 左侧面板 - 账号管理
        left_panel = ctk.CTkFrame(
            main,
            fg_color=ThemeColors.BG_SECONDARY,
            corner_radius=16,
            width=450
        )
        left_panel.pack(side="left", fill="y", padx=(0, 15))
        left_panel.pack_propagate(False)
        
        self._create_account_panel(left_panel)
        
        # 右侧面板
        right_panel = ctk.CTkFrame(main, fg_color="transparent")
        right_panel.pack(side="right", fill="both", expand=True)
        
        # 统计卡片行
        stats_frame = ctk.CTkFrame(right_panel, fg_color="transparent", height=120)
        stats_frame.pack(fill="x", pady=(0, 15))
        stats_frame.pack_propagate(False)
        
        self._create_stats_cards(stats_frame)
        
        # 发送面板
        send_panel = ctk.CTkFrame(
            right_panel,
            fg_color=ThemeColors.BG_SECONDARY,
            corner_radius=16
        )
        send_panel.pack(fill="both", expand=True)
        
        self._create_send_panel(send_panel)
    
    def _create_account_panel(self, parent):
        """创建账号管理面板"""
        # 标题栏
        title_frame = ctk.CTkFrame(parent, fg_color="transparent", height=65)
        title_frame.pack(fill="x", padx=20, pady=(15, 10))
        title_frame.pack_propagate(False)
        
        ctk.CTkLabel(
            title_frame,
            text="账号管理",
            font=ctk.CTkFont(size=22, weight="bold"),
            text_color=ThemeColors.TEXT_PRIMARY
        ).pack(side="left", pady=10)
        
        self.account_count_label = ctk.CTkLabel(
            title_frame,
            text="0 个账号",
            font=ctk.CTkFont(size=14),
            text_color=ThemeColors.TEXT_MUTED
        )
        self.account_count_label.pack(side="right", pady=10)
        
        # 操作按钮
        btn_frame = ctk.CTkFrame(parent, fg_color="transparent")
        btn_frame.pack(fill="x", padx=20, pady=(0, 10))
        
        ctk.CTkButton(
            btn_frame,
            text="📁 导入 tdata",
            font=ctk.CTkFont(size=15),
            fg_color=ThemeColors.ACCENT_GREEN,
            hover_color="#2ea043",
            corner_radius=8,
            height=42,
            command=self._import_tdata
        ).pack(side="left", expand=True, fill="x", padx=(0, 5))
        
        ctk.CTkButton(
            btn_frame,
            text="🔄 检测状态",
            font=ctk.CTkFont(size=15),
            fg_color=ThemeColors.ACCENT_BLUE,
            hover_color="#1f6feb",
            corner_radius=8,
            height=42,
            command=self._check_all_status
        ).pack(side="left", expand=True, fill="x", padx=(5, 0))
        
        # 全选操作
        select_frame = ctk.CTkFrame(parent, fg_color="transparent")
        select_frame.pack(fill="x", padx=20, pady=(0, 10))
        
        ctk.CTkButton(
            select_frame,
            text="全选",
            width=75,
            height=32,
            corner_radius=6,
            fg_color=ThemeColors.BG_HOVER,
            hover_color=ThemeColors.BORDER_LIGHT,
            text_color=ThemeColors.TEXT_PRIMARY,
            font=ctk.CTkFont(size=13),
            command=self._select_all
        ).pack(side="left", padx=(0, 5))
        
        ctk.CTkButton(
            select_frame,
            text="取消全选",
            width=75,
            height=32,
            corner_radius=6,
            fg_color=ThemeColors.BG_HOVER,
            hover_color=ThemeColors.BORDER_LIGHT,
            text_color=ThemeColors.TEXT_PRIMARY,
            font=ctk.CTkFont(size=13),
            command=self._deselect_all
        ).pack(side="left")
        
        self.selected_label = ctk.CTkLabel(
            select_frame,
            text="已选: 0",
            font=ctk.CTkFont(size=14),
            text_color=ThemeColors.ACCENT_BLUE
        )
        self.selected_label.pack(side="right")
        
        # 账号列表
        self.account_scroll = ctk.CTkScrollableFrame(
            parent,
            fg_color="transparent",
            scrollbar_button_color=ThemeColors.BORDER,
            scrollbar_button_hover_color=ThemeColors.BORDER_LIGHT
        )
        self.account_scroll.pack(fill="both", expand=True, padx=15, pady=(0, 15))
    
    def _create_stats_cards(self, parent):
        """创建统计卡片"""
        # 总账号
        self.stats_total = StatsCard(
            parent, "总账号", "0", "👥", ThemeColors.ACCENT_BLUE
        )
        self.stats_total.pack(side="left", expand=True, fill="both", padx=(0, 10))
        
        # 正常
        self.stats_online = StatsCard(
            parent, "正常", "0", "✓", ThemeColors.ACCENT_GREEN
        )
        self.stats_online.pack(side="left", expand=True, fill="both", padx=(0, 10))
        
        # 受限
        self.stats_restricted = StatsCard(
            parent, "受限", "0", "⚠", ThemeColors.ACCENT_YELLOW
        )
        self.stats_restricted.pack(side="left", expand=True, fill="both", padx=(0, 10))
        
        # 已发送
        self.stats_sent = StatsCard(
            parent, "已发送", "0", "📤", ThemeColors.ACCENT_PURPLE
        )
        self.stats_sent.pack(side="left", expand=True, fill="both")
    
    def _create_send_panel(self, parent):
        """创建发送面板"""
        # 内容区
        content = ctk.CTkFrame(parent, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=20, pady=20)
        
        # 上半部分 - 输入区
        input_frame = ctk.CTkFrame(content, fg_color="transparent")
        input_frame.pack(fill="x")
        
        # 左侧 - 目标用户
        target_frame = GradientFrame(input_frame)
        target_frame.pack(side="left", fill="both", expand=True, padx=(0, 10))
        
        ctk.CTkLabel(
            target_frame,
            text="📋 目标用户",
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color=ThemeColors.TEXT_PRIMARY
        ).pack(anchor="w", padx=15, pady=(15, 5))
        
        ctk.CTkLabel(
            target_frame,
            text="每行一个用户名，不需要 @ 符号",
            font=ctk.CTkFont(size=12),
            text_color=ThemeColors.TEXT_MUTED
        ).pack(anchor="w", padx=15, pady=(0, 10))
        
        self.target_text = ctk.CTkTextbox(
            target_frame,
            fg_color=ThemeColors.BG_DARK,
            text_color=ThemeColors.TEXT_PRIMARY,
            font=ctk.CTkFont(family="Consolas", size=14),
            corner_radius=8,
            border_width=1,
            border_color=ThemeColors.BORDER,
            height=180
        )
        self.target_text.pack(fill="both", expand=True, padx=15, pady=(0, 15))
        
        # 右侧 - 消息内容
        msg_frame = GradientFrame(input_frame)
        msg_frame.pack(side="right", fill="both", expand=True)
        
        ctk.CTkLabel(
            msg_frame,
            text="💬 消息内容",
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color=ThemeColors.TEXT_PRIMARY
        ).pack(anchor="w", padx=15, pady=(15, 5))
        
        ctk.CTkLabel(
            msg_frame,
            text="支持文本 (Markdown) | 拖入 .ogg 文件发送语音条",
            font=ctk.CTkFont(size=12),
            text_color=ThemeColors.TEXT_MUTED
        ).pack(anchor="w", padx=15, pady=(0, 10))
        
        self.message_text = ctk.CTkTextbox(
            msg_frame,
            fg_color=ThemeColors.BG_DARK,
            text_color=ThemeColors.TEXT_PRIMARY,
            font=ctk.CTkFont(size=14),
            corner_radius=8,
            border_width=1,
            border_color=ThemeColors.BORDER,
            height=150
        )
        self.message_text.pack(fill="both", expand=True, padx=15, pady=(0, 8))
        
        # 语音文件指示栏（拖入 .ogg 后显示）
        self.voice_bar = ctk.CTkFrame(msg_frame, fg_color=ThemeColors.BG_DARK, height=36, corner_radius=8)
        # voice_bar 默认不显示，拖入语音后才 pack
        
        self.voice_indicator = ctk.CTkLabel(
            self.voice_bar,
            text="",
            font=ctk.CTkFont(size=13),
            text_color=ThemeColors.ACCENT_PURPLE
        )
        self.voice_indicator.pack(side="left", padx=(12, 0))
        
        self.voice_clear_btn = ctk.CTkButton(
            self.voice_bar,
            text="✕ 移除",
            width=65,
            height=28,
            corner_radius=6,
            fg_color="transparent",
            hover_color=ThemeColors.ACCENT_RED,
            text_color=ThemeColors.TEXT_MUTED,
            font=ctk.CTkFont(size=12),
            command=self._clear_voice
        )
        self.voice_clear_btn.pack(side="right", padx=(0, 8))
        
        # 控制栏
        control_frame = ctk.CTkFrame(content, fg_color="transparent", height=60)
        control_frame.pack(fill="x", pady=(15, 0))
        control_frame.pack_propagate(False)
        
        # 左侧设置
        settings_frame = ctk.CTkFrame(control_frame, fg_color="transparent")
        settings_frame.pack(side="left")
        
        ctk.CTkLabel(
            settings_frame,
            text="发送间隔",
            font=ctk.CTkFont(size=14),
            text_color=ThemeColors.TEXT_SECONDARY
        ).pack(side="left")
        
        self.delay_entry = ctk.CTkEntry(
            settings_frame,
            width=65,
            height=38,
            corner_radius=8,
            fg_color=ThemeColors.BG_CARD,
            border_color=ThemeColors.BORDER,
            text_color=ThemeColors.TEXT_PRIMARY,
            font=ctk.CTkFont(size=14),
            justify="center"
        )
        self.delay_entry.pack(side="left", padx=(10, 5))
        self.delay_entry.insert(0, "5")
        
        ctk.CTkLabel(
            settings_frame,
            text="秒",
            font=ctk.CTkFont(size=14),
            text_color=ThemeColors.TEXT_SECONDARY
        ).pack(side="left")
        
        # 右侧按钮
        btn_frame = ctk.CTkFrame(control_frame, fg_color="transparent")
        btn_frame.pack(side="right")
        
        self.verify_btn = ctk.CTkButton(
            btn_frame,
            text="🔍 验证",
            width=105,
            height=46,
            corner_radius=10,
            fg_color=ThemeColors.BG_HOVER,
            hover_color=ThemeColors.BORDER_LIGHT,
            text_color=ThemeColors.TEXT_PRIMARY,
            font=ctk.CTkFont(size=15),
            command=self._verify_send
        )
        self.verify_btn.pack(side="left", padx=(0, 10))
        
        self.stop_btn = ctk.CTkButton(
            btn_frame,
            text="⏹ 停止",
            width=105,
            height=46,
            corner_radius=10,
            fg_color=ThemeColors.ACCENT_RED,
            hover_color="#da3633",
            text_color=ThemeColors.TEXT_PRIMARY,
            font=ctk.CTkFont(size=15),
            command=self._stop_send,
            state="disabled"
        )
        self.stop_btn.pack(side="left", padx=(0, 10))
        
        self.send_btn = ctk.CTkButton(
            btn_frame,
            text="🚀 开始发送",
            width=150,
            height=46,
            corner_radius=10,
            fg_color=ThemeColors.ACCENT_GREEN,
            hover_color="#2ea043",
            text_color=ThemeColors.TEXT_PRIMARY,
            font=ctk.CTkFont(size=16, weight="bold"),
            command=self._start_send
        )
        self.send_btn.pack(side="left")
        
        # 进度条
        self.progress = ctk.CTkProgressBar(
            content,
            height=6,
            corner_radius=3,
            fg_color=ThemeColors.BG_CARD,
            progress_color=ThemeColors.ACCENT_GREEN
        )
        self.progress.pack(fill="x", pady=(15, 5))
        self.progress.set(0)
        
        self.progress_label = ctk.CTkLabel(
            content,
            text="就绪",
            font=ctk.CTkFont(size=14),
            text_color=ThemeColors.TEXT_MUTED
        )
        self.progress_label.pack()
        
        # 日志区域
        self.log_box = ModernLogBox(content)
        self.log_box.pack(fill="both", expand=True, pady=(15, 0))
    
    # ==================== 语音文件处理 ====================
    
    def _on_voice_drop(self, files):
        """处理拖拽文件"""
        for f in files:
            try:
                file_path = f.decode('gbk') if isinstance(f, bytes) else str(f)
            except (UnicodeDecodeError, AttributeError):
                try:
                    file_path = f.decode('utf-8') if isinstance(f, bytes) else str(f)
                except Exception:
                    continue
            
            if file_path.lower().endswith('.ogg'):
                self._set_voice_file(file_path)
                return
        
        self.log_box.log("仅支持 .ogg 格式的语音文件", "warning")
    
    def _set_voice_file(self, file_path: str):
        """设置语音文件"""
        if not os.path.exists(file_path):
            self.log_box.log(f"文件不存在: {file_path}", "error")
            return
        
        if not file_path.lower().endswith('.ogg'):
            self.log_box.log("仅支持 .ogg 格式的语音文件", "warning")
            return
        
        self.voice_file_path = file_path
        filename = os.path.basename(file_path)
        self.voice_indicator.configure(text=f"🎤 {filename}")
        self.voice_bar.pack(fill="x", padx=15, pady=(0, 12))
        self.log_box.log(f"已选择语音文件: {filename}", "info")
    
    def _clear_voice(self):
        """清除语音文件"""
        self.voice_file_path = None
        self.voice_indicator.configure(text="")
        self.voice_bar.pack_forget()
        self.log_box.log("已移除语音文件", "info")
    
    # ==================== 功能方法 ====================
    
    def _load_accounts(self):
        """加载账号列表"""
        # 清空现有卡片
        for card in self.account_cards.values():
            card.destroy()
        self.account_cards.clear()
        self.selected_accounts.clear()
        
        # 重新加载
        self.manager._load_accounts()
        
        for phone, account in self.manager.accounts.items():
            self._add_account_card(account)
        
        self._update_stats()
        self.log_box.log(f"已加载 {len(self.manager.accounts)} 个账号", "info")
    
    def _add_account_card(self, account: TelegramAccount):
        """添加账号卡片"""
        card = AccountCard(
            self.account_scroll,
            account,
            on_select=self._on_account_select,
            on_delete=self._on_account_delete
        )
        card.pack(fill="x", pady=(0, 8))
        self.account_cards[account.phone] = card
    
    def _on_account_select(self, phone: str, selected: bool):
        """账号选择回调"""
        if selected:
            self.selected_accounts.add(phone)
        else:
            self.selected_accounts.discard(phone)
        self.selected_label.configure(text=f"已选: {len(self.selected_accounts)}")
    
    def _on_account_delete(self, phone: str):
        """删除账号"""
        if messagebox.askyesno("确认删除", f"确定要删除账号 {phone} 吗？"):
            self.manager.remove_account(phone)
            if phone in self.account_cards:
                self.account_cards[phone].destroy()
                del self.account_cards[phone]
            self.selected_accounts.discard(phone)
            self._update_stats()
            self.log_box.log(f"已删除账号: {phone}", "warning")
    
    def _select_all(self):
        """全选"""
        for phone, card in self.account_cards.items():
            card.set_selected(True)
            self.selected_accounts.add(phone)
        self.selected_label.configure(text=f"已选: {len(self.selected_accounts)}")
    
    def _deselect_all(self):
        """取消全选"""
        for card in self.account_cards.values():
            card.set_selected(False)
        self.selected_accounts.clear()
        self.selected_label.configure(text="已选: 0")
    
    def _update_stats(self):
        """更新统计数据"""
        total = len(self.manager.accounts)
        self.stats_total.set_value(str(total))
        self.account_count_label.configure(text=f"{total} 个账号")
    
    def _import_tdata(self):
        """导入 tdata"""
        if not OPENTELE_AVAILABLE:
            messagebox.showerror("错误", f"opentele 不可用:\n{OPENTELE_ERROR}")
            return
        
        tdata_path = filedialog.askdirectory(title="选择 tdata 文件夹")
        if not tdata_path:
            return
        
        self.log_box.log(f"开始导入: {tdata_path}", "info")
        self.connection_status.configure(text="● 正在导入...", text_color=ThemeColors.STATUS_CHECKING)
        
        async def do_import():
            return await self.manager.import_from_tdata(tdata_path)
        
        def on_complete(results):
            self.task_queue.put(("import_complete", results))
        
        self.async_helper.run(do_import(), on_complete)
    
    def _check_all_status(self):
        """检测所有账号状态"""
        if not self.account_cards:
            messagebox.showinfo("提示", "没有账号可检测")
            return
        
        self.log_box.log("开始检测账号状态...", "info")
        
        # 先设置所有账号为检测中
        for card in self.account_cards.values():
            card.set_status(AccountStatus.CHECKING)
        
        async def do_check():
            results = []
            for phone in list(self.manager.accounts.keys()):
                try:
                    client = await self.manager.get_client(phone)
                    if client:
                        # 尝试获取用户信息来检测状态
                        me = await client.get_me()
                        if me:
                            # 尝试发送一个测试请求来检测限制
                            try:
                                # 获取对话列表来测试账号功能
                                dialogs = await client.get_dialogs(limit=1)
                                results.append((phone, AccountStatus.ONLINE))
                            except Exception as e:
                                err_msg = str(e).lower()
                                if "flood" in err_msg:
                                    results.append((phone, AccountStatus.RESTRICTED))
                                elif "banned" in err_msg or "deactivated" in err_msg:
                                    results.append((phone, AccountStatus.FROZEN))
                                else:
                                    results.append((phone, AccountStatus.RESTRICTED))
                        else:
                            results.append((phone, AccountStatus.OFFLINE))
                    else:
                        results.append((phone, AccountStatus.OFFLINE))
                except Exception as e:
                    err_msg = str(e).lower()
                    if "banned" in err_msg or "deactivated" in err_msg:
                        results.append((phone, AccountStatus.FROZEN))
                    elif "auth" in err_msg:
                        results.append((phone, AccountStatus.OFFLINE))
                    else:
                        results.append((phone, AccountStatus.RESTRICTED))
                
                # 每检测完一个就通知
                self.task_queue.put(("status_update", results[-1]))
            
            return results
        
        def on_complete(results):
            self.task_queue.put(("status_complete", results))
        
        self.async_helper.run(do_check(), on_complete)
    
    def _start_send(self):
        """开始发送"""
        selected = list(self.selected_accounts)
        if not selected:
            messagebox.showwarning("提示", "请先选择要使用的账号")
            return
        
        targets_text = self.target_text.get("1.0", "end").strip()
        if not targets_text:
            messagebox.showwarning("提示", "请输入发送目标")
            return
        
        targets = []
        for line in targets_text.split("\n"):
            t = line.strip()
            if t:
                if t.startswith("@"):
                    t = t[1:]
                targets.append(t)
        
        if not targets:
            messagebox.showwarning("提示", "请输入有效的发送目标")
            return
        
        message = self.message_text.get("1.0", "end").strip()
        voice_path = self.voice_file_path
        
        # 文本和语音至少需要一个
        if not message and not voice_path:
            messagebox.showwarning("提示", "请输入消息内容或选择语音文件")
            return
        
        if voice_path and not os.path.exists(voice_path):
            messagebox.showwarning("提示", f"语音文件不存在: {voice_path}")
            return
        
        try:
            delay = float(self.delay_entry.get() or "5")
        except ValueError:
            delay = 5.0
        
        # 更新UI
        self.send_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.sending = True
        
        total = len(targets)
        self.progress.set(0)
        self.progress_label.configure(text=f"准备发送 0/{total}")
        self.connection_status.configure(text="● 发送中...", text_color=ThemeColors.STATUS_CHECKING)
        
        send_type = "语音" if voice_path else "文本"
        self.log_box.log(f"分配模式: {len(selected)} 个账号 → {total} 个目标 [{send_type}]", "info")
        
        async def do_send():
            count = 0
            results = []
            
            for i, target in enumerate(targets):
                if not self.sending:
                    break
                
                phone = selected[i % len(selected)]
                
                if voice_path:
                    success, msg = await self._send_voice_msg(phone, target, voice_path)
                else:
                    success, msg = await self.sender.send_from_account(phone, target, message)
                
                count += 1
                
                acc = self.manager.accounts.get(phone)
                acc_name = acc.name if acc and acc.name else phone
                log_msg = f"[{acc_name}] → @{target}: {'成功' if success else '失败'}"
                if not success and msg:
                    log_msg += f" ({msg})"
                
                results.append((phone, target, success, log_msg))
                self.task_queue.put(("send_progress", (count, total, success, log_msg)))
                
                if count < total:
                    await asyncio.sleep(delay)
            
            return results
        
        def on_complete(results):
            self.task_queue.put(("send_complete", results))
        
        self.async_helper.run(do_send(), on_complete)
    
    async def _send_voice_msg(self, phone: str, target: str, voice_path: str) -> Tuple[bool, str]:
        """发送语音消息"""
        try:
            client = await self.manager.get_client(phone)
            if not client:
                return False, "无法获取客户端"
            
            entity = await client.get_entity(target)
            await client.send_file(
                entity,
                voice_path,
                voice_note=True
            )
            return True, ""
        except Exception as e:
            return False, str(e)[:60]
    
    def _stop_send(self):
        """停止发送"""
        self.sending = False
        self.log_box.log("正在停止...", "warning")
    
    def _verify_send(self):
        """验证发送结果"""
        selected = list(self.selected_accounts)
        if not selected:
            messagebox.showwarning("提示", "请先选择账号")
            return
        
        targets_text = self.target_text.get("1.0", "end").strip()
        if not targets_text:
            messagebox.showwarning("提示", "请输入要验证的目标")
            return
        
        targets = [t.strip().lstrip("@") for t in targets_text.split("\n") if t.strip()]
        if not targets:
            return
        
        self.log_box.log("开始验证发送结果...", "info")
        self.verify_btn.configure(state="disabled")
        
        async def do_verify():
            results = []
            phone = selected[0]
            client = await self.manager.get_client(phone)
            
            if not client:
                return [("error", f"无法连接账号 {phone}")]
            
            for target in targets[:10]:
                try:
                    entity = await client.get_entity(target)
                    messages = await client.get_messages(entity, limit=5)
                    
                    if messages:
                        me = await client.get_me()
                        sent = any(m.sender_id == me.id for m in messages if m.sender_id)
                        
                        if sent:
                            msg = next((m for m in messages if m.sender_id == me.id), None)
                            if msg and msg.voice:
                                preview = "[语音消息]"
                            elif msg and msg.text:
                                preview = (msg.text[:40] + "...") if len(msg.text) > 40 else msg.text
                            else:
                                preview = "[媒体消息]"
                            results.append(("success", f"@{target}: ✓ \"{preview}\""))
                        else:
                            results.append(("warning", f"@{target}: 最近消息中未找到"))
                    else:
                        results.append(("warning", f"@{target}: 无对话记录"))
                except Exception as e:
                    results.append(("error", f"@{target}: {str(e)[:30]}"))
            
            return results
        
        def on_complete(results):
            self.task_queue.put(("verify_complete", results))
        
        self.async_helper.run(do_verify(), on_complete)
    
    # ==================== 事件处理 ====================
    
    def _check_queue(self):
        """检查任务队列"""
        try:
            while True:
                msg_type, data = self.task_queue.get_nowait()
                
                if msg_type == "import_complete":
                    self._on_import_complete(data)
                elif msg_type == "status_update":
                    self._on_status_update(data)
                elif msg_type == "status_complete":
                    self._on_status_complete(data)
                elif msg_type == "send_progress":
                    self._on_send_progress(data)
                elif msg_type == "send_complete":
                    self._on_send_complete(data)
                elif msg_type == "verify_complete":
                    self._on_verify_complete(data)
        except queue.Empty:
            pass
        
        self.after(100, self._check_queue)
    
    def _on_import_complete(self, results):
        success = sum(1 for s, _ in results if s)
        fail = len(results) - success
        
        for s, msg in results:
            self.log_box.log(msg, "success" if s else "error")
        
        self.log_box.log(f"导入完成: 成功 {success}, 失败 {fail}", "info")
        self._load_accounts()
        self.connection_status.configure(text="● 系统就绪", text_color=ThemeColors.STATUS_ONLINE)
    
    def _on_status_update(self, data):
        phone, status = data
        if phone in self.account_cards:
            self.account_cards[phone].set_status(status)
    
    def _on_status_complete(self, results):
        online = sum(1 for _, s in results if s == AccountStatus.ONLINE)
        restricted = sum(1 for _, s in results if s == AccountStatus.RESTRICTED)
        
        self.stats_online.set_value(str(online))
        self.stats_restricted.set_value(str(restricted))
        self.log_box.log(f"状态检测完成: 正常 {online}, 受限 {restricted}", "info")
    
    def _on_send_progress(self, data):
        count, total, success, msg = data
        self.progress.set(count / total)
        self.progress_label.configure(text=f"发送中 {count}/{total}")
        self.log_box.log(msg, "success" if success else "error")
        
        # 更新已发送统计
        self.stats_sent.set_value(str(count))
    
    def _on_send_complete(self, results):
        success = sum(1 for _, _, s, _ in results if s)
        fail = len(results) - success
        
        self.log_box.log(f"发送完成: 成功 {success}, 失败 {fail}", "info")
        self.send_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")
        self.progress.set(1)
        self.progress_label.configure(text=f"完成 {success}/{len(results)}")
        self.connection_status.configure(text="● 系统就绪", text_color=ThemeColors.STATUS_ONLINE)
    
    def _on_verify_complete(self, results):
        self.verify_btn.configure(state="normal")
        self.log_box.log("=== 验证结果 ===", "info")
        
        for level, msg in results:
            self.log_box.log(msg, level)
        
        success = sum(1 for l, _ in results if l == "success")
        self.log_box.log(f"验证完成: {success}/{len(results)} 已确认", "info")
    
    def _on_close(self):
        """关闭窗口"""
        self.sending = False
        
        if self.async_helper.loop:
            async def cleanup():
                await self.manager.close_all()
            
            asyncio.run_coroutine_threadsafe(cleanup(), self.async_helper.loop)
            self.async_helper.loop.call_soon_threadsafe(self.async_helper.loop.stop)
        
        self.destroy()


def main():
    app = TelegramSenderPro()
    app.mainloop()


if __name__ == "__main__":
    main()
