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
HR_ROLE = "Recruiter"
DIS_ROLE = "Dicipline"
FAMILY_ACCESS_ROLE = "Deadly"
PREFIX = "!"

CONTRACT_NOTIFY_ROLE_ID = 1473705347020623943

DB_PATH = 'gta_rp.db'

conn = sqlite3.connect(DB_PATH)
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

def has_dis_access(ctx):
    return any(r.name in (DIS_ROLE, ADMIN_ROLE) for r in ctx.author.roles)

def has_family_role(ctx):
    """Доступ к семейным функциям: Deadly, Тех. Состав, или член семьи."""
    if any(r.name == FAMILY_ACCESS_ROLE for r in ctx.author.roles):
        return True
    if has_admin(ctx):
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
        await ctx.send("❌ Недостаточно прав.", delete_after=10)
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"❌ Пропущен аргумент. Используйте `!помощь`.", delete_after=10)
    elif isinstance(error, commands.BadArgument):
        await ctx.send(f"❌ Неверный аргумент: {error}", delete_after=10)
    else:
        await ctx.send(f"❌ Ошибка: {str(error)}", delete_after=10)

@bot.command(name="backup")
@commands.check(has_admin)
async def backup_db(ctx):
    if not os.path.exists(DB_PATH):
        return await ctx.send("❌ База данных не найдена.", delete_after=10)
    file = discord.File(DB_PATH, filename="gta_rp.db")
    await ctx.send("📦 Бекап базы данных:", file=file)

@bot.command(name="restore")
@commands.check(has_admin)
async def restore_db(ctx):
    if len(ctx.message.attachments) == 0:
        return await ctx.send("❌ Прикрепите файл gta_rp.db.", delete_after=10)
    att = ctx.message.attachments[0]
    if not att.filename.endswith('.db'):
        return await ctx.send("❌ Файл должен иметь расширение .db.", delete_after=10)
    if os.path.exists(DB_PATH):
        os.rename(DB_PATH, DB_PATH + '.backup')
    try:
        await att.save(DB_PATH)
        global conn, c
        conn.close()
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        await ctx.send("✅ База данных восстановлена.")
    except Exception as e:
        await ctx.send(f"❌ Ошибка восстановления: {e}", delete_after=10)
        if os.path.exists(DB_PATH + '.backup'):
            os.rename(DB_PATH + '.backup', DB_PATH)

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
        return await ctx.send(f'⚠️ Пользователь с ID `{discord_id}` уже в семье.', delete_after=10)
    c.execute("SELECT * FROM family_members WHERE nickname=?", (nickname,))
    if c.fetchone():
        return await ctx.send(f'⚠️ Ник `{nickname}` уже занят.', delete_after=10)
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
        return await ctx.send(f'❌ Пользователь с ID `{discord_id}` не найден в семье.', delete_after=10)
    nickname = row[0]
    c.execute("DELETE FROM family_members WHERE discord_id=?", (discord_id,))
    conn.commit()
    await ctx.send(f'✅ <@{discord_id}> (`{nickname}`) удалён из семьи.')

@bot.command(name="семья")
@commands.check(has_family_role)
async def family_list(ctx):
    c.execute("SELECT nickname, discord_id FROM family_members")
    rows = c.fetchall()
    if not rows:
        return await ctx.send('👪 Семья пуста.', delete_after=10)
    lines = [f'<@{disc_id}> — `{nick}`' for nick, disc_id in rows]
    embed = discord.Embed(title='👥 Семья', description='\n'.join(lines), color=0x00ff00)
    await ctx.send(embed=embed)

@bot.command(name="добававто")
@commands.check(has_admin)
async def add_car(ctx, model: str, plate: str):
    nick = get_member_nick(ctx.author.id)
    if not nick:
        return await ctx.send('❌ Вы не привязаны к семье. Сначала добавьте себя через !добавсемья.', delete_after=10)
    nick = nick.replace("_", " ")
    try:
        c.execute("INSERT INTO vehicles (owner_nick, model, plate) VALUES (?, ?, ?)", (nick, model, plate))
        conn.commit()
        car_id = c.lastrowid
        await ctx.send(f'🚗 {model} ({plate}) добавлен, номер {car_id}. Владелец: `{nick}`.')
    except sqlite3.IntegrityError:
        await ctx.send(f'❌ Госномер `{plate}` уже существует.', delete_after=10)

@bot.command(name="удалавто")
@commands.check(has_admin)
async def remove_car(ctx, plate: str):
    c.execute("DELETE FROM vehicles WHERE plate=?", (plate,))
    if c.rowcount == 0:
        return await ctx.send(f'❌ Машина с госномером `{plate}` не найдена.', delete_after=10)
    conn.commit()
    await ctx.send(f'🗑️ Машина `{plate}` удалена.')

