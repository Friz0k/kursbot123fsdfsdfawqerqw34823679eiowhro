import discord
from discord.ext import commands
import sqlite3
import datetime
import io
import os
from flask import Flask
from threading import Thread

# ---------- НАСТРОЙКИ ----------
TOKEN = "MTUxNDY3MTA2NjY5MjE5MDMxOA.GZzryB.p1D7D_eXL-Qeo3SXq0__Eu8qpajG-O5J73jamY"   # <-- замени на реальный токен
ADMIN_ROLE_NAME = "Разработчик"
PREFIX = "!"

# ---------- БАЗА ДАННЫХ ----------
conn = sqlite3.connect('gta_rp.db')
c = conn.cursor()

c.execute('''CREATE TABLE IF NOT EXISTS family_members (
    nickname TEXT PRIMARY KEY,
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
    created_by TEXT,
    created_at TEXT
)''')
conn.commit()

# ---------- БОТ ----------
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix=PREFIX, intents=intents, help_command=None)

def is_admin(ctx):
    return any(role.name == ADMIN_ROLE_NAME for role in ctx.author.roles)

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

# ---------- КОМАНДЫ ----------
@bot.command(name="добавить-в-семью", aliases=["добавить_в_семью"])
@commands.check(is_admin)
async def add_family(ctx, nickname: str):
    nickname = nickname.replace("_", " ")
    if not get_player(nickname):
        return await ctx.send(f'❌ Игрок `{nickname}` не найден в системе.')
    c.execute("SELECT * FROM family_members WHERE nickname=?", (nickname,))
    if c.fetchone():
        return await ctx.send(f'⚠️ Игрок `{nickname}` уже в семье.')
    c.execute("INSERT INTO family_members (nickname, joined_at) VALUES (?, ?)",
              (nickname, datetime.datetime.now().isoformat()))
    conn.commit()
    await ctx.send(f'✅ Игрок `{nickname}` добавлен в семью. (Администратор: {ctx.author.mention})')

@bot.command(name="удалить-из-семьи", aliases=["удалить_из_семьи"])
@commands.check(is_admin)
async def remove_family(ctx, nickname: str):
    nickname = nickname.replace("_", " ")
    c.execute("DELETE FROM family_members WHERE nickname=?", (nickname,))
    if c.rowcount == 0:
        return await ctx.send(f'❌ Игрок `{nickname}` не состоит в семье.')
    conn.commit()
    await ctx.send(f'✅ Игрок `{nickname}` удалён из семьи. (Администратор: {ctx.author.mention})')

@bot.command(name="добавить-авто", aliases=["добавить_авто"])
@commands.check(is_admin)
async def add_car(ctx, nickname: str, model: str, plate: str):
    nickname = nickname.replace("_", " ")
    ensure_player(nickname)
    try:
        c.execute("INSERT INTO vehicles (owner_nick, model, plate) VALUES (?, ?, ?)",
                  (nickname, model, plate))
        conn.commit()
        car_id = c.lastrowid
        await ctx.send(f'🚗 Машина {model} (госномер {plate}) добавлена, номер авто: **{car_id}**. Владелец: `{nickname}`. (Администратор: {ctx.author.mention})')
    except sqlite3.IntegrityError:
        await ctx.send(f'❌ Машина с госномером `{plate}` уже существует.')

@bot.command(name="удалить-авто", aliases=["удалить_авто"])
@commands.check(is_admin)
async def remove_car(ctx, plate: str):
    c.execute("DELETE FROM vehicles WHERE plate=?", (plate,))
    if c.rowcount == 0:
        return await ctx.send(f'❌ Машина с госномером `{plate}` не найдена.')
    conn.commit()
    await ctx.send(f'🗑️ Машина с госномером `{plate}` удалена. (Администратор: {ctx.author.mention})')

@bot.command(name="инфо-авто")
async def car_info(ctx):
    check_auto_return()
    c.execute("SELECT id, owner_nick, model, plate, status, taken_by, return_at FROM vehicles")
    cars = c.fetchall()
    if not cars:
        return await ctx.send('🚫 Нет зарегистрированных авто.')
    lines = []
    for car in cars:
        car_id, owner, model, plate, status, taken_by, ret_at = car
        if status == 'свободен':
            line = f'`{car_id}` {model} ({plate}) — свободен'
        else:
            line = f'`{car_id}` {model} ({plate}) — занят {taken_by}, вернуть до {ret_at}'
        lines.append(line)
    embed = discord.Embed(title='🚗 Информация об авто', description='\n'.join(lines), color=0x3498db)
    await ctx.send(embed=embed)

