import discord
from discord.ext import commands
import sqlite3
import datetime
import io
import os
import re
from flask import Flask
from threading import Thread

TOKEN = os.getenv("TOKEN")
ADMIN_ROLE = "Deadly"
HR_ROLE = "HR"
BANK_ROLE = "Доступ к Банку"
DIS_ROLE = "Dis"
PREFIX = "!"

conn = sqlite3.connect('gta_rp.db')
c = conn.cursor()

c.execute('''CREATE TABLE IF NOT EXISTS family_members (
    nickname TEXT PRIMARY KEY,
    discord_id INTEGER UNIQUE,
    joined_at TEXT
)''')

c.execute('''CREATE TABLE IF NOT EXISTS vehicles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_nick TEXT,
    model TEXT,
    plate TEXT UNIQUE,
    status TEXT DEFAULT 'свободен',
    taken_by TEXT,
    taken_at TEXT,
    return_at TEXT
)''')

c.execute('''CREATE TABLE IF NOT EXISTS warehouse (
    item TEXT PRIMARY KEY,
    amount INTEGER CHECK(amount >= 0)
)''')

c.execute('''CREATE TABLE IF NOT EXISTS bank (
    balance INTEGER DEFAULT 0
)''')
c.execute("INSERT INTO bank (balance) SELECT 0 WHERE NOT EXISTS (SELECT 1 FROM bank)")

c.execute('''CREATE TABLE IF NOT EXISTS contracts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT,
    participants TEXT,
    due_date TEXT,
    bills INTEGER DEFAULT 0,
    created_by TEXT,
    created_at TEXT
)''')

c.execute('''CREATE TABLE IF NOT EXISTS disciplinary_actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nickname TEXT,
    discord_id INTEGER,
    action_type TEXT,
    reason TEXT,
    issued_by TEXT,
    date TEXT
)''')

# Миграции старых таблиц
try:
    c.execute("ALTER TABLE family_members ADD COLUMN discord_id INTEGER")
except:
    pass
try:
    c.execute("ALTER TABLE disciplinary_actions ADD COLUMN discord_id INTEGER")
except:
    pass
try:
    c.execute("ALTER TABLE contracts ADD COLUMN bills INTEGER DEFAULT 0")
except:
    pass

conn.commit()

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix=PREFIX, intents=intents, help_command=None)

def has_admin(ctx):
    return any(r.name == ADMIN_ROLE for r in ctx.author.roles)

def has_hr(ctx):
    return any(r.name in (HR_ROLE, ADMIN_ROLE) for r in ctx.author.roles)

def has_bank_access(ctx):
    return any(r.name in (BANK_ROLE, ADMIN_ROLE) for r in ctx.author.roles)

def has_dis_access(ctx):
    return any(r.name in (DIS_ROLE, ADMIN_ROLE) for r in ctx.author.roles)

def is_in_family(ctx):
    if has_hr(ctx):
        return True
    c.execute("SELECT 1 FROM family_members WHERE discord_id=?", (ctx.author.id,))
    return c.fetchone() is not None

def get_member_nick(user_id):
    c.execute("SELECT nickname FROM family_members WHERE discord_id=?", (user_id,))
    row = c.fetchone()
    return row[0] if row else None

def get_family_balance():
    c.execute("SELECT balance FROM bank LIMIT 1")
    return c.fetchone()[0]

def auto_return():
    now = datetime.datetime.now().isoformat()
    c.execute("UPDATE vehicles SET status='свободен', taken_by=NULL, taken_at=NULL, return_at=NULL WHERE status='занят' AND return_at <= ?", (now,))
    conn.commit()

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CheckFailure):
        await ctx.send("❌ Недостаточно прав.")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"❌ Пропущен аргумент. Используйте `!помощь`.")
    elif isinstance(error, commands.BadArgument):
        await ctx.send(f"❌ Неверный аргумент: {error}")
    else:
        await ctx.send(f"❌ Ошибка: {str(error)}")

@bot.command(name="id")
async def get_id(ctx, member: discord.Member = None):
    m = member or ctx.author
    await ctx.send(f'🆔 {m.mention}: `{m.id}`')

