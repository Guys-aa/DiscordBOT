import discord
from discord.ext import commands
from discord import app_commands
import random
import asyncio
import datetime
import hashlib
import json
import aiohttp
import os
import io
import base64
import socket
import ssl
import re
import qrcode
import matplotlib.pyplot as plt
import yfinance as yf
import dns.resolver
from gtts import gTTS
from textblob import TextBlob
from openai import OpenAI
import numpy as np # Added for graph command
from dotenv import load_dotenv

load_dotenv()

# ===== Bot & API 設定 =====

# GitHub Models API 設定
# GPT-4o mini 用のトークン (複数ある場合はカンマ区切りで .env に記述)
GPT4O_MINI_KEYS = os.getenv("GPT4O_MINI_KEYS", "").split(",")
# DeepSeek 用のトークン
DEEPSEEK_KEYS = os.getenv("DEEPSEEK_KEYS", "").split(",")

# キーのローテーション用インデックス
key_indexes = {"gpt-4o-mini": 0, "deepseek": 0}

# 会話履歴を保持する辞書 {user_id: [messages]}
user_histories = {}
MAX_HISTORY = 10 # 保存する直近のメッセージ数

def get_ai_client(model_type):
    global key_indexes
    keys = GPT4O_MINI_KEYS if model_type == "gpt-4o-mini" else DEEPSEEK_KEYS
    # キーが空の場合のガード
    if not keys or (len(keys) == 1 and keys[0] == ""):
        raise ValueError(f"APIキーが設定されていません: {model_type}")
        
    idx = key_indexes[model_type] % len(keys)
    key_indexes[model_type] += 1
    return OpenAI(
        base_url="https://models.inference.ai.azure.com",
        api_key=keys[idx]
    )

# Botの設定
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

# プレフィックスコマンドとスラッシュコマンドの両方を使用
bot = commands.Bot(command_prefix='!', intents=intents, help_command=None)


@bot.event
async def on_ready():
    """Botが起動したときに呼ばれるイベント"""
    print(f'✅ ログイン: {bot.user.name}')
    print(f'🆔 Bot ID: {bot.user.id}')
    print(f'📡 接続サーバー数: {len(bot.guilds)}')
    
    # スラッシュコマンドを同期 (重複解消バージョン)
    try:
        # 1. すべてのギルド（サーバー）から固有のコマンド設定を消去
        for guild in bot.guilds:
            bot.tree.clear_commands(guild=guild)
            await bot.tree.sync(guild=guild)
        
        # 2. グローバルコマンドとして一括同期
        await bot.tree.sync()
        print(f'🔄 コマンドをグローバル同期しました。重複は解消されます。')
    except Exception as e:
        print(f'❌ コマンド同期エラー: {e}')
    print('------')


@bot.event
async def on_message(message):
    if message.author == bot.user:
        return
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
        description="GitHub Models (GPT-4o/DeepSeek) 搭載の最新鋭ボットです。",
        color=0x2b2d31
    )
    embed.add_field(name="🤖 AI & NLP", value="`/chat`, `/chat_clear`, `/translate`, `/sentiment`, `/tts` ", inline=False)
    embed.add_field(name="💻 Developers", value="`/code`, `/github`, `/mermaid`, `/json`, `/hash`, `/password_gen` ", inline=False)
    embed.add_field(name="🌐 Network", value="`/http`, `/dns`, `/scan`, `/ssl`, `/ipinfo` ", inline=False)
    embed.add_field(name="📊 Tools & Media", value="`/graph`, `/qr`, `/crypto`, `/stock`, `/calc` ", inline=False)
    embed.add_field(name="🛠️ Utility", value="`/remind`, `/poll`, `/clear`, `/say` ", inline=False)
    embed.add_field(name="🎉 Fun", value="`/dice`, `/omikuji`, `/avatar`, `/ping` ", inline=False)
    embed.set_footer(text="すべてのコマンドはスラッシュコマンド '/' で利用可能です。")
    
    if isinstance(interaction, discord.Interaction):
        await interaction.response.send_message(embed=embed)
    else:
        await interaction.send(embed=embed)

@bot.command(name='help')
async def help_ctx(ctx): await send_help(ctx)

@bot.tree.command(name='help', description='すべての高度なコマンドを表示します')
async def help_slash(interaction: discord.Interaction): await send_help(interaction)


# ===== 🤖 AI & 自然言語処理 (NLP) =====