@bot.command(name="авто")
@commands.check(has_family_role)
async def car_list(ctx):
    auto_return()
    c.execute("SELECT id, owner_nick, model, plate, status, taken_by, return_at FROM vehicles")
    cars = c.fetchall()
    if not cars:
        return await ctx.send('🚫 Нет машин.', delete_after=10)
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
        return await ctx.send('❌ Вы не привязаны к семье.', delete_after=10)
    nick = nick.replace("_", " ")
    auto_return()
    c.execute("SELECT status, plate FROM vehicles WHERE id=?", (car_id,))
    car = c.fetchone()
    if not car:
        return await ctx.send(f'❌ Авто с номером `{car_id}` не найдено.', delete_after=10)
    status, plate = car
    if status != 'свободен':
        return await ctx.send(f'❌ Авто `{plate}` уже занято.', delete_after=10)
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
        return await ctx.send(f'❌ Авто с номером `{car_id}` не найдено.', delete_after=10)
    plate, status = car
    if status == 'свободен':
        return await ctx.send(f'❌ Авто `{plate}` уже свободно.', delete_after=10)
    c.execute("UPDATE vehicles SET status='свободен', taken_by=NULL, taken_at=NULL, return_at=NULL WHERE id=?", (car_id,))
    conn.commit()
    await ctx.send(f'✅ Авто `{plate}` возвращено.')

@bot.command(name="склад")
@commands.check(has_family_role)
async def warehouse_info(ctx):
    c.execute("SELECT item, amount FROM warehouse WHERE amount > 0")
    items = c.fetchall()
    if not items:
        return await ctx.send('📦 Склад пуст.', delete_after=10)
    desc = '\n'.join(f'• {item}: {amount} шт.' for item, amount in items)
    embed = discord.Embed(title='📦 Склад', description=desc, color=0x00ff00)
    await ctx.send(embed=embed)

@bot.command(name="взятьсклад")
@commands.check(has_admin)
async def take_warehouse(ctx, item: str, amount: int):
    nick = get_member_nick(ctx.author.id)
    if not nick:
        return await ctx.send('❌ Вы не привязаны к семье.', delete_after=10)
    nick = nick.replace("_", " ")
    if amount <= 0:
        return await ctx.send('❌ Количество > 0.', delete_after=10)
    c.execute("SELECT amount FROM warehouse WHERE item=?", (item,))
    row = c.fetchone()
    if not row or row[0] < amount:
        return await ctx.send(f'❌ Недостаточно `{item}` на складе.', delete_after=10)
    c.execute("UPDATE warehouse SET amount = amount - ? WHERE item=?", (amount, item))
    conn.commit()
    await ctx.send(f'✅ `{nick}` забрал {amount} x {item} со склада.')

@bot.command(name="положитьсклад")
@commands.check(has_admin)
async def put_warehouse(ctx, item: str, amount: int):
    nick = get_member_nick(ctx.author.id)
    if not nick:
        return await ctx.send('❌ Вы не привязаны к семье.', delete_after=10)
    nick = nick.replace("_", " ")
    if amount <= 0:
        return await ctx.send('❌ Количество > 0.', delete_after=10)
    c.execute("INSERT INTO warehouse (item, amount) VALUES (?, ?) ON CONFLICT(item) DO UPDATE SET amount = amount + ?",
              (item, amount, amount))
    conn.commit()
    await ctx.send(f'✅ `{nick}` положил {amount} x {item} на склад.')

@bot.command(name="банк")
@commands.check(has_family_role)
async def bank_balance(ctx):
    balance = get_family_balance()
    await ctx.send(f'💰 Баланс семьи: {balance}')

@bot.command(name="пополнить")
@commands.check(has_family_role)
async def bank_add(ctx, amount: int, *, reason: str = ""):
    if amount <= 0:
        return await ctx.send('❌ Сумма должна быть положительной.', delete_after=10)
    nick = get_member_nick(ctx.author.id)
    if not nick:
        return await ctx.send('❌ Вы не привязаны к семье. Используйте !добавсемья.', delete_after=10)
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
@commands.check(has_family_role)
async def bank_remove(ctx, amount: int, *, reason: str = ""):
    if amount <= 0:
        return await ctx.send('❌ Сумма должна быть положительной.', delete_after=10)
    nick = get_member_nick(ctx.author.id)
    if not nick:
        return await ctx.send('❌ Вы не привязаны к семье. Используйте !добавсемья.', delete_after=10)
    nick = nick.replace("_", " ")
    balance = get_family_balance()
    if balance < amount:
        return await ctx.send(f'❌ Недостаточно средств. Баланс: {balance}.', delete_after=10)
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
        return await ctx.send('ℹ️ Использование: `!контракт "Название" Участник1 Участник2 ... ДД.ММ.ГГГГ ЧЧ:ММ [векселя]`', delete_after=10)
    parts = args.split()
    if len(parts) < 2:
        return await ctx.send('❌ Укажите дату (ДД.ММ.ГГГГ) и время (ЧЧ:ММ).', delete_after=10)
    bills = 0
    if parts[-1].isdigit():
        bills = int(parts[-1])
        parts = parts[:-1]
    if len(parts) < 2:
        return await ctx.send('❌ Нужна дата и время.', delete_after=10)
    time_str = parts[-1]
    date_str = parts[-2]
    if not re.match(r'\d{2}\.\d{2}\.\d{4}', date_str) or not re.match(r'\d{2}:\d{2}', time_str):
        return await ctx.send('❌ Неверный формат даты/времени. Ожидается ДД.ММ.ГГГГ ЧЧ:ММ.', delete_after=10)
    participants = ' '.join(parts[:-2])
    due_date = f"{date_str} {time_str}"
    parts_list = participants.split()
    participants_db = ', '.join(parts_list)
    c.execute("INSERT INTO contracts (title, participants, due_date, bills, created_by, created_at) VALUES (?,?,?,?,?,?)",
              (title, participants_db, due_date, bills, str(ctx.author), datetime.datetime.now().isoformat()))
    conn.commit()

    role = ctx.guild.get_role(CONTRACT_NOTIFY_ROLE_ID)
    if role is None:
        role_mention = ""
    elif not role.mentionable:
        await ctx.send("⚠️ Роль для уведомлений не упоминаема. Контракт создан без тега.", delete_after=10)
        role_mention = ""
    else:
        role_mention = role.mention

    await ctx.send(f'{role_mention}\n📝 Контракт "{title}" ожидает подтверждения.\nУчастники: {participants_db}\nСрок: {due_date}\nВекселей: {bills}')

