import discord
from discord.ext import commands
from discord import app_commands
import random
import asyncio
import datetime
import time
import hashlib
import json
import aiohttp
import os
import io
import base64
import socket
import ssl
import uuid
import sys
import qrcode
import matplotlib.pyplot as plt
import yfinance as yf
import dns.resolver
from gtts import gTTS
from textblob import TextBlob
import numpy as np # Added for graph command
from dotenv import load_dotenv

# Avoid UnicodeEncodeError in logs on non-UTF8 environments.
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

load_dotenv()

# ===== Bot & 設定 =====

VERIFIED_ROLE_NAME = "Verified"  # 役割未指定時に自動作成するロール名
VERIFY_CONFIG_FILE = "verify_buttons.json"  # ボタンが紐づくロールIDの保存先
PRODUCT_CONFIG_FILE = "product_buttons.json"  # 商品ボタンの状態保存
PAYPAY_CHANNEL_FILE = "paypay_notify_channel.json"  # PayPayギフト確認用チャンネル（ギルドごと）
PENDING_ORDERS_FILE = "pending_orders.json"  # 購入申請の状態
WEB_AUTH_FILE = "web_auth_tokens.json"  # Web認証トークン管理
AUTO_SYNC_ON_READY = os.getenv("AUTO_SYNC_ON_READY", "true").lower() in {"1", "true", "yes", "on"}
CLEAR_GUILD_COMMANDS_ON_READY = os.getenv("CLEAR_GUILD_COMMANDS_ON_READY", "false").lower() in {"1", "true", "yes", "on"}
SYNC_COOLDOWN_SECONDS = int(os.getenv("SYNC_COOLDOWN_SECONDS", "1800"))  # 30分
STARTUP_RETRY_BASE_SECONDS = int(os.getenv("STARTUP_RETRY_BASE_SECONDS", "30"))
STARTUP_RETRY_MAX_SECONDS = int(os.getenv("STARTUP_RETRY_MAX_SECONDS", "900"))  # 15分
STARTUP_RETRY_LIMIT = int(os.getenv("STARTUP_RETRY_LIMIT", "0"))  # 0: 無制限
WAITRESS_THREADS = int(os.getenv("WAITRESS_THREADS", "8"))
ENABLE_MESSAGE_CONTENT_INTENT = os.getenv("ENABLE_MESSAGE_CONTENT_INTENT", "true").lower() in {"1", "true", "yes", "on"}
ENABLE_MEMBERS_INTENT = os.getenv("ENABLE_MEMBERS_INTENT", "true").lower() in {"1", "true", "yes", "on"}