@bot.command(name="добавсемья", aliases=["добавить-в-семью"])
@commands.check(has_hr)
async def add_family(ctx, discord_id: int, *, nickname: str):
    nickname = nickname.replace("_", " ")
    c.execute("SELECT * FROM family_members WHERE discord_id=?", (discord_id,))
    if c.fetchone():
        return await ctx.send(f'⚠️ Пользователь с ID `{discord_id}` уже в семье.')
    c.execute("SELECT * FROM family_members WHERE nickname=?", (nickname,))
    if c.fetchone():
        return await ctx.send(f'⚠️ Ник `{nickname}` уже занят.')
    c.execute("INSERT INTO family_members (nickname, discord_id, joined_at) VALUES (?, ?, ?)",
              (nickname, discord_id, datetime.datetime.now().isoformat()))
    conn.commit()
    await ctx.send(f'✅ <@{discord_id}> (`{nickname}`) добавлен в семью.')

@bot.command(name="удалсемья", aliases=["удалить-из-семьи"])
@commands.check(has_hr)
async def remove_family(ctx, discord_id: int):
    c.execute("SELECT nickname FROM family_members WHERE discord_id=?", (discord_id,))
    row = c.fetchone()
    if not row:
        return await ctx.send(f'❌ Пользователь с ID `{discord_id}` не найден в семье.')
    nickname = row[0]
    c.execute("DELETE FROM family_members WHERE discord_id=?", (discord_id,))
    conn.commit()
    await ctx.send(f'✅ <@{discord_id}> (`{nickname}`) удалён из семьи.')

@bot.command(name="семья")
@commands.check(is_in_family)
async def family_list(ctx):
    c.execute("SELECT nickname, discord_id FROM family_members")
    rows = c.fetchall()
    if not rows:
        return await ctx.send('👪 Семья пуста.')
    lines = [f'<@{disc_id}> — `{nick}`' for nick, disc_id in rows]
    embed = discord.Embed(title='👥 Семья', description='\n'.join(lines), color=0x00ff00)
    await ctx.send(embed=embed)

@bot.command(name="добававто")
@commands.check(has_admin)
async def add_car(ctx, model: str, plate: str):
    nick = get_member_nick(ctx.author.id)
    if not nick:
        return await ctx.send('❌ Вы не в семье.')
    nick = nick.replace("_", " ")
    try:
        c.execute("INSERT INTO vehicles (owner_nick, model, plate) VALUES (?, ?, ?)", (nick, model, plate))
        conn.commit()
        car_id = c.lastrowid
        await ctx.send(f'🚗 {model} ({plate}) добавлен, номер {car_id}. Владелец: `{nick}`.')
    except sqlite3.IntegrityError:
        await ctx.send(f'❌ Госномер `{plate}` уже существует.')

@bot.command(name="удалавто")
@commands.check(has_admin)
async def remove_car(ctx, plate: str):
    c.execute("DELETE FROM vehicles WHERE plate=?", (plate,))
    if c.rowcount == 0:
        return await ctx.send(f'❌ Машина с госномером `{plate}` не найдена.')
    conn.commit()
    await ctx.send(f'🗑️ Машина `{plate}` удалена.')

@bot.command(name="авто")
@commands.check(is_in_family)
async def car_list(ctx):
    auto_return()
    c.execute("SELECT id, owner_nick, model, plate, status, taken_by, return_at FROM vehicles")
    cars = c.fetchall()
    if not cars:
        return await ctx.send('🚫 Нет машин.')
    lines = []
    for cid, owner, model, plate, status, taken_by, ret_at in cars:
        if status == 'свободен':
            lines.append(f'`{cid}` {model} ({plate}) — свободен')
        else:
            lines.append(f'`{cid}` {model} ({plate}) — занят {taken_by}, до {ret_at}')
    embed = discord.Embed(title='🚗 Автомобили', description='\n'.join(lines), color=0x3498db)
    await ctx.send(embed=embed)

