4#!/usr/bin/env python3
"""Telegram 多账号批量发消息工具

功能:
  1. 支持多个 Telegram 账号同时管理
  2. 通过 URL 自动获取验证码登录
  3. 支持 tdata 会话导入（从 Telegram Desktop 导入已登录账号）
  4. 批量发送消息给多个联系人/群组
  5. 支持定时发送、间隔发送

用法:
    python telegram_multi_sender.py

账号配置格式:
    手机号|验证码URL
    例: +15795807280|https://miha.uk/tgapi/xxx/GetHTML
"""
import asyncio
import os
import sys
import re
import json
import time
import shutil
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field, asdict
from datetime import datetime

try:
    from telethon import TelegramClient
    from telethon.tl.types import User, Chat, Channel
    from telethon.errors import (
        SessionPasswordNeededError, 
        PhoneCodeExpiredError,
        PhoneCodeInvalidError,
        FloodWaitError,
        AuthRestartError
    )
    from telethon.sessions import StringSession
except ImportError:
    print("请先安装 telethon: pip install telethon")
    sys.exit(1)

try:
    import requests
except ImportError:
    print("请先安装 requests: pip install requests")
    sys.exit(1)

# 检查 opentele 是否可用（用于 tdata 导入）
OPENTELE_AVAILABLE = False
OPENTELE_ERROR = None
try:
    from opentele.td import TDesktop
    from opentele.tl import TelegramClient as OTelegramClient
    from opentele.api import API, UseCurrentSession, CreateNewSession
    OPENTELE_AVAILABLE = True
except ImportError as e:
    OPENTELE_ERROR = f"ImportError: {e}"
    print(f"[警告] opentele 不可用，将跳过 tdata 导入功能: {OPENTELE_ERROR}")
except Exception as e:
    OPENTELE_ERROR = f"{type(e).__name__}: {e}"
    print(f"[警告] opentele 加载失败，将跳过 tdata 导入功能: {OPENTELE_ERROR}")

# Telegram Desktop 内置 API
API_ID = 2040
API_HASH = "b18441a1ff607e10a989891a5462e627"

# 会话存储目录
SESSION_DIR = os.path.join(os.path.dirname(__file__), "telegram_sessions")
ACCOUNTS_FILE = os.path.join(os.path.dirname(__file__), "telegram_accounts.json")

os.makedirs(SESSION_DIR, exist_ok=True)


@dataclass
class TelegramAccount:
    """Telegram 账号信息"""
    phone: str
    session_file: str
    api_url: str = ""  # 验证码获取 URL
    name: str = ""
    username: str = ""
    user_id: int = 0
    logged_in: bool = False
    last_active: str = ""
    
    def to_dict(self):
        return asdict(self)


