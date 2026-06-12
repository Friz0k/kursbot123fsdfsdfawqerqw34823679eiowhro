import discord
from discord.ext import commands
import sqlite3
import datetime
import io
import os
from flask import Flask
from threading import Thread

TOKEN = os.getenv("TOKEN")
ADMIN_ROLE_NAME = "Deadly"
HR_ROLE_NAME = "HR"
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
    nickname TEXT PRIMARY KEY,
    balance INTEGER DEFAULT 0
)''')

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
conn.commit()

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix=PREFIX, intents=intents, help_command=None)

def is_admin(ctx):
    return any(role.name == ADMIN_ROLE_NAME for role in ctx.author.roles)

def is_hr_or_admin(ctx):
    return any(role.name in (HR_ROLE_NAME, ADMIN_ROLE_NAME) for role in ctx.author.roles)

def in_family(ctx):
    if is_hr_or_admin(ctx):
        return True
    c.execute("SELECT * FROM family_members WHERE discord_id=?", (ctx.author.id,))
    return c.fetchone() is not None

def get_family_nickname(user_id):
    c.execute("SELECT nickname FROM family_members WHERE discord_id=?", (user_id,))
    row = c.fetchone()
    return row[0] if row else None

def get_player(nickname):
    c.execute("SELECT nickname FROM bank WHERE nickname=?", (nickname,))
    return c.fetchone() is not None

def ensure_player(nickname):
    if not get_player(nickname):
        c.execute("INSERT INTO bank (nickname, balance) VALUES (?, 0)", (nickname,))
        conn.commit()

def check_auto_return():
    now = datetime.datetime.now().isoformat()
    c.execute("UPDATE vehicles SET status='свободен', taken_by=NULL, taken_at=NULL, return_at=NULL WHERE status='занят' AND return_at <= ?", (now,))
    conn.commit()

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CheckFailure):
        await ctx.send("❌ У вас недостаточно прав для этой команды. Требуется роль HR или Deadly.")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"❌ Пропущен обязательный аргумент. Используйте `!помощь` для подсказки.")
    elif isinstance(error, commands.BadArgument):
        await ctx.send(f"❌ Ошибка в аргументе: {error}")
    else:
        await ctx.send(f"❌ Произошла ошибка: {str(error)}")

@bot.command(name="id")
async def get_id(ctx, member: discord.Member = None):
    if not member:
        member = ctx.author
    await ctx.send(f'🆔 Discord ID {member.mention}: `{member.id}`')

@bot.command(name="добавсемья", aliases=["добавить-в-семью", "добавить_в_семью"])
@commands.check(is_hr_or_admin)
async def add_family(ctx, discord_id: int, *, nickname: str):
    nickname = nickname.replace("_", " ")
    ensure_player(nickname)
    c.execute("SELECT * FROM family_members WHERE discord_id=?", (discord_id,))
    if c.fetchone():
        return await ctx.send(f'⚠️ Пользователь с ID `{discord_id}` уже в семье.')
    c.execute("SELECT * FROM family_members WHERE nickname=?", (nickname,))
    if c.fetchone():
        return await ctx.send(f'⚠️ Ник `{nickname}` уже закреплён за другим.')
    c.execute("INSERT INTO family_members (nickname, discord_id, joined_at) VALUES (?, ?, ?)",
              (nickname, discord_id, datetime.datetime.now().isoformat()))
    conn.commit()
    await ctx.send(f'✅ <@{discord_id}> (`{nickname}`) добавлен в семью. (Адм: {ctx.author.mention})')

@bot.command(name="удалсемья", aliases=["удалить-из-семьи", "удалить_из_семьи"])
@commands.check(is_hr_or_admin)
async def remove_family(ctx, discord_id: int):
    c.execute("SELECT nickname FROM family_members WHERE discord_id=?", (discord_id,))
    row = c.fetchone()
    if not row:
        return await ctx.send(f'❌ Пользователь с ID `{discord_id}` не в семье.')
    nickname = row[0]
    c.execute("DELETE FROM family_members WHERE discord_id=?", (discord_id,))
    conn.commit()
    await ctx.send(f'✅ <@{discord_id}> (`{nickname}`) удалён из семьи. (Адм: {ctx.author.mention})')

@bot.command(name="семья")
@commands.check(in_family)
async def family_list(ctx):
    c.execute("SELECT nickname, discord_id FROM family_members")
    rows = c.fetchall()
    if not rows:
        return await ctx.send('👪 Семья пуста.')
    lines = [f'<@{disc_id}> — `{nick}`' for nick, disc_id in rows]
    embed = discord.Embed(title='👥 Семья', description='\n'.join(lines), color=0x00ff00)
    await ctx.send(embed=embed)

@bot.command(name="добававто", aliases=["добавить-авто", "добавить_авто"])
@commands.check(is_admin)
async def add_car(ctx, nickname: str = None, model: str = None, plate: str = None):
    if model is None or plate is None:
        return await ctx.send('ℹ️ Использование: `!добававто [ник] модель госномер`. Без ника – ваш ник.')
    if nickname is None or nickname.lower() == "себе":
        nickname = get_family_nickname(ctx.author.id)
        if not nickname:
            return await ctx.send('❌ Вы не в семье. Укажите ник явно.')
    nickname = nickname.replace("_", " ")
    ensure_player(nickname)
    try:
        c.execute("INSERT INTO vehicles (owner_nick, model, plate) VALUES (?, ?, ?)",
                  (nickname, model, plate))
        conn.commit()
        car_id = c.lastrowid
        await ctx.send(f'🚗 {model} ({plate}) добавлен, номер {car_id}. Владелец: `{nickname}`. (Адм: {ctx.author.mention})')
    except sqlite3.IntegrityError:
        await ctx.send(f'❌ Машина с госномером `{plate}` уже существует.')

@bot.command(name="удалавто", aliases=["удалить-авто", "удалить_авто"])
@commands.check(is_admin)
async def remove_car(ctx, plate: str):
    c.execute("DELETE FROM vehicles WHERE plate=?", (plate,))
    if c.rowcount == 0:
        return await ctx.send(f'❌ Машина с госномером `{plate}` не найдена.')
    conn.commit()
    await ctx.send(f'🗑️ Машина с госномером `{plate}` удалена. (Адм: {ctx.author.mention})')

@bot.command(name="авто")
@commands.check(in_family)
async def car_info(ctx):
    check_auto_return()
    c.execute("SELECT id, owner_nick, model, plate, status, taken_by, return_at FROM vehicles")
    cars = c.fetchall()
    if not cars:
        return await ctx.send('🚫 Нет зарегистрированных авто.')
    lines = []
    for car_id, owner, model, plate, status, taken_by, ret_at in cars:
        if status == 'свободен':
            lines.append(f'`{car_id}` {model} ({plate}) — свободен')
        else:
            lines.append(f'`{car_id}` {model} ({plate}) — занят {taken_by}, до {ret_at}')
    embed = discord.Embed(title='🚗 Автомобили', description='\n'.join(lines), color=0x3498db)
    await ctx.send(embed=embed)

@bot.command(name="взятьавто", aliases=["взять-авто", "взять_авто"])
@commands.check(is_admin)
async def take_car(ctx, car_id: int, nickname: str = None, hours: float = 2.0):
    if nickname is None:
        nickname = get_family_nickname(ctx.author.id)
        if not nickname:
            return await ctx.send('❌ Укажите ник, т.к. вы не в семье.')
    nickname = nickname.replace("_", " ")
    check_auto_return()
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
              (nickname, now.isoformat(), return_at.isoformat(), car_id))
    conn.commit()
    await ctx.send(f'✅ Авто `{plate}` выдано `{nickname}` на {hours} ч до {return_at.strftime("%d.%m.%Y %H:%M")}. (Адм: {ctx.author.mention})')

@bot.command(name="вернутьавто", aliases=["вернуть-авто", "вернуть_авто"])
@commands.check(is_admin)
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
    await ctx.send(f'✅ Авто `{plate}` возвращено. (Адм: {ctx.author.mention})')

@bot.command(name="склад")
@commands.check(in_family)
async def warehouse_info(ctx):
    c.execute("SELECT item, amount FROM warehouse WHERE amount > 0")
    items = c.fetchall()
    if not items:
        return await ctx.send('📦 Склад пуст.')
    desc = '\n'.join(f'• {item}: {amount} шт.' for item, amount in items)
    embed = discord.Embed(title='📦 Склад', description=desc, color=0x00ff00)
    await ctx.send(embed=embed)

@bot.command(name="взятьсклад", aliases=["взять-со-склада", "взять_со_склада"])
@commands.check(is_admin)
async def take_from_warehouse(ctx, nickname: str = None, item: str = None, amount: int = None):
    if item is None or amount is None:
        return await ctx.send('ℹ️ Использование: `!взятьсклад [ник] предмет кол-во`. Без ника – ваш ник.')
    if nickname is None:
        nickname = get_family_nickname(ctx.author.id)
        if not nickname:
            return await ctx.send('❌ Вы не в семье. Укажите ник явно.')
    nickname = nickname.replace("_", " ")
    if amount <= 0:
        return await ctx.send('❌ Количество должно быть > 0.')
    ensure_player(nickname)
    c.execute("SELECT amount FROM warehouse WHERE item=?", (item,))
    row = c.fetchone()
    if not row or row[0] < amount:
        return await ctx.send(f'❌ Недостаточно `{item}` на складе.')
    c.execute("UPDATE warehouse SET amount = amount - ? WHERE item=?", (amount, item))
    conn.commit()
    await ctx.send(f'✅ `{nickname}` забрал {amount} x {item} со склада. (Адм: {ctx.author.mention})')

@bot.command(name="положитьсклад", aliases=["положить-на-склад", "положить_на_склад"])
@commands.check(is_admin)
async def put_to_warehouse(ctx, nickname: str = None, item: str = None, amount: int = None):
    if item is None or amount is None:
        return await ctx.send('ℹ️ Использование: `!положитьсклад [ник] предмет кол-во`. Без ника – ваш ник.')
    if nickname is None:
        nickname = get_family_nickname(ctx.author.id)
        if not nickname:
            return await ctx.send('❌ Вы не в семье. Укажите ник явно.')
    nickname = nickname.replace("_", " ")
    if amount <= 0:
        return await ctx.send('❌ Количество должно быть > 0.')
    ensure_player(nickname)
    c.execute("INSERT INTO warehouse (item, amount) VALUES (?, ?) ON CONFLICT(item) DO UPDATE SET amount = amount + ?",
              (item, amount, amount))
    conn.commit()
    await ctx.send(f'✅ `{nickname}` положил {amount} x {item} на склад. (Адм: {ctx.author.mention})')

@bot.command(name="пополнить", aliases=["банк-пополнить", "банк_пополнить"])
@commands.check(is_admin)
async def bank_add(ctx, amount: int, *, reason: str = "Без причины"):
    nickname = get_family_nickname(ctx.author.id)
    if not nickname:
        return await ctx.send('❌ Вы не в семье. Используйте !пополнить_ник {ник} {сумма} {причина}.')
    nickname = nickname.replace("_", " ")
    reason = reason.replace("_", " ")
    if amount <= 0:
        return await ctx.send('❌ Сумма должна быть положительной.')
    ensure_player(nickname)
    c.execute("UPDATE bank SET balance = balance + ? WHERE nickname=?", (amount, nickname))
    conn.commit()
    c.execute("SELECT balance FROM bank WHERE nickname=?", (nickname,))
    new_balance = c.fetchone()[0]
    files = []
    for att in ctx.message.attachments:
        if att.content_type and att.content_type.startswith("image/"):
            img_bytes = await att.read()
            new_filename = att.filename.replace("_", "-")
            files.append(discord.File(fp=io.BytesIO(img_bytes), filename=new_filename))
    msg = f'💰 Счёт `{nickname}` пополнен на {amount}. Причина: {reason}. Баланс: {new_balance}. (Адм: {ctx.author.mention})'
    await ctx.send(msg, files=files if files else None)

@bot.command(name="пополнить_ник")
@commands.check(is_admin)
async def bank_add_target(ctx, nickname: str, amount: int, *, reason: str = "Без причины"):
    nickname = nickname.replace("_", " ")
    reason = reason.replace("_", " ")
    if amount <= 0:
        return await ctx.send('❌ Сумма должна быть положительной.')
    ensure_player(nickname)
    c.execute("UPDATE bank SET balance = balance + ? WHERE nickname=?", (amount, nickname))
    conn.commit()
    c.execute("SELECT balance FROM bank WHERE nickname=?", (nickname,))
    new_balance = c.fetchone()[0]
    files = []
    for att in ctx.message.attachments:
        if att.content_type and att.content_type.startswith("image/"):
            img_bytes = await att.read()
            new_filename = att.filename.replace("_", "-")
            files.append(discord.File(fp=io.BytesIO(img_bytes), filename=new_filename))
    msg = f'💰 Счёт `{nickname}` пополнен на {amount}. Причина: {reason}. Баланс: {new_balance}. (Адм: {ctx.author.mention})'
    await ctx.send(msg, files=files if files else None)

@bot.command(name="снять", aliases=["банк-снять", "банк_снять"])
@commands.check(is_admin)
async def bank_remove(ctx, amount: int, *, reason: str = "Без причины"):
    nickname = get_family_nickname(ctx.author.id)
    if not nickname:
        return await ctx.send('❌ Вы не в семье. Используйте !снять_ник {ник} {сумма} {причина}.')
    nickname = nickname.replace("_", " ")
    reason = reason.replace("_", " ")
    if amount <= 0:
        return await ctx.send('❌ Сумма должна быть положительной.')
    ensure_player(nickname)
    c.execute("SELECT balance FROM bank WHERE nickname=?", (nickname,))
    balance = c.fetchone()[0]
    if balance < amount:
        return await ctx.send(f'❌ Недостаточно средств. Баланс: {balance}.')
    c.execute("UPDATE bank SET balance = balance - ? WHERE nickname=?", (amount, nickname))
    conn.commit()
    new_balance = balance - amount
    files = []
    for att in ctx.message.attachments:
        if att.content_type and att.content_type.startswith("image/"):
            img_bytes = await att.read()
            new_filename = att.filename.replace("_", "-")
            files.append(discord.File(fp=io.BytesIO(img_bytes), filename=new_filename))
    msg = f'💸 Со счета `{nickname}` снято {amount}. Причина: {reason}. Баланс: {new_balance}. (Адм: {ctx.author.mention})'
    await ctx.send(msg, files=files if files else None)

@bot.command(name="снять_ник")
@commands.check(is_admin)
async def bank_remove_target(ctx, nickname: str, amount: int, *, reason: str = "Без причины"):
    nickname = nickname.replace("_", " ")
    reason = reason.replace("_", " ")
    if amount <= 0:
        return await ctx.send('❌ Сумма должна быть положительной.')
    ensure_player(nickname)
    c.execute("SELECT balance FROM bank WHERE nickname=?", (nickname,))
    balance = c.fetchone()[0]
    if balance < amount:
        return await ctx.send(f'❌ Недостаточно средств. Баланс: {balance}.')
    c.execute("UPDATE bank SET balance = balance - ? WHERE nickname=?", (amount, nickname))
    conn.commit()
    new_balance = balance - amount
    files = []
    for att in ctx.message.attachments:
        if att.content_type and att.content_type.startswith("image/"):
            img_bytes = await att.read()
            new_filename = att.filename.replace("_", "-")
            files.append(discord.File(fp=io.BytesIO(img_bytes), filename=new_filename))
    msg = f'💸 Со счета `{nickname}` снято {amount}. Причина: {reason}. Баланс: {new_balance}. (Адм: {ctx.author.mention})'
    await ctx.send(msg, files=files if files else None)

@bot.command(name="банк")
@commands.check(in_family)
async def bank_balance(ctx, nickname: str = None):
    if nickname:
        nickname = nickname.replace("_", " ")
    else:
        nickname = get_family_nickname(ctx.author.id)
        if not nickname:
            return await ctx.send('❌ Вы не в семье. Укажите ник.')
    c.execute("SELECT balance FROM bank WHERE nickname=?", (nickname,))
    row = c.fetchone()
    if not row:
        return await ctx.send(f'❌ Счёт `{nickname}` не найден.')
    await ctx.send(f'💰 Баланс `{nickname}`: {row[0]}')

@bot.command(name="контракт", aliases=["контракт-взять", "контракт_взять"])
@commands.check(is_admin)
async def take_contract(ctx, title: str = None, participants: str = None, due_date: str = None, bills: int = 0):
    if None in (title, participants, due_date):
        return await ctx.send('ℹ️ Использование: `!контракт "Название" "Участники" ДД.ММ.ГГГГ ЧЧ:ММ [векселя]`')
    c.execute("INSERT INTO contracts (title, participants, due_date, bills, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?)",
              (title, participants, due_date, bills, str(ctx.author), datetime.datetime.now().isoformat()))
    conn.commit()
    await ctx.send(f'📝 Контракт "{title}" создан.\nУчастники: {participants}\nВыполнить до: {due_date}\nВекселей: {bills}\nСоздал: {ctx.author.mention}')

@bot.command(name="дв", aliases=["ДВ"])
@commands.check(is_admin)
async def disciplinary_action(ctx, nickname: str, action_type: str, *, reason: str):
    action_type = action_type.lower()
    allowed = ["предупреждение", "выговор", "2выговора", "warn", "увал"]
    if action_type not in allowed:
        return await ctx.send(f'❌ Неверный тип. Допустимые: {", ".join(allowed)}')
    nickname = nickname.replace("_", " ")
    ensure_player(nickname)
    c.execute("SELECT discord_id FROM family_members WHERE nickname=?", (nickname,))
    row = c.fetchone()
    discord_id = row[0] if row else None
    c.execute("INSERT INTO disciplinary_actions (nickname, discord_id, action_type, reason, issued_by, date) VALUES (?, ?, ?, ?, ?, ?)",
              (nickname, discord_id, action_type, reason, str(ctx.author), datetime.datetime.now().isoformat()))
    conn.commit()
    mention = f'<@{discord_id}>' if discord_id else nickname
    await ctx.send(f'⚠️ {mention} получил **{action_type}**.\nПричина: {reason}\nВыдал: {ctx.author.mention}')

@bot.command(name="выговоры")
@commands.check(in_family)
async def list_actions(ctx, nickname: str = None):
    if nickname:
        nickname = nickname.replace("_", " ")
    else:
        nickname = get_family_nickname(ctx.author.id)
        if not nickname:
            return await ctx.send('❌ Вы не в семье. Укажите ник.')
    c.execute("SELECT action_type, reason, issued_by, date FROM disciplinary_actions WHERE nickname=? ORDER BY date DESC", (nickname,))
    rows = c.fetchall()
    if not rows:
        return await ctx.send(f'✅ У `{nickname}` нет выговоров.')
    lines = [f'**{typ}** — {reason} (от {issued_by}, {date})' for typ, reason, issued_by, date in rows]
    embed = discord.Embed(title=f'📋 Выговоры: {nickname}', description='\n'.join(lines), color=0xff0000)
    await ctx.send(embed=embed)

@bot.command(name="помощь", aliases=["хелп"])
async def help_command(ctx):
    embed = discord.Embed(title="Помощь", color=0x00ff00)
    embed.add_field(name="👥 Семья", value="`!добавсемья ID Ник` — добавить\n`!удалсемья ID` — удалить\n`!семья` — список\n`!id @user` — узнать ID", inline=False)
    embed.add_field(name="🚗 Авто", value="`!добававто [ник] Модель Госномер`\n`!удалавто Госномер`\n`!авто`\n`!взятьавто Номер [ник] [часы]`\n`!вернутьавто Номер`", inline=False)
    embed.add_field(name="📦 Склад", value="`!склад`\n`!взятьсклад [ник] Предмет Кол-во`\n`!положитьсклад [ник] Предмет Кол-во`", inline=False)
    embed.add_field(name="💰 Банк", value="`!банк [ник]` — баланс\n`!пополнить Сумма Причина` — себе\n`!пополнить_ник Ник Сумма Причина`\n`!снять Сумма Причина` — себе\n`!снять_ник Ник Сумма Причина`", inline=False)
    embed.add_field(name="📝 Контракты", value="`!контракт \"Название\" \"Участники\" Дата [векселя]`", inline=False)
    embed.add_field(name="⚠️ Дисциплина", value="`!дв Ник Тип Причина`\n`!выговоры [ник]`", inline=False)
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