@bot.command(name="взятьавто")
@commands.check(has_admin)
async def take_car(ctx, car_id: int, hours: float = 2.0):
    nick = get_member_nick(ctx.author.id)
    if not nick:
        return await ctx.send('❌ Вы не в семье.')
    nick = nick.replace("_", " ")
    auto_return()
    c.execute("SELECT status, plate FROM vehicles WHERE id=?", (car_id,))
    car = c.fetchone()
    if not car:
        return await ctx.send(f'❌ Авто с номером `{car_id}` не найдено.')
    status, plate = car
    if status != 'свободен':
        return await ctx.send(f'❌ Авто `{plate}` уже занято.')
    now = datetime.datetime.now()
    return_at = now + datetime.timedelta(hours=hours)
    c.execute("UPDATE vehicles SET status='занят', taken_by=?, taken_at=?, return_at=? WHERE id=?",
              (nick, now.isoformat(), return_at.isoformat(), car_id))
    conn.commit()
    await ctx.send(f'✅ `{plate}` выдано `{nick}` на {hours} ч до {return_at.strftime("%d.%m.%Y %H:%M")}.')

@bot.command(name="вернутьавто")
@commands.check(has_admin)
async def return_car(ctx, car_id: int):
    c.execute("SELECT plate, status FROM vehicles WHERE id=?", (car_id,))
    car = c.fetchone()
    if not car:
        return await ctx.send(f'❌ Авто с номером `{car_id}` не найдено.')
    plate, status = car
    if status == 'свободен':
        return await ctx.send(f'❌ Авто `{plate}` уже свободно.')
    c.execute("UPDATE vehicles SET status='свободен', taken_by=NULL, taken_at=NULL, return_at=NULL WHERE id=?", (car_id,))
    conn.commit()
    await ctx.send(f'✅ Авто `{plate}` возвращено.')

@bot.command(name="склад")
@commands.check(is_in_family)
async def warehouse_info(ctx):
    c.execute("SELECT item, amount FROM warehouse WHERE amount > 0")
    items = c.fetchall()
    if not items:
        return await ctx.send('📦 Склад пуст.')
    desc = '\n'.join(f'• {item}: {amount} шт.' for item, amount in items)
    embed = discord.Embed(title='📦 Склад', description=desc, color=0x00ff00)
    await ctx.send(embed=embed)

@bot.command(name="взятьсклад")
@commands.check(has_admin)
async def take_warehouse(ctx, item: str, amount: int):
    nick = get_member_nick(ctx.author.id)
    if not nick:
        return await ctx.send('❌ Вы не в семье.')
    nick = nick.replace("_", " ")
    if amount <= 0:
        return await ctx.send('❌ Количество > 0.')
    c.execute("SELECT amount FROM warehouse WHERE item=?", (item,))
    row = c.fetchone()
    if not row or row[0] < amount:
        return await ctx.send(f'❌ Недостаточно `{item}` на складе.')
    c.execute("UPDATE warehouse SET amount = amount - ? WHERE item=?", (amount, item))
    conn.commit()
    await ctx.send(f'✅ `{nick}` забрал {amount} x {item} со склада.')

@bot.command(name="положитьсклад")
@commands.check(has_admin)
async def put_warehouse(ctx, item: str, amount: int):
    nick = get_member_nick(ctx.author.id)
    if not nick:
        return await ctx.send('❌ Вы не в семье.')
    nick = nick.replace("_", " ")
    if amount <= 0:
        return await ctx.send('❌ Количество > 0.')
    c.execute("INSERT INTO warehouse (item, amount) VALUES (?, ?) ON CONFLICT(item) DO UPDATE SET amount = amount + ?",
              (item, amount, amount))
    conn.commit()
    await ctx.send(f'✅ `{nick}` положил {amount} x {item} на склад.')

@bot.command(name="банк")
@commands.check(is_in_family)
async def bank_balance(ctx):
    balance = get_family_balance()
    await ctx.send(f'💰 Баланс семьи: {balance}')