def load_verify_role_ids():
    try:
        with open(VERIFY_CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return set(int(x) for x in data)
    except FileNotFoundError:
        return set()
    except Exception as e:
        print(f"⚠️ 認証ボタン設定の読み込みに失敗しました: {e}")
        return set()


def persist_verify_role_id(role_id: int):
    current = load_verify_role_ids()
    if role_id in current:
        return
    current.add(role_id)
    try:
        with open(VERIFY_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(list(current), f)
    except Exception as e:
        print(f"⚠️ 認証ボタン設定の保存に失敗しました: {e}")


def load_product_configs():
    try:
        with open(PRODUCT_CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except Exception as e:
        print(f"⚠️ 商品ボタン設定の読み込みに失敗しました: {e}")
        return {}


def persist_product_config(product_id: str, data: dict):
    try:
        current = load_product_configs()
        current[product_id] = data
        with open(PRODUCT_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(current, f)
    except Exception as e:
        print(f"⚠️ 商品ボタン設定の保存に失敗しました: {e}")


def load_paypay_notify_channels() -> dict[int, int]:
    try:
        with open(PAYPAY_CHANNEL_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
            return {int(k): int(v) for k, v in raw.items()}
    except FileNotFoundError:
        return {}
    except Exception as e:
        print(f"⚠️ PayPay通知チャンネル設定の読み込みに失敗しました: {e}")
        return {}


def persist_paypay_notify_channel(guild_id: int, channel_id: int):
    data = load_paypay_notify_channels()
    data[int(guild_id)] = int(channel_id)
    try:
        with open(PAYPAY_CHANNEL_FILE, "w", encoding="utf-8") as f:
            json.dump({str(k): v for k, v in data.items()}, f)
    except Exception as e:
        print(f"⚠️ PayPay通知チャンネル設定の保存に失敗しました: {e}")


def get_paypay_notify_channel_id(guild_id: int) -> int | None:
    return load_paypay_notify_channels().get(int(guild_id))


def load_pending_orders() -> dict:
    try:
        with open(PENDING_ORDERS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except Exception as e:
        print(f"⚠️ 購入申請データの読み込みに失敗しました: {e}")
        return {}


def persist_pending_orders(orders: dict):
    try:
        with open(PENDING_ORDERS_FILE, "w", encoding="utf-8") as f:
            json.dump(orders, f)
    except Exception as e:
        print(f"⚠️ 購入申請データの保存に失敗しました: {e}")


def get_order(order_id: str) -> dict | None:
    return load_pending_orders().get(order_id)


def upsert_order(order_id: str, data: dict):
    orders = load_pending_orders()
    orders[order_id] = data
    persist_pending_orders(orders)


def update_order_status(order_id: str, status: str):
    orders = load_pending_orders()
    if order_id not in orders:
        return
    orders[order_id]["status"] = status
    persist_pending_orders(orders)


def load_web_auth_tokens() -> dict:
    try:
        with open(WEB_AUTH_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except Exception as e:
        print(f"⚠️ Web認証トークンの読み込みに失敗しました: {e}")
        return {}


def persist_web_auth_tokens(tokens: dict):
    try:
        with open(WEB_AUTH_FILE, "w", encoding="utf-8") as f:
            json.dump(tokens, f)
    except Exception as e:
        print(f"⚠️ Web認証トークンの保存に失敗しました: {e}")


def generate_web_auth_token(user_id: int, user_name: str) -> str:
    """Web認証用トークンを生成"""
    import secrets
    token = secrets.token_urlsafe(32)
    
    tokens = load_web_auth_tokens()
    tokens[token] = {
        "user_id": user_id,
        "user_name": user_name,
        "created_at": datetime.datetime.now().isoformat(),
        "expires_at": (datetime.datetime.now() + datetime.timedelta(hours=1)).isoformat()
    }
    persist_web_auth_tokens(tokens)
    return token


def validate_web_auth_token(token: str) -> dict | None:
    """Web認証トークンを検証"""
    tokens = load_web_auth_tokens()
    if token not in tokens:
        return None
    
    token_data = tokens[token]
    expires_at = datetime.datetime.fromisoformat(token_data["expires_at"])
    
    if datetime.datetime.now() > expires_at:
        # 期限切れトークンを削除
        del tokens[token]
        persist_web_auth_tokens(tokens)
        return None
    
    return token_data


def is_guild_manager(interaction: discord.Interaction) -> bool:
    guild = interaction.guild
    if not guild:
        return False
    member = guild.get_member(interaction.user.id)
    if not member:
        return False
    return member.guild_permissions.administrator or member.guild_permissions.manage_guild


async def ensure_verified_role(guild: discord.Guild):
    """Ensure the default verification role exists; create it if missing."""
    for role in guild.roles:
        if role.name.lower() == VERIFIED_ROLE_NAME.lower():
            return role
    try:
        return await guild.create_role(name=VERIFIED_ROLE_NAME, reason="Verification button setup")
    except discord.Forbidden:
        return None
    except Exception as e:
        print(f"⚠️ ロール作成エラー: {e}")
        return None


class VerificationView(discord.ui.View):
    def __init__(self, role_id: int):
        super().__init__(timeout=None)
        self.role_id = role_id
        button = discord.ui.Button(
            label="認証する",
            style=discord.ButtonStyle.success,
            custom_id=f"verify_button:{role_id}"
        )

        async def on_click(interaction: discord.Interaction):
            guild = interaction.guild
            if not guild:
                await interaction.response.send_message("サーバー内でのみ利用できます。", ephemeral=True)
                return

            role = guild.get_role(self.role_id)
            if role is None:
                await interaction.response.send_message("❌ 紐づくロールが見つかりませんでした。サーバー管理者に連絡してください。", ephemeral=True)
                return

            member = interaction.user
            if role in member.roles:
                await interaction.response.send_message("すでに認証済みです。", ephemeral=True)
                return

            try:
                await member.add_roles(role, reason="Verification button")
                await interaction.response.send_message("✅ 認証しました！", ephemeral=True)
            except discord.Forbidden:
                await interaction.response.send_message("❌ ロールを付与できません。Botの権限とロール順位を確認してください。", ephemeral=True)
            except Exception as e:
                await interaction.response.send_message(f"❌ エラー: {e}", ephemeral=True)

        button.callback = on_click
        self.add_item(button)


class PayPayGiftModal(discord.ui.Modal):
    """購入者が PayPay ギフトリンクを入力するモーダル。"""

    def __init__(self, product_id: str, product_title: str, selected_option: str, buy_url: str | None):
        super().__init__(title="PayPayギフトリンク")
        self.product_id = product_id
        self.product_title = product_title
        self.selected_option = selected_option
        self.buy_url = (buy_url.strip() if buy_url else None) or None
        self.link_input = discord.ui.TextInput(
            label="PayPayギフトのURL",
            placeholder="https://pay.paypay.ne.jp/ ...",
            style=discord.TextStyle.short,
            required=True,
            max_length=500,
        )
        self.add_item(self.link_input)

    async def on_submit(self, interaction: discord.Interaction):
        guild = interaction.guild
        if not guild:
            await interaction.response.send_message("サーバー内でのみ利用できます。", ephemeral=True)
            return

        notify_ch_id = get_paypay_notify_channel_id(guild.id)
        if not notify_ch_id:
            await interaction.response.send_message(
                "管理者がまだ PayPay 確認用チャンネルを設定していません。サーバー所有者に `/set_paypay_channel` の設定を依頼してください。",
                ephemeral=True,
            )
            return

        channel = guild.get_channel(notify_ch_id)
        if not channel or not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message("通知チャンネルが無効です。管理者に連絡してください。", ephemeral=True)
            return

        me = guild.me
        if me and not channel.permissions_for(me).send_messages:
            await interaction.response.send_message("Bot が通知チャンネルに投稿できません。権限を確認してください。", ephemeral=True)
            return

        gift_link = self.link_input.value.strip()
        buyer = interaction.user
        order_id = uuid.uuid4().hex

        embed = discord.Embed(
            title="購入申請（PayPayギフト）",
            color=0xFEE75C,
            timestamp=datetime.datetime.now(datetime.timezone.utc),
        )
        embed.add_field(name="ユーザー", value=f"{buyer.mention} (`{buyer.id}`)", inline=False)
        embed.add_field(name="商品", value=self.product_title[:1024], inline=True)
        embed.add_field(name="選択", value=self.selected_option[:1024], inline=True)
        embed.add_field(name="PayPayギフトリンク", value=f"```{gift_link}```", inline=False)
        if self.buy_url:
            embed.add_field(
                name="商品に登録されたダウンロードURL",
                value=f"```{self.buy_url[:900]}```",
                inline=False,
            )

        view = AdminOrderView(order_id)
        interaction.client.add_view(view)

        await interaction.response.defer(ephemeral=True)

        msg = await channel.send(embed=embed, view=view)
        upsert_order(
            order_id,
            {
                "guild_id": guild.id,
                "channel_id": channel.id,
                "message_id": msg.id,
                "buyer_id": buyer.id,
                "buyer_name": str(buyer),
                "product_id": self.product_id,
                "product_title": self.product_title,
                "selected_option": self.selected_option,
                "gift_link": gift_link,
                "buy_url": self.buy_url,
                "status": "pending",
            },
        )

        await interaction.followup.send(
            "PayPayギフトリンクを管理者に送信しました。内容確認後、DMでダウンロード案内が届きます。",
            ephemeral=True,
        )


class DownloadLinkModal(discord.ui.Modal):
    """管理者が商品のダウンロードURLを入力して購入者にDM送付。"""

    def __init__(self, order_id: str):
        super().__init__(title="ダウンロードリンクを送付")
        self.order_id = order_id
        order = get_order(order_id) or {}
        default_url = (order.get("buy_url") or "").strip() or None
        if default_url and len(default_url) > 400:
            default_url = default_url[:400]
        self.url_input = discord.ui.TextInput(
            label="ダウンロードURL",
            style=discord.TextStyle.short,
            required=True,
            max_length=500,
            default=default_url if default_url else None,
        )
        self.add_item(self.url_input)

    async def on_submit(self, interaction: discord.Interaction):
        if not is_guild_manager(interaction):
            await interaction.response.send_message("この操作は管理者のみ実行できます。", ephemeral=True)
            return

        order = get_order(self.order_id)
        if not order or order.get("status") != "pending":
            await interaction.response.send_message("この申請は既に処理済みです。", ephemeral=True)
            return

        url = self.url_input.value.strip()
        buyer_id = int(order["buyer_id"])
        user = interaction.client.get_user(buyer_id)
        if user is None:
            try:
                user = await interaction.client.fetch_user(buyer_id)
            except discord.NotFound:
                await interaction.response.send_message("購入者ユーザーが見つかりません。", ephemeral=True)
                return

        product_title = order.get("product_title", "商品")
        selected = order.get("selected_option", "")
        try:
            await user.send(f"**{product_title}**（{selected}）のダウンロードリンクです:\n{url}")
        except discord.Forbidden:
            await interaction.response.send_message(
                "DM を送信できませんでした（受信設定をオフにしている可能性があります）。別途ユーザーに連絡してください。",
                ephemeral=True,
            )
            return

        ch = interaction.client.get_channel(int(order["channel_id"]))
        if ch:
            try:
                msg = await ch.fetch_message(int(order["message_id"]))
                if msg.embeds:
                    old = msg.embeds[0]
                    emb = discord.Embed(title=old.title, description=old.description, color=discord.Color.green())
                    for field in old.fields:
                        emb.add_field(name=field.name, value=field.value, inline=field.inline)
                    emb.set_footer(text="ステータス: DLリンクを送付済み")
                    if old.timestamp:
                        emb.timestamp = old.timestamp
                    await msg.edit(embed=emb, view=None)
            except Exception as e:
                print(f"⚠️ 管理者メッセージ更新エラー: {e}")

        update_order_status(self.order_id, "fulfilled")
        await interaction.response.send_message("購入者にダウンロードリンクを送信しました。", ephemeral=True)


class AdminOrderView(discord.ui.View):
    """通知チャンネル上で管理者が送付/却下を選ぶビュー。"""

    def __init__(self, order_id: str):
        super().__init__(timeout=None)
        self.order_id = order_id

        fulfill_btn = discord.ui.Button(
            label="DLリンクを送付",
            style=discord.ButtonStyle.success,
            custom_id=f"order_fulfill:{order_id}",
        )
        decline_btn = discord.ui.Button(
            label="送付しない（却下）",
            style=discord.ButtonStyle.danger,
            custom_id=f"order_decline:{order_id}",
        )
        approve_role_btn = discord.ui.Button(
            label="ロール付与 & 承認",
            style=discord.ButtonStyle.success,
            custom_id=f"order_role_approve:{order_id}",
            emoji="👑"
        )
        fulfill_btn.callback = self._on_fulfill
        decline_btn.callback = self._on_decline
        approve_role_btn.callback = self._on_approve_role
        self.add_item(fulfill_btn)
        self.add_item(approve_role_btn)
        self.add_item(decline_btn)

    async def _on_approve_role(self, interaction: discord.Interaction):
        if not is_guild_manager(interaction):
            await interaction.response.send_message("この操作は管理者のみ実行できます。", ephemeral=True)
            return
        
        order = get_order(self.order_id)
        if not order:
            await interaction.response.send_message("注文データが見つかりません。", ephemeral=True)
            return

        guild = interaction.guild
        buyer_id = int(order["buyer_id"])
        member = guild.get_member(buyer_id)
        if not member:
            try:
                member = await guild.fetch_member(buyer_id)
            except discord.NotFound:
                await interaction.response.send_message("購入者がサーバー内に見つかりません。", ephemeral=True)
                return

        # 商品詳細から Role ID を探す
        product_detail = order.get("selected_option", "")
        import re
        role_match = re.search(r"Role: (\d+)", product_detail)
        
        if not role_match:
            await interaction.response.send_message("この商品には自動付与ロールが設定されていません。手動で対応してください。", ephemeral=True)
            return

        role_id = int(role_match.group(1))
        role = guild.get_role(role_id)
        
        if not role:
            await interaction.response.send_message(f"❌ ロール (ID: {role_id}) が見つかりません。", ephemeral=True)
            return

        try:
            await member.add_roles(role, reason=f"Web Store Purchase: {order['product_title']}")
            update_order_status(self.order_id, "fulfilled")
            
            # メッセージ更新
            ch = interaction.client.get_channel(int(order["channel_id"]))
            if ch:
                msg = await ch.fetch_message(int(order["message_id"]))
                emb = msg.embeds[0]
                emb.color = discord.Color.gold()
                emb.set_footer(text="ステータス: ロール付与済み (自動)")
                await msg.edit(embed=emb, view=None)

            await interaction.response.send_message(f"✅ {member.mention} に {role.name} を付与しました。", ephemeral=True)
            try:
                await member.send(f"🌟 ご購入ありがとうございます！**{role.name}** ロールを付与しました。")
            except: pass
            
        except discord.Forbidden:
            await interaction.response.send_message("❌ ロール付与権限がありません。Botのロールを一番上に移動してください。", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ エラーが発生しました: {e}", ephemeral=True)


    async def _on_fulfill(self, interaction: discord.Interaction):
        if not is_guild_manager(interaction):
            await interaction.response.send_message("この操作は管理者のみ実行できます。", ephemeral=True)
            return
        order = get_order(self.order_id)
        if not order or order.get("status") != "pending":
            await interaction.response.send_message("この申請は既に処理済みです。", ephemeral=True)
            return
        await interaction.response.send_modal(DownloadLinkModal(self.order_id))

    async def _on_decline(self, interaction: discord.Interaction):
        if not is_guild_manager(interaction):
            await interaction.response.send_message("この操作は管理者のみ実行できます。", ephemeral=True)
            return
        order = get_order(self.order_id)
        if not order or order.get("status") != "pending":
            await interaction.response.send_message("この申請は既に処理済みです。", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        ch = interaction.client.get_channel(int(order["channel_id"]))
        if ch:
            try:
                msg = await ch.fetch_message(int(order["message_id"]))
                if msg.embeds:
                    old = msg.embeds[0]
                    emb = discord.Embed(title=old.title, description=old.description, color=discord.Color.red())
                    for field in old.fields:
                        emb.add_field(name=field.name, value=field.value, inline=field.inline)
                    emb.set_footer(text="ステータス: 却下")
                    if old.timestamp:
                        emb.timestamp = old.timestamp
                    await msg.edit(embed=emb, view=None)
            except Exception as e:
                print(f"⚠️ 管理者メッセージ更新エラー: {e}")

        update_order_status(self.order_id, "declined")
        await interaction.followup.send("却下しました。", ephemeral=True)


class ProductView(discord.ui.View):
    def __init__(self, product_id: str, stock_text: str, product_title: str, options: list[str], buy_url: str | None = None):
        super().__init__(timeout=None)
        self.product_id = product_id
        self.stock_text = stock_text
        self.product_title = product_title or "商品"
        self.buy_url = (buy_url.strip() if buy_url else None) or None
        self.options = options or []

        buy_button = discord.ui.Button(
            label="購入する",
            style=discord.ButtonStyle.primary,
            custom_id=f"product_buy:{product_id}",
        )
        stock_button = discord.ui.Button(
            label="在庫確認",
            style=discord.ButtonStyle.success,
            custom_id=f"product_stock:{product_id}",
        )

        async def on_buy(interaction: discord.Interaction):
            if not self.options:
                await interaction.response.send_message("商品リストが見つかりません。管理者にお問い合わせください。", ephemeral=True)
                return

            select = discord.ui.Select(
                placeholder="購入する商品を選択してください",
                options=[discord.SelectOption(label=opt[:100], value=opt[:100]) for opt in self.options][:25],
            )

            async def on_select(select_interaction: discord.Interaction):
                chosen = select.values[0]
                modal = PayPayGiftModal(self.product_id, self.product_title, chosen, self.buy_url)
                await select_interaction.response.send_modal(modal)

            select.callback = on_select
            view = discord.ui.View()
            view.add_item(select)
            await interaction.response.send_message("購入する商品を選択してください。", view=view, ephemeral=True)

        async def on_stock(interaction: discord.Interaction):
            await interaction.response.send_message(f"在庫情報: {self.stock_text}", ephemeral=True)

        buy_button.callback = on_buy
        stock_button.callback = on_stock
        self.add_item(buy_button)
        self.add_item(stock_button)


# Botの設定
intents = discord.Intents.default()
intents.message_content = ENABLE_MESSAGE_CONTENT_INTENT
intents.members = ENABLE_MEMBERS_INTENT

# プレフィックスコマンドとスラッシュコマンドの両方を使用
bot = commands.Bot(command_prefix=commands.when_mentioned_or("!", "."), intents=intents, help_command=None)
last_global_sync_at: datetime.datetime | None = None
persistent_views_registered = False


def _utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def sanitize_discord_token(raw_token: str | None) -> str | None:
    if raw_token is None:
        return None
    token = raw_token.strip()
    if len(token) >= 2 and ((token[0] == '"' and token[-1] == '"') or (token[0] == "'" and token[-1] == "'")):
        token = token[1:-1].strip()
    return token or None


def get_discord_token_from_env() -> tuple[str | None, str | None, bool]:
    for env_name in ("DISCORD_TOKEN", "DISCORD_TOKEN2"):
        raw_token = os.getenv(env_name)
        if raw_token is None:
            continue
        token = sanitize_discord_token(raw_token)
        token_was_normalized = token != raw_token
        return env_name, token, token_was_normalized
    return None, None, False


def _is_rate_limit_error(error: Exception) -> bool:
    text = str(error).lower()
    if isinstance(error, discord.HTTPException) and error.status == 429:
        return True
    return "rate limited" in text or "error 1015" in text or "cloudflare" in text


async def safe_sync_commands(guild: discord.Guild | None = None) -> list[app_commands.AppCommand]:
    delays = [5, 15, 45, 90]
    target = f"{guild.name} ({guild.id})" if guild else "グローバル"

    for attempt, delay in enumerate(delays, start=1):
        try:
            return await bot.tree.sync(guild=guild)
        except Exception as e:
            is_last = attempt == len(delays)
            if is_last or not _is_rate_limit_error(e):
                raise
            print(f"⚠️ {target}同期でレート制限を検出: {e}")
            print(f"⏳ {delay}秒待機して再試行します ({attempt}/{len(delays)})")
            await asyncio.sleep(delay)

    return []


@bot.event
async def on_ready():
    """Botが起動したときに呼ばれるイベント"""
    global last_global_sync_at, persistent_views_registered

    print(f'✅ ログイン: {bot.user.name}')
    print(f'🆔 Bot ID: {bot.user.id}')
    print(f'📡 接続サーバー数: {len(bot.guilds)}')
    # 永続ビューを再登録（再起動後も認証ボタンを動かす）
    if not persistent_views_registered:
        for role_id in load_verify_role_ids():
            bot.add_view(VerificationView(role_id))
        for pid, pdata in load_product_configs().items():
            bot.add_view(
                ProductView(
                    pid,
                    pdata.get("stock_text", "在庫未設定"),
                    pdata.get("title", "商品"),
                    pdata.get("options", []),
                    pdata.get("buy_url"),
                )
            )
        for oid, odata in load_pending_orders().items():
            if odata.get("status") == "pending":
                bot.add_view(AdminOrderView(oid))
        persistent_views_registered = True

    if not AUTO_SYNC_ON_READY:
        print("⏭️ AUTO_SYNC_ON_READY=false のため起動時同期をスキップしました")
        print('------')
        return

    now = _utc_now()
    if last_global_sync_at and (now - last_global_sync_at).total_seconds() < SYNC_COOLDOWN_SECONDS:
        remaining = int(SYNC_COOLDOWN_SECONDS - (now - last_global_sync_at).total_seconds())
        print(f"⏭️ 起動時同期をスキップしました (クールダウン残り: {remaining}秒)")
        print('------')
        return

    # スラッシュコマンドを同期
    try:
        if CLEAR_GUILD_COMMANDS_ON_READY:
            for guild in bot.guilds:
                bot.tree.clear_commands(guild=guild)
                await safe_sync_commands(guild=guild)
        synced = await safe_sync_commands()
        last_global_sync_at = _utc_now()
        print(f'🔄 コマンドをグローバル同期しました ({len(synced)}個)')
    except Exception as e:
        print(f'❌ コマンド同期エラー: {e}')
    print('------')


@bot.event
async def on_message(message):
    if message.author == bot.user:
        return

    # Web Store Webhook からのメッセージを監視 (BOTがWebhookメッセージを拾うための工夫)
    # ※ 本来Webhookメッセージは on_message に入らないことが多いですが、
    # ユーザーがリンクを貼ったり、Bot自身が検知できる形式で連携します。
    # 今回はウェブストアが Bot の /api/order を叩くのではなく Webhook を使う想定なので
    # もしBotに直接注文を送りたい場合は Flask の API を拡張するのがベストです。
    
    await bot.process_commands(message)


# ===== エラーハンドリング =====

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"❌ 引数が足りません！使い方はこちら:\n`{ctx.prefix}{ctx.command.name} {ctx.command.signature}`")
    elif isinstance(error, commands.BadArgument):
        await ctx.send(f"❌ 入力された値が正しくありません。")
    elif isinstance(error, commands.CommandNotFound):
        pass
    else:
        print(f"⚠️ エラー: {error}")


# ===== ヘルプコマンド (プレミアムデザイン) =====

async def send_help(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🌌 PRIM BOT ULTIMATE MENU",
        description="ユーティリティと商品販売（PayPayギフト）向けのボットです。",
        color=0x2b2d31
    )
    embed.add_field(name="📝 NLP", value="`/translate`, `/sentiment`, `/tts` ", inline=False)
    embed.add_field(name="💻 Developers", value="`/code`, `/github`, `/mermaid`, `/json`, `/hash`, `/password_gen` ", inline=False)
    embed.add_field(name="🌐 Network", value="`/http`, `/dns`, `/scan`, `/ssl`, `/ipinfo` ", inline=False)
    embed.add_field(name="📊 Tools & Media", value="`/graph`, `/qr`, `/crypto`, `/stock`, `/calc` ", inline=False)
    embed.add_field(name="🛠️ Utility", value="`/setup_verify`, `/set_paypay_channel`, `/post_product`, `/clear`, `/clear_all`, `/remind`, `/poll`, `/say`, `/web_auth` ", inline=False)
    embed.set_footer(text="すべてのコマンドはスラッシュコマンド '/' で利用可能です。")
    
    if isinstance(interaction, discord.Interaction):
        await interaction.response.send_message(embed=embed)
    else:
        await interaction.send(embed=embed)

@bot.command(name='help')
async def help_ctx(ctx): await send_help(ctx)

@bot.tree.command(name='help', description='すべての高度なコマンドを表示します')
async def help_slash(interaction: discord.Interaction): await send_help(interaction)


@bot.command(name='join')
async def join_ctx(ctx):
    """実行者がいるボイスチャンネルにBotを参加させる (.join / !join)"""
    if not ctx.guild:
        await ctx.send("❌ このコマンドはサーバー内でのみ使えます。")
        return

    if not ctx.author.voice or not ctx.author.voice.channel:
        await ctx.send("❌ 先にあなたがボイスチャンネルへ参加してください。")
        return

    target_channel = ctx.author.voice.channel
    voice_client = ctx.guild.voice_client

    try:
        if voice_client and voice_client.is_connected():
            if voice_client.channel and voice_client.channel.id == target_channel.id:
                await ctx.send(f"✅ すでに {target_channel.mention} に参加しています。")
                return
            await voice_client.move_to(target_channel)
        else:
            await target_channel.connect()
        await ctx.send(f"🔊 {target_channel.mention} に参加しました。")
    except Exception as e:
        await ctx.send(f"❌ VC参加に失敗しました: {e}")


@bot.command(name='menbaku', aliases=['めんばく'])
async def menbaku_ctx(ctx):
    """管理者専用: サーバーメンバーを分割でメンションする (.menbaku / !menbaku)"""
    if not ctx.guild:
        await ctx.send("❌ このコマンドはサーバー内でのみ使えます。")
        return

    if not ctx.author.guild_permissions.administrator:
        await ctx.send("❌ このコマンドは管理者のみ使用できます。")
        return

    members = [m for m in ctx.guild.members if not m.bot]
    if not members:
        await ctx.send("ℹ️ メンション対象のメンバーがいません。")
        return

    chunk_size = 20
    total_chunks = (len(members) + chunk_size - 1) // chunk_size
    await ctx.send(f"📣 メンバー通知を開始します。対象: {len(members)}人")

    for i in range(0, len(members), chunk_size):
        chunk = members[i:i + chunk_size]
        mentions = " ".join(m.mention for m in chunk)
        await ctx.send(
            mentions,
            allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
        )
        if (i // chunk_size) + 1 < total_chunks:
            await asyncio.sleep(1.2)

    await ctx.send("✅ メンバー通知が完了しました。")


# ===== 自然言語処理 (NLP) =====

@bot.tree.command(name='translate', description='テキストを翻訳します（英語など）')
async def translate_slash(interaction: discord.Interaction, text: str, to_lang: str = "ja"):
    await interaction.response.defer()
    try:
        blob = TextBlob(text)
        translated = str(blob.translate(to=to_lang))
        await interaction.followup.send(f"🌐 **翻訳結果 ({to_lang})**:\n`{translated}`")
    except Exception as e:
        await interaction.followup.send(f"❌ 翻訳エラー: {e} (短すぎるか、すでにその言語の可能性があります)")

@bot.tree.command(name='sentiment', description='文章の感情を分析します')
async def sentiment_slash(interaction: discord.Interaction, text: str):
    blob = TextBlob(text)
    polarity = blob.sentiment.polarity
    res = "ポジティブ 😊" if polarity > 0.1 else "ネガティブ 😞" if polarity < -0.1 else "ニュートラル 😐"
    await interaction.response.send_message(f"🧠 **感情分析結果**: `{res}` (スコア: {polarity:.2f})")

@bot.tree.command(name='tts', description='テキストを音声(MP3)に変換します')
async def tts_slash(interaction: discord.Interaction, text: str):
    await interaction.response.defer()
    try:
        tts = gTTS(text=text, lang='ja')
        buf = io.BytesIO()
        tts.write_to_fp(buf)
        buf.seek(0)
        await interaction.followup.send("🎙️ 音声を生成しました：", file=discord.File(buf, "speech.mp3"))
    except Exception as e:
        await interaction.followup.send(f"❌ TTSエラー: {e}")

# ===== 💻 Developers & Security =====

@bot.tree.command(name='code', description='コードを実行します (Codapi利用)')
@app_commands.describe(lang='言語 (python, js, cpp, etc.)', code='実行するコード')
async def code_slash(interaction: discord.Interaction, lang: str, code: str):
    await interaction.response.defer()
    lang_map = {"py": "python", "js": "javascript", "node": "javascript", "cpp": "cpp", "c": "c", "py3": "python"}
    sandbox = lang_map.get(lang.lower(), lang.lower())
    
    code = code.strip('`').strip()
    if code.startswith(lang): code = code[len(lang):].lstrip()

    payload = {
        "sandbox": sandbox,
        "version": "",
        "command": "run",
        "files": {"": code}
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post("https://api.codapi.org/v1/exec", json=payload) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    await interaction.followup.send(f"❌ APIエラー: `{resp.status}`\n詳細: {error_text[:200]}")
                    return
                data = await resp.json()
                output = data.get("stdout", "") + data.get("stderr", "")
                if not output: output = "(出力なし)"
                
                if len(output) > 1900: output = output[:1900] + "\n...(省略)"
                await interaction.followup.send(f"💻 **実行結果 ({sandbox})**:\n```\n{output}\n```")
    except Exception as e:
        await interaction.followup.send(f"❌ 実行エラー: {e}")

@bot.tree.command(name='github', description='GitHubリポジトリの情報を取得します')
async def github_slash(interaction: discord.Interaction, repo: str):
    async with aiohttp.ClientSession() as session:
        async with session.get(f"https://api.github.com/repos/{repo}") as resp:
            if resp.status != 200:
                await interaction.response.send_message("❌ リポジトリが見つかりません。例: `google/jax` ")
                return
            data = await resp.json()
            embed = discord.Embed(title=f"📦 {data['full_name']}", url=data['html_url'], color=0x2b2d31)
            embed.description = data['description']
            embed.add_field(name="⭐ Stars", value=data['stargazers_count'])
            embed.add_field(name="🍴 Forks", value=data['forks_count'])
            embed.add_field(name="🛠️ Language", value=data['language'])
            await interaction.response.send_message(embed=embed)

@bot.tree.command(name='mermaid', description='Mermaid記法を画像に変換します')
async def mermaid_slash(interaction: discord.Interaction, code: str):
    await interaction.response.defer()
    code_bytes = code.encode('utf-8')
    base64_str = base64.b64encode(code_bytes).decode('utf-8')
    url = f"https://mermaid.ink/img/{base64_str}"
    await interaction.followup.send(f"📊 **Mermaid Diagram**:\n{url}")

@bot.tree.command(name='json', description='JSONを整形します')
async def json_slash(interaction: discord.Interaction, text: str):
    try:
        data = json.loads(text.strip('`'))
        pretty = json.dumps(data, indent=4, ensure_ascii=False)
        if len(pretty) > 1900: pretty = pretty[:1900] + "\n...(省略)"
        await interaction.response.send_message(f"📄 **JSON Formatted**:\n```json\n{pretty}\n```")
    except Exception as e:
        await interaction.response.send_message(f"❌ 無効なJSONです: `{e}` ")

@bot.tree.command(name='hash', description='テキストをハッシュ化します')
async def hash_slash(interaction: discord.Interaction, algo: str, text: str):
    text_bytes = text.encode('utf-8')
    if algo.lower() == 'sha256': res = hashlib.sha256(text_bytes).hexdigest()
    elif algo.lower() == 'md5': res = hashlib.md5(text_bytes).hexdigest()
    else:
        await interaction.response.send_message("❌ 対応アルゴリズム: `sha256`, `md5` ")
        return
    await interaction.response.send_message(f"🔒 **{algo.upper()}**: `{res}` ")

@bot.tree.command(name='password_gen', description='安全なパスワードを生成します')
async def passgen_slash(interaction: discord.Interaction, length: int = 16):
    chars = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789!@#$%^&*()"
    pwd = "".join(random.choice(chars) for _ in range(length))
    await interaction.response.send_message(f"🔑 **Generated Password**: `{pwd}` ", ephemeral=True)

# ===== 🌐 ネットワーク & インフラ =====

@bot.tree.command(name='http', description='URLのステータスを確認します')
async def http_slash(interaction: discord.Interaction, url: str):
    if not url.startswith("http"): url = "http://" + url
    try:
        start = datetime.datetime.now()
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=10) as resp:
                ms = (datetime.datetime.now() - start).total_seconds() * 1000
                await interaction.response.send_message(f"🌐 **{url}**\nStatus: `{resp.status} {resp.reason}`\nResponse Time: `{ms:.2f}ms`")
    except Exception as e:
        await interaction.response.send_message(f"❌ 接続エラー: {e}")

@bot.tree.command(name='dns', description='ドメインのDNS情報を取得します')
async def dns_slash(interaction: discord.Interaction, domain: str, type: str = "A"):
    try:
        answers = dns.resolver.resolve(domain, type)
        res = "\n".join([str(r) for r in answers])
        await interaction.response.send_message(f"📡 **DNS {type} Records for {domain}**:\n```\n{res}\n```")
    except Exception as e:
        await interaction.response.send_message(f"❌ DNSエラー: {e}")

@bot.tree.command(name='scan', description='ポートスキャンを実行します')
async def scan_slash(interaction: discord.Interaction, host: str, port: int):
    await interaction.response.defer()
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(3)
        result = sock.connect_ex((host, port))
        status = "OPEN 🟢" if result == 0 else "CLOSED 🔴"
        await interaction.followup.send(f"🔍 **Scan {host}:{port}** -> `{status}` ")
        sock.close()
    except Exception as e:
        await interaction.followup.send(f"❌ スキャンエラー: {e}")

@bot.tree.command(name='ssl', description='SSL証明書の情報を取得します')
async def ssl_slash(interaction: discord.Interaction, domain: str):
    await interaction.response.defer()
    try:
        context = ssl.create_default_context()
        with socket.create_connection((domain, 443)) as sock:
            with context.wrap_socket(sock, server_hostname=domain) as ssock:
                cert = ssock.getpeercert()
                expiry = cert['notAfter']
                issuer = cert['issuer'][1][0][1]
                await interaction.followup.send(f"🔒 **SSL Info: {domain}**\nIssuer: `{issuer}`\nExpiry: `{expiry}`")
    except Exception as e:
        await interaction.followup.send(f"❌ SSLエラー: {e}")

@bot.tree.command(name='ipinfo', description='IP情報を取得します')
async def ipinfo_slash(interaction: discord.Interaction, ip: str):
    try:
        if not interaction.response.is_done():
            await interaction.response.defer()
    except Exception:
        pass

    try:
        if ip in ["127.0.0.1", "localhost", "::1"] or ip.startswith("192.168.") or ip.startswith("10.") or ip.startswith("172.16."):
            await interaction.followup.send(f"🏠 **IP: {ip}** は「プライベートIP」です。", ephemeral=True)
            return

        async with aiohttp.ClientSession() as session:
            url = f"http://ip-api.com/json/{ip}?fields=status,message,country,regionName,city,zip,isp,org,as,query"
            async with session.get(url, timeout=10) as resp:
                data = await resp.json()
                if data.get('status') == 'success':
                    embed = discord.Embed(title=f"📍 IP情報: {data.get('query')}", color=0x2b2d31)
                    embed.add_field(name="🌍 国", value=data.get('country', '不明'), inline=True)
                    embed.add_field(name="🏙️ 都市", value=data.get('city', '不明'), inline=True)
                    embed.add_field(name="🏢 ISP", value=data.get('isp', '不明'), inline=False)
                    await interaction.followup.send(embed=embed)
                else:
                    await interaction.followup.send(f"❌ エラー: {data.get('message', '不明')}")
    except Exception as e:
        await interaction.followup.send(f"❌ ネットワークエラー: {e}")

# ===== 📊 グラフィック & ツール =====

@bot.tree.command(name='graph', description='数式のグラフを描画します')
async def graph_slash(interaction: discord.Interaction, expression: str):
    await interaction.response.defer()
    try:
        x = np.linspace(-10, 10, 400)
        safe_expr = expression.replace("^", "**")
        y = eval(safe_expr, {"x": x, "np": np, "sin": np.sin, "cos": np.cos, "tan": np.tan})
        plt.figure(figsize=(6, 4))
        plt.plot(x, y)
        plt.title(f"y = {expression}")
        plt.grid(True)
        buf = io.BytesIO()
        plt.savefig(buf, format='png')
        buf.seek(0)
        plt.close()
        await interaction.followup.send(file=discord.File(buf, "graph.png"))
    except Exception as e:
        await interaction.followup.send(f"❌ 描画エラー: {e}")

@bot.tree.command(name='qr', description='QRコードを生成します')
async def qr_slash(interaction: discord.Interaction, text: str):
    img = qrcode.make(text)
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    await interaction.response.send_message(f"📱 **QRコード: {text}**", file=discord.File(buf, "qr.png"))

@bot.tree.command(name='crypto', description='仮想通貨の価格を表示します')
async def crypto_slash(interaction: discord.Interaction, coin: str = "bitcoin"):
    coin = coin.lower()
    async with aiohttp.ClientSession() as session:
        url = f"https://api.coingecko.com/api/v3/simple/price?ids={coin}&vs_currencies=jpy,usd"
        async with session.get(url) as resp:
            if resp.status != 200:
                await interaction.response.send_message(f"❌ APIエラー: `{resp.status}`")
                return
            data = await resp.json()
            if coin in data:
                jpy, usd = data[coin]['jpy'], data[coin]['usd']
                await interaction.response.send_message(f"💰 **{coin.upper()}**: `{jpy:,} JPY` / `{usd:,} USD` ")
            else:
                await interaction.response.send_message(f"❌ `{coin}` が見つかりません。")

@bot.tree.command(name='stock', description='株価・為替情報を取得します')
async def stock_slash(interaction: discord.Interaction, symbol: str):
    await interaction.response.defer()
    try:
        ticker = yf.Ticker(symbol)
        price = ticker.fast_info['last_price']
        currency = ticker.fast_info['currency']
        await interaction.followup.send(f"📈 **{symbol.upper()}**: `{price:.2f} {currency}` ")
    except Exception as e:
        await interaction.followup.send(f"❌ 取得エラー: {e}")

@bot.tree.command(name='calc', description='計算を行います')
async def calc_slash(interaction: discord.Interaction, expression: str):
    allowed = "0123456789+-*/(). "
    if all(c in allowed for c in expression):
        try:
            await interaction.response.send_message(f'📈 計算結果: `{expression} = {eval(expression)}`')
        except: await interaction.response.send_message("❌ 計算エラー")
    else: await interaction.response.send_message("❌ 安全でない文字が含まれています。")

# ===== 実用ツール (スラッシュ対応) =====

@bot.tree.command(name='setup_verify', description='認証ボタンを設置（サーバー所有者のみ）')
@app_commands.describe(channel='設置先チャンネル（未指定なら現在のチャンネル）', role='付与したいロール（未指定なら新規作成の Verified）', description_text='案内文（省略可）')
async def setup_verify_slash(interaction: discord.Interaction, channel: discord.TextChannel = None, role: discord.Role = None, description_text: str = "ルールを読んだら下のボタンを押してください。"):
    guild = interaction.guild
    if not guild:
        await interaction.response.send_message("サーバー内でのみ使用できます。", ephemeral=True)
        return
    if interaction.user.id != guild.owner_id:
        await interaction.response.send_message("このコマンドはサーバー所有者のみ実行できます。", ephemeral=True)
        return

    target_channel = channel or interaction.channel
    me = guild.me
    if not target_channel.permissions_for(me).send_messages:
        await interaction.response.send_message("指定チャンネルでメッセージを送信できません。Botの権限を確認してください。", ephemeral=True)
        return
    if not me.guild_permissions.manage_roles:
        await interaction.response.send_message("Botに`ロールの管理`権限がありません。付与してください。", ephemeral=True)
        return

    target_role = role
    if target_role is None:
        target_role = await ensure_verified_role(guild)
        if target_role is None:
            await interaction.response.send_message("ロールを作成/参照できません。Botの権限とロール位置を確認してください。", ephemeral=True)
            return

    if target_role.managed:
        await interaction.response.send_message("このロールはシステム管理ロールのため付与できません。別のロールを選んでください。", ephemeral=True)
        return
    if target_role.position >= me.top_role.position:
        await interaction.response.send_message("Botのロールより上位のため付与できません。ロール順を調整してください。", ephemeral=True)
        return

    embed = discord.Embed(
        title="認証",
        description=f"```\n{description_text}\n```",
        color=0x57F287
    )
    embed.set_image(url="https://images.unsplash.com/photo-1500530855697-b586d89ba3ee?auto=format&fit=crop&w=900&q=80")
    embed.set_footer(text=f"ボタンを押すと「{target_role.name}」ロールが付与されます。")
    view = VerificationView(target_role.id)
    bot.add_view(view)  # 永続ビューとして登録
    persist_verify_role_id(target_role.id)
    await target_channel.send(embed=embed, view=view)
    await interaction.response.send_message(f"{target_channel.mention} に認証ボタンを設置しました。付与ロール: `{target_role.name}`", ephemeral=True)


@bot.tree.command(name='set_paypay_channel', description='PayPayギフト確認用チャンネルを設定します（購入者のリンクが届く先・サーバー所有者のみ）')
@app_commands.describe(channel='管理者がギフトリンクを確認するテキストチャンネル')
async def set_paypay_channel_slash(interaction: discord.Interaction, channel: discord.TextChannel):
    guild = interaction.guild
    if not guild:
        await interaction.response.send_message("サーバー内でのみ使用できます。", ephemeral=True)
        return
    if interaction.user.id != guild.owner_id:
        await interaction.response.send_message("このコマンドはサーバー所有者のみ実行できます。", ephemeral=True)
        return

    me = guild.me
    if not channel.permissions_for(me).send_messages or not channel.permissions_for(me).embed_links:
        await interaction.response.send_message("そのチャンネルに Bot がメッセージ・埋め込みを送信できません。権限を確認してください。", ephemeral=True)
        return

    persist_paypay_notify_channel(guild.id, channel.id)
    await interaction.response.send_message(
        f"PayPay ギフト確認チャンネルを {channel.mention} に設定しました。`/post_product` の「購入する」から届くリンクはここに表示されます。",
        ephemeral=True,
    )


@bot.tree.command(name='post_product', description='商品カードを投稿します（所有者のみ）')
@app_commands.describe(
    title='商品名/見出し',
    body='説明文',
    price='価格テキスト (例: 1200円)',
    stock_text='在庫情報 (例: 在庫あり/残り3など)',
    buy_url='商品のダウンロードURL（省略可・管理者通知とDL送付モーダルの初期値に使います）',
    options='購入時に選択させる商品リスト（改行区切り）',
    image_url='画像URL (省略可)',
    channel='投稿先チャンネル (省略可)',
)
async def post_product_slash(
    interaction: discord.Interaction,
    title: str,
    body: str,
    price: str,
    stock_text: str,
    buy_url: str = None,
    options: str = None,
    image_url: str = None,
    channel: discord.TextChannel = None,
):
    guild = interaction.guild
    if not guild:
        await interaction.response.send_message("サーバー内でのみ使用できます。", ephemeral=True)
        return
    if interaction.user.id != guild.owner_id:
        await interaction.response.send_message("このコマンドはサーバー所有者のみ実行できます。", ephemeral=True)
        return

    target_channel = channel or interaction.channel
    me = guild.me
    if not target_channel.permissions_for(me).send_messages:
        await interaction.response.send_message("指定チャンネルでメッセージを送信できません。Botの権限を確認してください。", ephemeral=True)
        return

    product_id = str(int(datetime.datetime.now().timestamp() * 1000))
    option_list = [opt.strip() for opt in (options.splitlines() if options else []) if opt.strip()]
    if not option_list:
        option_list = [title]

    embed = discord.Embed(title=title, description=body, color=0x2b2d31)
    embed.add_field(name="料金", value=f"```\n{price}\n```", inline=False)
    # Remove download URL from public display - will be sent via DM after purchase
    if image_url:
        embed.set_image(url=image_url)
    embed.set_footer(text="Developer @pri_m123")

    view = ProductView(product_id, stock_text, title, option_list, buy_url.strip() if buy_url else None)
    bot.add_view(view)
    persist_product_config(
        product_id,
        {"stock_text": stock_text, "title": title, "options": option_list, "buy_url": buy_url.strip() if buy_url else None},
    )
    await target_channel.send(embed=embed, view=view)
    await interaction.response.send_message(f"{target_channel.mention} に商品カードを投稿しました。", ephemeral=True)


@bot.tree.command(name='remind', description='リマインダーを設定します')
async def remind_slash(interaction: discord.Interaction, minutes: int, message: str):
    await interaction.response.send_message(f'⏰ {minutes}分後に「{message}」をお知らせします！')
    await asyncio.sleep(minutes * 60)
    await interaction.channel.send(f'🔔 {interaction.user.mention} 時間です: **{message}**')

@bot.tree.command(name='poll', description='投票を作成します')
async def poll_slash(interaction: discord.Interaction, title: str, choices: str):
    choice_list = choices.split()
    if len(choice_list) < 2:
        await interaction.response.send_message("❌ 選択肢を2つ以上指定してください（スペース区切り）。", ephemeral=True)
        return
    emojis = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
    desc = "\n".join(f"{emojis[i]} {c}" for i, c in enumerate(choice_list[:10]))
    embed = discord.Embed(title=f"📊 {title}", description=desc, color=discord.Color.blue())
    await interaction.response.send_message(embed=embed)
    msg = await interaction.original_response()
    for i in range(len(choice_list[:10])): await msg.add_reaction(emojis[i])

@bot.tree.command(name='clear', description='メッセージ削除')
@app_commands.checks.has_permissions(manage_messages=True)
async def clear_slash(interaction: discord.Interaction, amount: int = 5):
    await interaction.response.defer(ephemeral=True)
    await interaction.channel.purge(limit=amount)
    await interaction.followup.send(f'🧹 {amount}件削除しました。', ephemeral=True)

@bot.tree.command(name='clear_all', description='チャンネルの全メッセージを削除します（TOP ADMINロールのみ）')
@app_commands.describe(channel='削除対象チャンネル（省略時は現在のチャンネル）')
async def clear_all_slash(interaction: discord.Interaction, channel: discord.TextChannel = None):
    guild = interaction.guild
    if not guild:
        await interaction.response.send_message("サーバー内でのみ使用できます。", ephemeral=True)
        return
    
    # TOP ADMINロールの確認
    member = guild.get_member(interaction.user.id)
    if not member:
        await interaction.response.send_message("ユーザー情報が見つかりません。", ephemeral=True)
        return
    
    top_admin_role = None
    for role in member.roles:
        if role.name.upper() == "TOP ADMIN":
            top_admin_role = role
            break
    
    if not top_admin_role:
        await interaction.response.send_message("このコマンドはTOP ADMINロールのみ実行できます。", ephemeral=True)
        return
    
    target_channel = channel or interaction.channel
    me = guild.me
    
    # 権限確認
    if not target_channel.permissions_for(me).manage_messages:
        await interaction.response.send_message(f"{target_channel.mention} でメッセージを管理する権限がありません。", ephemeral=True)
        return
    
    if not target_channel.permissions_for(me).read_message_history:
        await interaction.response.send_message(f"{target_channel.mention} のメッセージ履歴を読む権限がありません。", ephemeral=True)
        return
    
    await interaction.response.send_message(f"{target_channel.mention} のメッセージを全削除中です...", ephemeral=True)
    
    try:
        deleted_count = 0
        async for message in target_channel.history(limit=None):
            try:
                await message.delete()
                deleted_count += 1
                # API制限を避けるために少し待機
                if deleted_count % 10 == 0:
                    await asyncio.sleep(1)
            except discord.Forbidden:
                continue  # 削除できないメッセージはスキップ
            except Exception as e:
                print(f"⚠️ メッセージ削除エラー: {e}")
                continue
        
        await interaction.followup.send(f"✅ {target_channel.mention} で {deleted_count}件のメッセージを削除しました。", ephemeral=True)
        
    except Exception as e:
        await interaction.followup.send(f"❌ 削除中にエラーが発生しました: {e}", ephemeral=True)


@bot.tree.command(name='say', description='ボットにメッセージを言わせます')
async def say_slash(interaction: discord.Interaction, text: str):
    try:
        await interaction.response.send_message("送信中...", ephemeral=True)
        await interaction.channel.send(text)
        await interaction.delete_original_response()
    except discord.Forbidden:
        await interaction.followup.send("❌ 権限がありません。", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"❌ エラー: {e}", ephemeral=True)

# ===== Web認証サーバー =====

from flask import Flask, request, jsonify, redirect
import threading
import requests
import secrets

# Flaskアプリケーション
app = Flask(__name__)


@app.route('/')
def health_check():
    return "PRIM BOT API: Online", 200

# Discord OAuth2設定
DISCORD_CLIENT_ID = os.getenv('DISCORD_CLIENT_ID', '')
DISCORD_CLIENT_SECRET = os.getenv('DISCORD_CLIENT_SECRET', '')
DISCORD_REDIRECT_URI = os.getenv('DISCORD_REDIRECT_URI', 'https://prim-store.pages.dev/callback.html')

@app.route('/api/config')
def get_config():
    """Discord OAuth2設定を返す"""
    return jsonify({
        "discordClientId": DISCORD_CLIENT_ID
    })

@app.route('/api/auth/exchange', methods=['POST'])
def exchange_code():
    """認証コードをアクセストークンと交換"""
    try:
        data = request.get_json(silent=True) or {}
        code = data.get('code')
        
        if not code:
            return jsonify({'success': False, 'error': '認証コードがありません'})
        
        # Discordにトークン交換リクエスト
        token_url = 'https://discord.com/api/oauth2/token'
        token_data = {
            'client_id': DISCORD_CLIENT_ID,
            'client_secret': DISCORD_CLIENT_SECRET,
            'grant_type': 'authorization_code',
            'code': code,
            'redirect_uri': DISCORD_REDIRECT_URI
        }
        
        headers = {'Content-Type': 'application/x-www-form-urlencoded'}
        token_response = requests.post(token_url, data=token_data, headers=headers, timeout=15)
        
        if token_response.status_code != 200:
            return jsonify({'success': False, 'error': 'トークン交換に失敗しました'})
        
        token_info = token_response.json()
        access_token = token_info.get('access_token')
        
        # ユーザー情報取得
        user_url = 'https://discord.com/api/users/@me'
        user_headers = {'Authorization': f'Bearer {access_token}'}
        user_response = requests.get(user_url, headers=user_headers, timeout=15)
        
        if user_response.status_code != 200:
            return jsonify({'success': False, 'error': 'ユーザー情報取得に失敗しました'})
        
        user_data = user_response.json()
        
        return jsonify({
            'success': True,
            'user': user_data,
            'access_token': access_token
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/webhook-order', methods=['POST'])
def handle_webstore_order():
    """Webストアからの注文を受け取るエンドポイント"""
    try:
        data = request.get_json(silent=True) or {}
        order_id = secrets.token_hex(8)
        
        # Botのイベントループを使用してDiscordにメッセージを送る
        async def send_order_notice():
            # ギルドを取得 (最初のギルドまたはID指定)
            if not bot.guilds: return
            guild = bot.guilds[0] 
            
            # 通知チャンネル取得
            ch_id = get_paypay_notify_channel_id(guild.id)
            if not ch_id: return
            channel = bot.get_channel(ch_id)
            if not channel: return

            buyer_id = int(data.get('userId', 0))
            items = data.get('items', [])
            item_names = [f"{i['name']}{f' (Role: {i.get('roleId')})' if i.get('roleId') else ''}" for i in items]
            
            embed = discord.Embed(
                title="🛒 Webストア受注 (PayPay)",
                color=0x3B82F6,
                timestamp=datetime.datetime.now(datetime.timezone.utc)
            )
            embed.add_field(name="ユーザー", value=f"<@{buyer_id}> (`{buyer_id}`)", inline=False)
            embed.add_field(name="商品", value="\n".join(item_names), inline=False)
            embed.add_field(name="PayPayリンク", value=f"```{data.get('paypayLink')}```", inline=False)
            embed.set_footer(text=f"Order ID: {order_id}")

            view = AdminOrderView(order_id)
            msg = await channel.send(embed=embed, view=view)
            
            # 注文データを保存 (bot.py の既存の仕組みを利用)
            upsert_order(order_id, {
                "guild_id": guild.id,
                "channel_id": channel.id,
                "message_id": msg.id,
                "buyer_id": buyer_id,
                "product_title": "Web Store Order",
                "selected_option": ", ".join(item_names),
                "status": "pending",
                "buy_url": None
            })

        bot.loop.create_task(send_order_notice())
        return jsonify({'success': True, 'orderId': order_id})
    except Exception as e:
        print(f"API Error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

def start_auth_server():
    """認証サーバーを起動"""
    port = int(os.environ.get("PORT", 8000))
    try:
        from waitress import serve
        print(f"🌐 Web API (waitress) listening on 0.0.0.0:{port}")
        serve(app, host='0.0.0.0', port=port, threads=WAITRESS_THREADS)
    except Exception as e:
        print(f"⚠️ waitress起動に失敗。Flask開発サーバーへフォールバックします: {e}")
        app.run(host='0.0.0.0', port=port, threaded=True, use_reloader=False)

def start_auth_server_thread():
    """認証サーバーをバックグラウンド起動"""
    auth_server_thread = threading.Thread(target=start_auth_server, daemon=True)
    auth_server_thread.start()
    return auth_server_thread

# ===== Botの起動 =====

def run_bot_with_retry(token: str):
    attempt = 0
    while True:
        try:
            bot.run(token)
            return
        except KeyboardInterrupt:
            raise
        except discord.LoginFailure:
            print("❌ Discordログイン失敗: トークンが無効です。Renderの環境変数 DISCORD_TOKEN を再発行して設定してください。")
            raise
        except discord.PrivilegedIntentsRequired:
            print("❌ Privileged Intents が未有効です。Discord Developer Portal > Bot で")
            print("   MESSAGE CONTENT INTENT と SERVER MEMBERS INTENT をONにしてください。")
            print("   使わない場合は ENABLE_MESSAGE_CONTENT_INTENT=false / ENABLE_MEMBERS_INTENT=false で起動可能です。")
            raise
        except Exception as e:
            attempt += 1

            if STARTUP_RETRY_LIMIT > 0 and attempt >= STARTUP_RETRY_LIMIT:
                print(f"❌ 起動再試行の上限 ({STARTUP_RETRY_LIMIT}) に達しました: {e}")
                raise

            wait_seconds = min(STARTUP_RETRY_BASE_SECONDS * (2 ** (attempt - 1)), STARTUP_RETRY_MAX_SECONDS)
            print(f"⚠️ Bot起動エラー: {e}")
            print(f"⏳ {wait_seconds}秒待って再試行します ({attempt}回目)")
            time.sleep(wait_seconds)

if __name__ == '__main__':
    token_env_name, token, token_was_normalized = get_discord_token_from_env()
    if not token:
        print("DISCORD_TOKEN / DISCORD_TOKEN2 が未設定、または値が空です。.env または Render env vars を確認してください。")
    else:
        print(f"🔑 {token_env_name} を使用して起動します。")
        if token_was_normalized:
            print(f"ℹ️ {token_env_name} の前後空白/引用符を除去して使用します。")
        print(f"ℹ️ intents: message_content={ENABLE_MESSAGE_CONTENT_INTENT}, members={ENABLE_MEMBERS_INTENT}")
        start_auth_server_thread()
        run_bot_with_retry(token)
    if not token:
        print("DISCORD_TOKEN / DISCORD_TOKEN2 が設定されていません。.env または Render env vars を確認してください。")
    else:
        start_auth_server_thread()
        run_bot_with_retry(token)