@bot.command(name="взять-авто", aliases=["взять_авто"])
@commands.check(is_admin)
async def take_car(ctx, car_id: int = None, nickname: str = None, hours: float = 2.0):
    if car_id is None or nickname is None:
        return await ctx.send('ℹ️ Использование: `!взять-авто {номер_авто} {никнейм} [часы]`\nПример: `!взять-авто 1 Alexandr_Deadflux 2.5`')
    check_auto_return()
    nickname = nickname.replace("_", " ")
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
    await ctx.send(f'✅ Авто `{plate}` (№{car_id}) выдано игроку `{nickname}` на {hours} ч. Возврат до {return_at.strftime("%d.%m.%Y %H:%M")}. (Администратор: {ctx.author.mention})')

@bot.command(name="вернуть-авто", aliases=["вернуть_авто"])
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
    await ctx.send(f'✅ Авто `{plate}` возвращено. (Администратор: {ctx.author.mention})')

@bot.command(name="склад-инфо", aliases=["складинфо"])
async def warehouse_info(ctx):
    c.execute("SELECT item, amount FROM warehouse WHERE amount > 0")
    items = c.fetchall()
    if not items:
        return await ctx.send('📦 Склад пуст.')
    desc = '\n'.join(f'• **{item}** — {amount} шт.' for item, amount in items)
    embed = discord.Embed(title='📦 Склад', description=desc, color=0x00ff00)
    await ctx.send(embed=embed)

@bot.command(name="взять-со-склада", aliases=["взять_со_склада"])
@commands.check(is_admin)
async def take_from_warehouse(ctx, nickname: str = None, item: str = None, amount: int = None):
    if None in (nickname, item, amount):
        embed = discord.Embed(
            title="ℹ️ Использование",
            description="**!взять-со-склада {ник} {предмет} {количество}**\nПример: `!взять-со-склада Alexandr_Deadflux Аптечка 5`",
            color=0x3498db
        )
        return await ctx.send(embed=embed)
    nickname = nickname.replace("_", " ")
    if amount <= 0:
        return await ctx.send('❌ Количество должно быть больше нуля.')
    ensure_player(nickname)
    c.execute("SELECT amount FROM warehouse WHERE item=?", (item,))
    row = c.fetchone()
    if not row or row[0] < amount:
        return await ctx.send(f'❌ Недостаточно `{item}` на складе.')
    c.execute("UPDATE warehouse SET amount = amount - ? WHERE item=?", (amount, item))
    conn.commit()
    await ctx.send(f'✅ Игрок `{nickname}` забрал `{amount}` x **{item}** со склада. (Администратор: {ctx.author.mention})')

@bot.command(name="положить-на-склад", aliases=["положить_на_склад"])
@commands.check(is_admin)
async def put_to_warehouse(ctx, nickname: str = None, item: str = None, amount: int = None):
    if None in (nickname, item, amount):
        embed = discord.Embed(
            title="ℹ️ Использование",
            description="**!положить-на-склад {ник} {предмет} {количество}**\nПример: `!положить-на-склад Alexandr_Deadflux Аптечка 2`",
            color=0x3498db
        )
        return await ctx.send(embed=embed)
    nickname = nickname.replace("_", " ")
    if amount <= 0:
        return await ctx.send('❌ Количество должно быть больше нуля.')
    ensure_player(nickname)
    c.execute("INSERT INTO warehouse (item, amount) VALUES (?, ?) "
              "ON CONFLICT(item) DO UPDATE SET amount = amount + ?",
              (item, amount, amount))
    conn.commit()
    await ctx.send(f'✅ Игрок `{nickname}` положил `{amount}` x **{item}** на склад. (Администратор: {ctx.author.mention})')

@bot.command(name="банк-пополнить", aliases=["банк_пополнить"])
@commands.check(is_admin)
async def bank_add(ctx, nickname: str = None, amount: int = None, *, reason: str = None):
    if nickname is None or amount is None or reason is None:
        embed = discord.Embed(
            title="ℹ️ Использование команды",
            description="**!банк-пополнить {никнейм} {сумма} {причина}**\n"
                        "Пример: `!банк-пополнить Alexandr_Deadflux 100000 Оплата взносов`\n"
                        "Можно прикрепить скриншот баланса.",
            color=0x3498db
        )
        return await ctx.send(embed=embed)

    if amount <= 0:
        return await ctx.send('❌ Сумма должна быть положительной.')

    nickname = nickname.replace("_", " ")
    reason = reason.replace("_", " ")

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

    msg = f'💰 Счёт `{nickname}` пополнен на **{amount}**.\nПричина: {reason}\nТекущий баланс: **{new_balance}**\nАдминистратор: {ctx.author.mention}'
    if files:
        await ctx.send(msg, files=files)
    else:
        await ctx.send(msg)