@bot.command(name="пополнить")
@commands.check(is_in_family)
async def bank_add(ctx, amount: int, *, reason: str = ""):
    if amount <= 0:
        return await ctx.send('❌ Сумма должна быть положительной.')
    nick = get_member_nick(ctx.author.id)
    if not nick:
        return await ctx.send('❌ Вы не привязаны к семье. Используйте !добавсемья.')
    nick = nick.replace("_", " ")
    c.execute("UPDATE bank SET balance = balance + ?", (amount,))
    conn.commit()
    new_balance = get_family_balance()
    files = []
    for att in ctx.message.attachments:
        if att.content_type and att.content_type.startswith("image/"):
            img_bytes = await att.read()
            new_name = att.filename.replace("_", "-")
            files.append(discord.File(fp=io.BytesIO(img_bytes), filename=new_name))
    msg = f'💰 Счёт семьи пополнен на {amount} (от {nick}).'
    if reason:
        msg += f' Причина: {reason}.'
    msg += f' Баланс: {new_balance}.'
    await ctx.send(msg, files=files if files else None)

@bot.command(name="снять")
@commands.check(has_bank_access)
async def bank_remove(ctx, amount: int, *, reason: str = ""):
    if amount <= 0:
        return await ctx.send('❌ Сумма должна быть положительной.')
    nick = get_member_nick(ctx.author.id)
    if not nick:
        return await ctx.send('❌ Вы не привязаны к семье.')
    nick = nick.replace("_", " ")
    balance = get_family_balance()
    if balance < amount:
        return await ctx.send(f'❌ Недостаточно средств. Баланс: {balance}.')
    c.execute("UPDATE bank SET balance = balance - ?", (amount,))
    conn.commit()
    new_balance = get_family_balance()
    files = []
    for att in ctx.message.attachments:
        if att.content_type and att.content_type.startswith("image/"):
            img_bytes = await att.read()
            new_name = att.filename.replace("_", "-")
            files.append(discord.File(fp=io.BytesIO(img_bytes), filename=new_name))
    msg = f'💸 Из бюджета семьи снято {amount} (от {nick}).'
    if reason:
        msg += f' Причина: {reason}.'
    msg += f' Баланс: {new_balance}.'
    await ctx.send(msg, files=files if files else None)

@bot.command(name="контракт")
@commands.check(has_admin)
async def contract(ctx, title: str, *, args: str = ""):
    if not args.strip():
        return await ctx.send('ℹ️ Использование: `!контракт "Название" Участник1 Участник2 ... ДД.ММ.ГГГГ ЧЧ:ММ [векселя]`')
    parts = args.split()
    if len(parts) < 2:
        return await ctx.send('❌ Укажите дату (ДД.ММ.ГГГГ) и время (ЧЧ:ММ).')
    bills = 0
    if parts[-1].isdigit():
        bills = int(parts[-1])
        parts = parts[:-1]
    if len(parts) < 2:
        return await ctx.send('❌ Нужна дата и время.')
    time_str = parts[-1]
    date_str = parts[-2]
    if not re.match(r'\d{2}\.\d{2}\.\d{4}', date_str) or not re.match(r'\d{2}:\d{2}', time_str):
        return await ctx.send('❌ Неверный формат даты/времени. Ожидается ДД.ММ.ГГГГ ЧЧ:ММ.')
    participants = ' '.join(parts[:-2])
    due_date = f"{date_str} {time_str}"
    parts_list = participants.split()
    participants_db = ', '.join(parts_list)
    c.execute("INSERT INTO contracts (title, participants, due_date, bills, created_by, created_at) VALUES (?,?,?,?,?,?)",
              (title, participants_db, due_date, bills, str(ctx.author), datetime.datetime.now().isoformat()))
    conn.commit()
    await ctx.send(f'📝 Контракт "{title}" создан.\nУчастники: {participants_db}\nСрок: {due_date}\nВекселей: {bills}')