@bot.command(name="дв")
@commands.check(has_dis_access)
async def dv_add(ctx, nickname: str, action_type: str, *, reason: str):
    action_type = action_type.lower()
    allowed = ["предупреждение", "выговор", "2выговора", "warn", "увал"]
    if action_type not in allowed:
        return await ctx.send(f'❌ Неверный тип. Допустимые: {", ".join(allowed)}', delete_after=10)
    nickname = nickname.replace("_", " ")

    has_image = False
    for att in ctx.message.attachments:
        if att.content_type and att.content_type.startswith("image/"):
            has_image = True
            break
    if not has_image:
        return await ctx.send('❌ Необходимо прикрепить скриншот.', delete_after=10)

    c.execute("SELECT discord_id FROM family_members WHERE nickname=?", (nickname,))
    row = c.fetchone()
    discord_id = row[0] if row else None

    files = []
    for att in ctx.message.attachments:
        if att.content_type and att.content_type.startswith("image/"):
            img_bytes = await att.read()
            new_name = att.filename.replace("_", "-")
            files.append(discord.File(fp=io.BytesIO(img_bytes), filename=new_name))

    c.execute("INSERT INTO disciplinary_actions (nickname, discord_id, action_type, reason, issued_by, date) VALUES (?,?,?,?,?,?)",
              (nickname, discord_id, action_type, reason, str(ctx.author), datetime.datetime.now().isoformat()))
    conn.commit()
    mention = f'<@{discord_id}>' if discord_id else nickname
    await ctx.send(f'⚠️ {mention} получил **{action_type}**.\nПричина: {reason}\nВыдал: {ctx.author.mention}', files=files if files else None)

@bot.command(name="выговоры")
@commands.check(has_family_role)
async def dv_list(ctx, nickname: str = None):
    if nickname:
        nickname = nickname.replace("_", " ")
    else:
        nickname = get_member_nick(ctx.author.id)
        if not nickname:
            return await ctx.send('❌ Укажите ник или будьте в семье.', delete_after=10)
    c.execute("SELECT action_type, reason, issued_by, date FROM disciplinary_actions WHERE nickname=? ORDER BY date DESC", (nickname,))
    rows = c.fetchall()
    if not rows:
        return await ctx.send(f'✅ У `{nickname}` нет выговоров.', delete_after=10)
    lines = [f'**{t}** — {r} (от {i}, {d})' for t, r, i, d in rows]
    embed = discord.Embed(title=f'📋 Выговоры: {nickname}', description='\n'.join(lines), color=0xff0000)
    await ctx.send(embed=embed)

@bot.command(name="снятьдв")
@commands.check(has_dis_access)
async def dv_remove(ctx, nickname: str, *, reason: str):
    nickname = nickname.replace("_", " ")
    c.execute("DELETE FROM disciplinary_actions WHERE id = (SELECT id FROM disciplinary_actions WHERE nickname=? ORDER BY date DESC LIMIT 1)", (nickname,))
    if c.rowcount == 0:
        return await ctx.send(f'❌ У `{nickname}` нет выговоров.', delete_after=10)
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
    embed.add_field(name="💰 Банк", value="`!банк` — баланс семьи\n`!пополнить Сумма [Причина]`\n`!снять Сумма [Причина]` — (Deadly/Тех. Состав/члены семьи)", inline=False)
    embed.add_field(name="📝 Контракты", value="`!контракт \"Название\" Участник1 Участник2 ... ДД.ММ.ГГГГ ЧЧ:ММ [векселя]`\n(отмечается <@&роль>)", inline=False)
    embed.add_field(name="⚠️ Дисциплина", value="`!дв Ник Тип Причина` (обязательно прикрепить скриншот)\n`!выговоры [ник]`\n`!снятьдв Ник Причина`", inline=False)
    embed.add_field(name="💾 Бекап", value="`!backup` — сохранить базу данных\n`!restore` — восстановить базу из прикреплённого файла", inline=False)
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