class AccountManager:
    """多账号管理器"""
    
    def __init__(self):
        self.accounts: Dict[str, TelegramAccount] = {}
        self.clients: Dict[str, TelegramClient] = {}
        self._load_accounts()
    
    def _load_accounts(self):
        """从文件加载账号列表"""
        if os.path.exists(ACCOUNTS_FILE):
            try:
                with open(ACCOUNTS_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                for phone, info in data.items():
                    self.accounts[phone] = TelegramAccount(**info)
            except Exception as e:
                print(f"加载账号失败: {e}")
    
    def _save_accounts(self):
        """保存账号列表到文件"""
        try:
            data = {phone: acc.to_dict() for phone, acc in self.accounts.items()}
            with open(ACCOUNTS_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"保存账号失败: {e}")
    
    def add_account(self, phone: str, api_url: str = "") -> TelegramAccount:
        """添加新账号"""
        phone = self._normalize_phone(phone)
        session_file = os.path.join(SESSION_DIR, f"{phone.replace('+', '')}")
        
        account = TelegramAccount(
            phone=phone,
            session_file=session_file,
            api_url=api_url
        )
        self.accounts[phone] = account
        self._save_accounts()
        return account
    
    def _normalize_phone(self, phone: str) -> str:
        """标准化手机号格式"""
        phone = phone.strip()
        if not phone.startswith('+'):
            phone = '+' + phone
        return phone
    
    def get_account(self, phone: str) -> Optional[TelegramAccount]:
        """获取账号信息"""
        phone = self._normalize_phone(phone)
        return self.accounts.get(phone)
    
    def list_accounts(self) -> List[TelegramAccount]:
        """列出所有账号"""
        return list(self.accounts.values())
    
    def remove_account(self, phone: str):
        """删除账号"""
        phone = self._normalize_phone(phone)
        if phone in self.accounts:
            acc = self.accounts.pop(phone)
            # 删除 session 文件
            if os.path.exists(acc.session_file + '.session'):
                os.remove(acc.session_file + '.session')
            self._save_accounts()
    
    async def login_account(self, phone: str, api_url: str = "", 
                           manual_code: str = None, manual_2fa: str = None) -> Tuple[bool, str]:
        """登录账号
        
        Args:
            phone: 手机号
            api_url: 验证码获取 URL（可选）
            manual_code: 手动输入的验证码（可选）
            manual_2fa: 手动输入的2FA密码（可选）
        
        Returns:
            (成功与否, 消息)
        """
        phone = self._normalize_phone(phone)
        
        # 确保账号已添加
        if phone not in self.accounts:
            self.add_account(phone, api_url)
        
        account = self.accounts[phone]
        if api_url:
            account.api_url = api_url
        
        client = TelegramClient(account.session_file, API_ID, API_HASH)
        
        try:
            await client.connect()
            
            if await client.is_user_authorized():
                # 已登录
                me = await client.get_me()
                account.name = f"{me.first_name or ''} {me.last_name or ''}".strip()
                account.username = me.username or ""
                account.user_id = me.id
                account.logged_in = True
                account.last_active = datetime.now().isoformat()
                self._save_accounts()
                self.clients[phone] = client
                return True, f"已登录: {account.name} (@{account.username})"
            
            # 需要登录
            await client.send_code_request(phone)
            print(f"验证码已发送到 {phone}")
            
            # 获取验证码
            code = None
            if manual_code:
                code = manual_code
            elif account.api_url:
                code, error = await self._fetch_code_from_url(account.api_url)
                if error:
                    return False, f"获取验证码失败: {error}"
            else:
                code = input(f"请输入 {phone} 收到的验证码: ").strip()
            
            if not code:
                return False, "未提供验证码"
            
            try:
                await client.sign_in(phone, code)
            except SessionPasswordNeededError:
                # 需要2FA
                password = None
                if manual_2fa:
                    password = manual_2fa
                elif account.api_url:
                    password, error = await self._fetch_2fa_from_url(account.api_url)
                    if error or not password:
                        password = input(f"请输入 {phone} 的2FA密码: ").strip()
                else:
                    password = input(f"请输入 {phone} 的2FA密码: ").strip()
                
                await client.sign_in(password=password)
            
            # 登录成功
            me = await client.get_me()
            account.name = f"{me.first_name or ''} {me.last_name or ''}".strip()
            account.username = me.username or ""
            account.user_id = me.id
            account.logged_in = True
            account.last_active = datetime.now().isoformat()
            self._save_accounts()
            self.clients[phone] = client
            
            return True, f"登录成功: {account.name} (@{account.username})"
            
        except FloodWaitError as e:
            return False, f"请求过于频繁，需等待 {e.seconds} 秒"
        except PhoneCodeExpiredError:
            return False, "验证码已过期"
        except PhoneCodeInvalidError:
            return False, "验证码无效"
        except Exception as e:
            return False, f"登录失败: {str(e)}"
    
    async def _fetch_code_from_url(self, url: str) -> Tuple[Optional[str], Optional[str]]:
        """从 URL 获取验证码"""
        try:
            # 等待几秒让验证码到达
            await asyncio.sleep(3)
            
            resp = requests.get(url, timeout=30)
            if resp.status_code != 200:
                return None, f"HTTP {resp.status_code}"
            
            text = resp.text
            
            # 尝试解析验证码（常见格式）
            patterns = [
                r'(?:code|验证码|Code)[:\s]*(\d{5,6})',
                r'(\d{5,6})',  # 纯数字
            ]
            
            for pattern in patterns:
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    return match.group(1), None
            
            return None, "未找到验证码"
            
        except Exception as e:
            return None, str(e)
    
    async def _fetch_2fa_from_url(self, url: str) -> Tuple[Optional[str], Optional[str]]:
        """从 URL 获取 2FA 密码"""
        try:
            resp = requests.get(url, timeout=30)
            if resp.status_code != 200:
                return None, f"HTTP {resp.status_code}"
            
            text = resp.text
            
            # 尝试解析 2FA 密码
            patterns = [
                r'(?:2fa|password|密码|Password)[:\s]*([^\s<]+)',
            ]
            
            for pattern in patterns:
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    return match.group(1), None
            
            return None, "未找到2FA密码"
            
        except Exception as e:
            return None, str(e)
    
    async def get_client(self, phone: str) -> Optional[TelegramClient]:
        """获取已登录的客户端"""
        phone = self._normalize_phone(phone)
        
        if phone in self.clients:
            client = self.clients[phone]
            if client.is_connected():
                return client
        
        account = self.accounts.get(phone)
        if not account:
            return None
        
        # 尝试重新连接
        # tdata 导入的账号使用 opentele 的 API
        if OPENTELE_AVAILABLE and "tdata_" in account.session_file:
            client = OTelegramClient(account.session_file, api=API.TelegramDesktop)
        else:
            client = TelegramClient(account.session_file, API_ID, API_HASH)
        await client.connect()
        
        if await client.is_user_authorized():
            self.clients[phone] = client
            return client
        
        return None
    
    async def close_all(self):
        """关闭所有连接"""
        for client in self.clients.values():
            try:
                await client.disconnect()
            except:
                pass
        self.clients.clear()
    
    async def import_from_tdata(self, tdata_path: str = None) -> List[Tuple[bool, str]]:
        """从 Telegram Desktop tdata 导入已登录账号
        
        Args:
            tdata_path: tdata 文件夹路径，默认使用 Telegram Desktop 的路径
            
        Returns:
            [(成功与否, 消息), ...]
        """
        if not OPENTELE_AVAILABLE:
            return [(False, f"opentele 不可用: {OPENTELE_ERROR}。请使用其他登录方式（选项1或2）")]
        
        if tdata_path is None:
            # 默认 Telegram Desktop 路径
            if sys.platform == 'win32':
                tdata_path = os.path.expandvars(r'%APPDATA%\Telegram Desktop\tdata')
            elif sys.platform == 'darwin':
                tdata_path = os.path.expanduser('~/Library/Application Support/Telegram Desktop/tdata')
            else:
                tdata_path = os.path.expanduser('~/.local/share/TelegramDesktop/tdata')
        
        if not os.path.exists(tdata_path):
            return [(False, f"tdata 路径不存在: {tdata_path}")]
        
        results = []
        
        try:
            print(f"正在加载 tdata: {tdata_path}")
            td = TDesktop(tdata_path)
            print(f"发现 {len(td.accounts)} 个账号")
            
            for i, acc in enumerate(td.accounts):
                client = None
                try:
                    print(f"\n导入账号 {i+1}/{len(td.accounts)}...")
                    
                    # 生成 session 文件名
                    session_name = f"tdata_{acc.UserId}"
                    session_file = os.path.join(SESSION_DIR, session_name)
                    
                    # 直接用每个 Account 对象转换，避免 td.ToTelethon 始终用 mainAccount
                    client = await OTelegramClient.FromTDesktop(
                        acc,
                        session=session_file,
                        flag=UseCurrentSession
                    )
                    
                    await client.connect()
                    
                    if await client.is_user_authorized():
                        me = await client.get_me()
                        phone = f"+{me.phone}" if me.phone else f"id_{me.id}"
                        
                        # 创建账号记录
                        account = TelegramAccount(
                            phone=phone,
                            session_file=session_file,
                            name=f"{me.first_name or ''} {me.last_name or ''}".strip(),
                            username=me.username or "",
                            user_id=me.id,
                            logged_in=True,
                            last_active=datetime.now().isoformat()
                        )
                        
                        self.accounts[phone] = account
                        # 断开连接，session 文件已保存，后续使用时重新连接
                        await client.disconnect()
                        
                        results.append((True, f"导入成功: {account.name} (@{account.username}) - {phone}"))
                        print(f"  用户: {account.name} (@{account.username})")
                        print(f"  手机: {phone}")
                        print(f"  ID: {me.id}")
                    else:
                        await client.disconnect()
                        results.append((False, f"账号 {acc.UserId} 未授权"))
                        
                except Exception as e:
                    if client:
                        try:
                            await client.disconnect()
                        except:
                            pass
                    results.append((False, f"导入账号 {i+1} 失败: {str(e)}"))
                
                # 延迟避免 SQLite 锁定
                await asyncio.sleep(0.3)
            
            self._save_accounts()
            
        except Exception as e:
            results.append((False, f"加载 tdata 失败: {str(e)}"))
        
        return results


class MultiSender:
    """多账号消息发送器"""
    
    def __init__(self, manager: AccountManager):
        self.manager = manager
    
    async def send_from_account(self, phone: str, target, message: str) -> Tuple[bool, str]:
        """使用指定账号发送消息"""
        client = await self.manager.get_client(phone)
        if not client:
            return False, f"账号 {phone} 未登录"
        
        try:
            await client.send_message(target, message)
            return True, f"[{phone}] 发送成功"
        except Exception as e:
            return False, f"[{phone}] 发送失败: {e}"
    
    async def send_from_all(self, target, message: str, delay: float = 1.0):
        """使用所有已登录账号发送消息"""
        results = []
        
        for phone, account in self.manager.accounts.items():
            if not account.logged_in:
                continue
            
            success, msg = await self.send_from_account(phone, target, message)
            results.append((phone, success, msg))
            print(msg)
            
            await asyncio.sleep(delay)
        
        return results
    
    async def send_to_multiple(self, phone: str, targets: List, message: str, delay: float = 1.0):
        """使用单个账号发送给多个目标"""
        client = await self.manager.get_client(phone)
        if not client:
            print(f"账号 {phone} 未登录")
            return []
        
        results = []
        for target in targets:
            try:
                await client.send_message(target, message)
                print(f"[{phone}] -> {target}: 成功")
                results.append((target, True))
            except Exception as e:
                print(f"[{phone}] -> {target}: 失败 - {e}")
                results.append((target, False))
            
            await asyncio.sleep(delay)
        
        return results
    
    async def batch_send(self, accounts_targets: Dict[str, List], message: str, delay: float = 1.0):
        """批量发送：指定每个账号的目标列表
        
        Args:
            accounts_targets: {手机号: [目标列表]}
            message: 消息内容
            delay: 每条消息间隔
        """
        for phone, targets in accounts_targets.items():
            print(f"\n=== 账号 {phone} ===")
            await self.send_to_multiple(phone, targets, message, delay)


def parse_account_config(config_line: str) -> Tuple[str, str]:
    """解析账号配置行
    
    格式: 手机号|验证码URL
    返回: (手机号, URL)
    """
    parts = config_line.strip().split('|', 1)
    phone = parts[0].strip()
    api_url = parts[1].strip() if len(parts) > 1 else ""
    return phone, api_url


async def interactive_mode():
    """交互模式"""
    manager = AccountManager()
    sender = MultiSender(manager)
    
    try:
        while True:
            print("\n" + "=" * 50)
            print(" Telegram 多账号发消息工具")
            print("=" * 50)
            print("1. 查看所有账号")
            print("2. 添加/登录账号 (手动输入验证码)")
            print("3. 批量添加账号 (从URL自动获取验证码)")
            print("4. 从 Telegram Desktop 导入账号 (tdata)")
            print("5. 单账号发消息")
            print("6. 多账号群发同一消息")
            print("7. 删除账号")
            print("8. 退出")
            print("=" * 50)
            
            choice = input("请选择: ").strip()
            
            if choice == "1":
                accounts = manager.list_accounts()
                if not accounts:
                    print("暂无账号")
                else:
                    print(f"\n共 {len(accounts)} 个账号:")
                    for i, acc in enumerate(accounts, 1):
                        status = "已登录" if acc.logged_in else "未登录"
                        name = acc.name or "未知"
                        print(f"  {i}. {acc.phone} - {name} [{status}]")
            
            elif choice == "2":
                phone = input("输入手机号 (带国际区号，如+8613812345678): ").strip()
                if phone:
                    success, msg = await manager.login_account(phone)
                    print(msg)
            
            elif choice == "3":
                print("输入账号配置 (格式: 手机号|验证码URL，每行一个，空行结束):")
                configs = []
                while True:
                    line = input().strip()
                    if not line:
                        break
                    configs.append(line)
                
                for config in configs:
                    phone, api_url = parse_account_config(config)
                    print(f"\n正在登录 {phone}...")
                    success, msg = await manager.login_account(phone, api_url)
                    print(msg)
                    await asyncio.sleep(2)  # 避免请求过快
            
            elif choice == "4":
                # tdata 导入
                if not OPENTELE_AVAILABLE:
                    print(f"opentele 不可用: {OPENTELE_ERROR}")
                    print("opentele在Windows + Python 3.14上存在兼容性问题")
                    print("请使用其他登录方式（选项1或2）")
                    continue
                
                print("\n从 Telegram Desktop 导入账号")
                print("注意: 导入后会创建新会话，原 Telegram Desktop 仍可正常使用")
                custom_path = input("输入 tdata 路径 (留空使用默认路径): ").strip()
                tdata_path = custom_path if custom_path else None
                
                results = await manager.import_from_tdata(tdata_path)
                print("\n导入结果:")
                for success, msg in results:
                    status = "+" if success else "x"
                    print(f"  {status} {msg}")
            
            elif choice == "5":
                phone = input("选择账号 (手机号): ").strip()
                target = input("输入目标 (用户名/@xxx 或 ID): ").strip()
                message = input("输入消息: ").strip()
                
                if phone and target and message:
                    success, msg = await sender.send_from_account(phone, target, message)
                    print(msg)
            
            elif choice == "6":
                target = input("输入目标 (用户名/@xxx 或 ID): ").strip()
                message = input("输入消息: ").strip()
                delay = float(input("发送间隔秒数 (默认1.0): ").strip() or "1.0")
                
                if target and message:
                    await sender.send_from_all(target, message, delay)
            
            elif choice == "7":
                phone = input("输入要删除的手机号: ").strip()
                if phone:
                    manager.remove_account(phone)
                    print(f"已删除账号 {phone}")
            
            elif choice == "8":
                break
        
    finally:
        await manager.close_all()


# === 编程接口 ===

async def quick_send(phone: str, target, message: str, api_url: str = "") -> bool:
    """快速发送消息
    
    Example:
        import asyncio
        from telegram_multi_sender import quick_send
        
        asyncio.run(quick_send(
            phone="+8613812345678",
            target="@username",
            message="Hello!"
        ))
    """
    manager = AccountManager()
    try:
        success, msg = await manager.login_account(phone, api_url)
        if not success:
            print(msg)
            return False
        
        sender = MultiSender(manager)
        success, msg = await sender.send_from_account(phone, target, message)
        print(msg)
        return success
    finally:
        await manager.close_all()


async def batch_login(configs: List[str]) -> Dict[str, bool]:
    """批量登录账号
    
    Args:
        configs: ["手机号|URL", ...] 格式的配置列表
    
    Returns:
        {手机号: 是否登录成功}
    """
    manager = AccountManager()
    results = {}
    
    try:
        for config in configs:
            phone, api_url = parse_account_config(config)
            success, msg = await manager.login_account(phone, api_url)
            results[phone] = success
            print(msg)
            await asyncio.sleep(2)
    finally:
        await manager.close_all()
    
    return results


async def import_tdata(tdata_path: str = None) -> List[Dict]:
    """从 Telegram Desktop 导入账号
    
    Args:
        tdata_path: tdata 路径，默认使用 Telegram Desktop 的路径
    
    Returns:
        导入的账号列表 [{phone, name, username, user_id}, ...]
        
    Example:
        import asyncio
        from telegram_multi_sender import import_tdata
        
        accounts = asyncio.run(import_tdata())
        for acc in accounts:
            print(f"导入: {acc['name']} ({acc['phone']})")
    """
    manager = AccountManager()
    imported = []
    
    try:
        results = await manager.import_from_tdata(tdata_path)
        
        for success, msg in results:
            print(msg)
        
        # 返回成功导入的账号信息
        for phone, acc in manager.accounts.items():
            if acc.logged_in:
                imported.append({
                    'phone': acc.phone,
                    'name': acc.name,
                    'username': acc.username,
                    'user_id': acc.user_id
                })
    finally:
        await manager.close_all()
    
    return imported


async def get_all_logged_accounts() -> List[Dict]:
    """获取所有已保存且可用的账号
    
    Returns:
        [{phone, name, username, user_id, logged_in}, ...]
    """
    manager = AccountManager()
    accounts = []
    
    try:
        for phone, acc in manager.accounts.items():
            # 尝试连接验证
            client = await manager.get_client(phone)
            is_valid = client is not None
            
            accounts.append({
                'phone': acc.phone,
                'name': acc.name,
                'username': acc.username,
                'user_id': acc.user_id,
                'logged_in': is_valid
            })
    finally:
        await manager.close_all()
    
    return accounts


if __name__ == "__main__":
    asyncio.run(interactive_mode())