@bot.command(name="дв")
@commands.check(has_dis_access)
async def dv_add(ctx, nickname: str, action_type: str, *, reason: str):
    action_type = action_type.lower()
    allowed = ["предупреждение", "выговор", "2выговора", "warn", "увал"]
    if action_type not in allowed:
        return await ctx.send(f'❌ Неверный тип. Допустимые: {", ".join(allowed)}')
    nickname = nickname.replace("_", " ")
    c.execute("SELECT discord_id FROM family_members WHERE nickname=?", (nickname,))
    row = c.fetchone()
    discord_id = row[0] if row else None
    c.execute("INSERT INTO disciplinary_actions (nickname, discord_id, action_type, reason, issued_by, date) VALUES (?,?,?,?,?,?)",
              (nickname, discord_id, action_type, reason, str(ctx.author), datetime.datetime.now().isoformat()))
    conn.commit()
    mention = f'<@{discord_id}>' if discord_id else nickname
    await ctx.send(f'⚠️ {mention} получил **{action_type}**.\nПричина: {reason}')

@bot.command(name="выговоры")
@commands.check(is_in_family)
async def dv_list(ctx, nickname: str = None):
    if nickname:
        nickname = nickname.replace("_", " ")
    else:
        nickname = get_member_nick(ctx.author.id)
        if not nickname:
            return await ctx.send('❌ Укажите ник или будьте в семье.')
    c.execute("SELECT action_type, reason, issued_by, date FROM disciplinary_actions WHERE nickname=? ORDER BY date DESC", (nickname,))
    rows = c.fetchall()
    if not rows:
        return await ctx.send(f'✅ У `{nickname}` нет выговоров.')
    lines = [f'**{t}** — {r} (от {i}, {d})' for t, r, i, d in rows]
    embed = discord.Embed(title=f'📋 Выговоры: {nickname}', description='\n'.join(lines), color=0xff0000)
    await ctx.send(embed=embed)

@bot.command(name="снятьдв")
@commands.check(has_dis_access)
async def dv_remove(ctx, nickname: str, *, reason: str):
    nickname = nickname.replace("_", " ")
    c.execute("DELETE FROM disciplinary_actions WHERE id = (SELECT id FROM disciplinary_actions WHERE nickname=? ORDER BY date DESC LIMIT 1)", (nickname,))
    if c.rowcount == 0:
        return await ctx.send(f'❌ У `{nickname}` нет выговоров.')
    conn.commit()
    c.execute("SELECT discord_id FROM family_members WHERE nickname=?", (nickname,))
    row = c.fetchone()
    disc_id = row[0] if row else None
    mention = f'<@{disc_id}>' if disc_id else nickname
    await ctx.send(f'✅ Снят последний выговор с {mention}.\nПричина: {reason}')

@bot.command(name="помощь", aliases=["хелп"])
async def help_cmd(ctx):
    embed = discord.Embed(title="Помощь", color=0x00ff00)
    embed.add_field(name="👥 Семья", value="`!добавсемья ID Ник`\n`!удалсемья ID`\n`!семья`\n`!id @user`", inline=False)
    embed.add_field(name="🚗 Авто", value="`!добававто Модель Госномер`\n`!удалавто Госномер`\n`!авто`\n`!взятьавто Номер [часы]`\n`!вернутьавто Номер`", inline=False)
    embed.add_field(name="📦 Склад", value="`!склад`\n`!взятьсклад Предмет Кол-во`\n`!положитьсклад Предмет Кол-во`", inline=False)
    embed.add_field(name="💰 Банк", value="`!банк` — баланс семьи\n`!пополнить Сумма [Причина]` — любой член семьи\n`!снять Сумма [Причина]` — требуется роль «Доступ к Банку»", inline=False)
    embed.add_field(name="📝 Контракты", value="`!контракт \"Название\" Участник1 Участник2 ... ДД.ММ.ГГГГ ЧЧ:ММ [векселя]`", inline=False)
    embed.add_field(name="⚠️ Дисциплина", value="`!дв Ник Тип Причина`\n`!выговоры [ник]`\n`!снятьдв Ник Причина`", inline=False)
    await ctx.send(embed=embed)

@bot.event
async def on_command_completion(ctx):
    try:
        await ctx.message.delete()
    except:
        pass

app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is alive!"

def run_web():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

Thread(target=run_web).start()

bot.run(TOKEN)