@bot.tree.command(name='chat', description='AI (GitHub Models) と会話します')
@app_commands.describe(model='使用するモデル', message='相談内容')
@app_commands.choices(model=[
    app_commands.Choice(name='GPT-4o mini (高速/万能)', value='gpt-4o-mini'),
    app_commands.Choice(name='DeepSeek (推論特化/思考表示あり)', value='deepseek'),
])
async def chat_slash(interaction: discord.Interaction, message: str, model: str = "gpt-4o-mini"):
    # 応答を保留にする（3秒ルール対策）
    try:
        if not interaction.response.is_done():
            await interaction.response.defer()
    except Exception:
        pass # すでにレスポンスが開始されている場合はスキップ
    
    user_id = str(interaction.user.id)
    if user_id not in user_histories:
        user_histories[user_id] = []
    
    # 履歴に現在のメッセージを追加
    user_histories[user_id].append({"role": "user", "content": message})
    
    # GitHub Models 上の実際のモデル名 ID を設定
    model_id = "gpt-4o-mini" if model == "gpt-4o-mini" else "DeepSeek-R1"
    
    try:
        client = get_ai_client(model)

        # 履歴を含めて送信
        response = client.chat.completions.create(
            messages=user_histories[user_id],
            model=model_id,
        )
        
        ai_message = response.choices[0].message.content
        
        # --- 推論モデルの <think> タグ（思考プロセス）の処理 ---
        raw_output = ai_message
        clean_text = re.sub(r'<think>.*?</think>', '', raw_output, flags=re.DOTALL).strip()
        
        # 履歴には生の出力を保存
        user_histories[user_id].append({"role": "assistant", "content": raw_output})
        
        # 履歴が長くなりすぎないように制限
        if len(user_histories[user_id]) > MAX_HISTORY * 2:
            user_histories[user_id] = user_histories[user_id][-(MAX_HISTORY * 2):]

        # 表示用のテキストを選択
        final_text = clean_text if clean_text else "回答を生成しましたが、内容が空です（思考のみが行われた可能性があります）。"

        if len(final_text) > 2000:
            file = io.BytesIO(final_text.encode('utf-8'))
            await interaction.followup.send(f"📄 **AI回答 ({model})** が長いためファイル出力しました：", file=discord.File(file, "response.txt"))
        else:
            await interaction.followup.send(f"🤖 **AI回答 ({model})**:\n{final_text}")
    except Exception as e:
        # エラーが発生した場合は履歴から最後の入力を削除
        if user_id in user_histories and user_histories[user_id]:
            user_histories[user_id].pop()
        await interaction.followup.send(f"❌ AIエラー: {e}")

@bot.tree.command(name='chat_clear', description='あなたとの会話の履歴をリセットします')
async def chat_clear_slash(interaction: discord.Interaction):
    user_id = str(interaction.user.id)
    if user_id in user_histories:
        user_histories[user_id] = []
        await interaction.response.send_message("🧹 会話の履歴をリセットしました！", ephemeral=True)
    else:
        await interaction.response.send_message("履歴はすでに空です。", ephemeral=True)

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

# ===== その他のコマンド =====

@bot.tree.command(name='ping', description='応答速度')
async def ping_slash(interaction: discord.Interaction):
    await interaction.response.send_message(f'🏓 Pong! {round(bot.latency * 1000)}ms')

@bot.tree.command(name='omikuji', description='運勢')
async def omikuji_slash(interaction: discord.Interaction):
    results = ["大吉 🌟", "吉 ✨", "中吉 👍", "小吉 🙂", "末吉 😐", "凶 💀", "大凶 👻"]
    await interaction.response.send_message(f'🧧 運勢... **【 {random.choice(results)} 】**')

@bot.tree.command(name='dice', description='サイコロ')
async def dice_slash(interaction: discord.Interaction, sides: int = 6):
    await interaction.response.send_message(f'🎲 結果: **{random.randint(1, sides)}** ({sides}面)')

@bot.tree.command(name='avatar', description='アバター')
async def avatar_slash(interaction: discord.Interaction, user: discord.User = None):
    user = user or interaction.user
    embed = discord.Embed(title=f'{user.display_name}', color=0x2b2d31)
    embed.set_image(url=user.display_avatar.url)
    await interaction.response.send_message(embed=embed)


# ===== Botの起動 =====

if __name__ == '__main__':
    token = os.getenv('DISCORD_TOKEN')
    if not token:
        print("❌ DISCORD_TOKEN が設定されていません。.env ファイルを確認してください。")
    else:
        bot.run(token)