@bot.command(name="банк-снять", aliases=["банк_снять"])
@commands.check(is_admin)
async def bank_remove(ctx, nickname: str = None, amount: int = None, *, reason: str = None):
    if nickname is None or amount is None or reason is None:
        embed = discord.Embed(
            title="ℹ️ Использование команды",
            description="**!банк-снять {никнейм} {сумма} {причина}**\n"
                        "Пример: `!банк-снять Alexandr_Deadflux 50000 Крафт`\n"
                        "Можно прикрепить скриншот.",
            color=0x3498db
        )
        return await ctx.send(embed=embed)

    if amount <= 0:
        return await ctx.send('❌ Сумма должна быть положительной.')

    nickname = nickname.replace("_", " ")
    reason = reason.replace("_", " ")

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

    msg = f'💸 Со счета `{nickname}` снято **{amount}**.\nПричина: {reason}\nНовый баланс: **{new_balance}**\nАдминистратор: {ctx.author.mention}'
    if files:
        await ctx.send(msg, files=files)
    else:
        await ctx.send(msg)

@bot.command(name="контракт-взять", aliases=["контракт_взять"])
@commands.check(is_admin)
async def take_contract(ctx, title: str = None, participants: str = None, due_date: str = None):
    if None in (title, participants, due_date):
        embed = discord.Embed(
            title="ℹ️ Использование",
            description="**!контракт-взять \"Название\" \"Участник1, Участник2, ...\" ДД.ММ.ГГГГ ЧЧ:ММ**\n"
                        "Пример: `!контракт-взять \"Тихая гавань\" \"Игрок1, Игрок2\" 12.06.2026 13:00`\n"
                        "До 20 участников через запятую.",
            color=0x3498db
        )
        return await ctx.send(embed=embed)
    c.execute("INSERT INTO contracts (title, participants, due_date, created_by, created_at) "
              "VALUES (?, ?, ?, ?, ?)",
              (title, participants, due_date, str(ctx.author), datetime.datetime.now().isoformat()))
    conn.commit()
    await ctx.send(f'📝 Контракт **{title}** создан.\nУчастники: {participants}\nВыполнить до: {due_date}\nСоздал: {ctx.author.mention}')

@bot.command(name="помощь", aliases=["хелп"])
async def help_command(ctx):
    embed = discord.Embed(
        title="📋 Список команд",
        description="Все команды начинаются с `!`\n\n"
                    "👥 **Семья**\n"
                    "`!добавить-в-семью {ник}` — добавить в семью\n"
                    "`!удалить-из-семьи {ник}` — удалить из семьи\n\n"
                    "🚗 **Автомобили**\n"
                    "`!добавить-авто {ник} {модель} {госномер}`\n"
                    "`!удалить-авто {госномер}`\n"
                    "`!инфо-авто` — список всех авто и их статус\n"
                    "`!взять-авто {номер_авто} {ник} [часы]` — выдать авто (по умолч. 2 часа)\n"
                    "`!вернуть-авто {номер_авто}` — досрочно вернуть\n\n"
                    "📦 **Склад**\n"
                    "`!склад-инфо` — посмотреть содержимое\n"
                    "`!взять-со-склада {ник} {предмет} {кол-во}`\n"
                    "`!положить-на-склад {ник} {предмет} {кол-во}`\n\n"
                    "💰 **Банк**\n"
                    "`!банк-пополнить {ник} {сумма} {причина}`\n"
                    "`!банк-снять {ник} {сумма} {причина}`\n"
                    "   (можно прикрепить скриншот)\n\n"
                    "📝 **Контракты**\n"
                    "`!контракт-взять \"Название\" \"Участники\" ДД.ММ.ГГГГ ЧЧ:ММ`\n\n"
                    "ℹ️ Если забыли синтаксис, просто введите команду без аргументов.",
        color=0x00ff00
    )
    await ctx.send(embed=embed)

@bot.event
async def on_command_completion(ctx):
    try:
        await ctx.message.delete()
    except (discord.Forbidden, discord.HTTPException):
        pass

# ---------- ВЕБ-СЕРВЕР (чтобы Render не засыпал) ----------
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is alive!"

def run_web():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

t = Thread(target=run_web)
t.start()

# ---------- ЗАПУСК БОТА ----------
bot.run(TOKEN)