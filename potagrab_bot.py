# -*- coding: utf-8 -*-
import asyncio
import aiohttp
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.types import CallbackQuery
from aiogram.exceptions import TelegramForbiddenError
import logging
import os
import sys
import io
import json

# ===== FIX WINDOWS ENCODING =====
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')
# ================================

# ========== SETTINGS ==========
# Берём токен из переменной окружения BOT_TOKEN
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    logging.error("BOT_TOKEN environment variable not set!")
    sys.exit(1)
# ===============================

API_URL = "https://api.pota.app/spot"
DEFAULT_INTERVAL = 120
MIN_INTERVAL = 60
USERS_CONFIG_FILE = "users_config.json"

# Global variables
current_interval = DEFAULT_INTERVAL
update_task = None
users_config = {}

# DIGI modes
DIGI_MODES = ["FT4", "FT8", "RTTY", "PSK", "PSK31", "PSK63", "MFSK", "JT65", "JT9", "FT2", "FSK", "OLIVIA", "CONTESTI", "HELL", "THOR", "DOMINO"]

# Band definitions
BANDS = {
    "160m": {"name": "160m", "min_freq": 1800, "max_freq": 2000, "emoji": "🔴"},
    "80m": {"name": "80m", "min_freq": 3500, "max_freq": 4000, "emoji": "🟠"},
    "60m": {"name": "60m", "min_freq": 5330, "max_freq": 5400, "emoji": "🟡"},
    "40m": {"name": "40m", "min_freq": 7000, "max_freq": 7300, "emoji": "🟢"},
    "30m": {"name": "30m", "min_freq": 10100, "max_freq": 10150, "emoji": "🔵"},
    "20m": {"name": "20m", "min_freq": 14000, "max_freq": 14350, "emoji": "🟣"},
    "17m": {"name": "17m", "min_freq": 18068, "max_freq": 18168, "emoji": "🟤"},
    "15m": {"name": "15m", "min_freq": 21000, "max_freq": 21450, "emoji": "🔴"},
    "12m": {"name": "12m", "min_freq": 24890, "max_freq": 24990, "emoji": "⚫"},
    "10m": {"name": "10m", "min_freq": 28000, "max_freq": 29700, "emoji": "⚪"},
    "vhf": {"name": "VHF (6m+)", "min_freq": 50000, "max_freq": 999999, "emoji": "📡"},
}

# ========== CONFIG FUNCTIONS ==========
def load_users_config():
    global users_config
    if os.path.exists(USERS_CONFIG_FILE):
        try:
            with open(USERS_CONFIG_FILE, 'r', encoding='utf-8') as f:
                users_config = json.load(f)
                logging.info(f"Loaded config for {len(users_config)} users")
        except Exception as e:
            logging.error(f"Error loading users config: {e}")
            users_config = {}
    else:
        users_config = {}

def save_users_config():
    global users_config
    try:
        with open(USERS_CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(users_config, f, ensure_ascii=False, indent=2)
        logging.info(f"Saved config for {len(users_config)} users")
    except Exception as e:
        logging.error(f"Error saving users config: {e}")

def get_user_config(user_id):
    user_id_str = str(user_id)
    if user_id_str not in users_config:
        users_config[user_id_str] = {
            "selected_bands": ["all"],
            "selected_modes": ["all"],
            "blocked_reference_prefixes": [],
            "last_spot_id": 0,
            "active": True
        }
    return users_config[user_id_str]

def restore_user(user_id):
    user_id_str = str(user_id)
    if user_id_str in users_config:
        users_config[user_id_str]["active"] = True
        logging.info(f"Restored existing user {user_id}")
    else:
        users_config[user_id_str] = {
            "selected_bands": ["all"],
            "selected_modes": ["all"],
            "blocked_reference_prefixes": [],
            "last_spot_id": 0,
            "active": True
        }
        logging.info(f"Created new config for user {user_id}")
    save_users_config()

def remove_user(user_id):
    user_id_str = str(user_id)
    if user_id_str in users_config:
        del users_config[user_id_str]
        save_users_config()
        logging.info(f"Removed user {user_id} (blocked bot)")

def is_user_active(user_id):
    config = get_user_config(user_id)
    return config.get("active", True)

def set_user_active(user_id, active):
    get_user_config(user_id)["active"] = active
    save_users_config()

def get_last_spot_id(user_id):
    return get_user_config(user_id).get("last_spot_id", 0)

def save_last_spot_id(user_id, spot_id):
    get_user_config(user_id)["last_spot_id"] = spot_id
    save_users_config()

def get_selected_bands(user_id):
    return get_user_config(user_id).get("selected_bands", ["all"])

def save_selected_bands(user_id, bands):
    get_user_config(user_id)["selected_bands"] = bands
    save_users_config()

def get_selected_modes(user_id):
    return get_user_config(user_id).get("selected_modes", ["all"])

def save_selected_modes(user_id, modes):
    get_user_config(user_id)["selected_modes"] = modes
    save_users_config()

def get_blocked_prefixes(user_id):
    return get_user_config(user_id).get("blocked_reference_prefixes", [])

def save_blocked_prefixes(user_id, prefixes):
    get_user_config(user_id)["blocked_reference_prefixes"] = prefixes
    save_users_config()

# ========== DISPLAY FUNCTIONS ==========
def get_bands_display(user_id):
    selected = get_selected_bands(user_id)
    if "all" in selected:
        return "All bands"
    if not selected:
        return "No bands"
    names = [BANDS[b]["name"] for b in selected if b in BANDS]
    return ", ".join(names[:3]) + (f" +{len(names)-3}" if len(names) > 3 else "")

def get_modes_display(user_id):
    selected = get_selected_modes(user_id)
    if "all" in selected:
        return "All modes"
    if not selected:
        return "No modes"
    names = []
    for m in selected:
        if m == "DIGI":
            names.append("DIGI")
        else:
            names.append(m)
    return ", ".join(names)

def get_blocked_display(user_id):
    blocked = get_blocked_prefixes(user_id)
    return ", ".join(blocked) if blocked else "None"

# ========== FILTER FUNCTIONS ==========
def check_band_filter(freq_str, user_id):
    selected = get_selected_bands(user_id)
    if "all" in selected:
        return True
    if not selected:
        return False
    try:
        freq = float(freq_str)
    except:
        return True
    for band in selected:
        if band in BANDS and BANDS[band]["min_freq"] <= freq <= BANDS[band]["max_freq"]:
            return True
    return False

def check_mode_filter(mode, user_id):
    selected = get_selected_modes(user_id)
    if "all" in selected:
        return True
    if not selected:
        return False
    mode_up = mode.upper() if mode else ""
    for m in selected:
        if m == "CW" and mode_up == "CW":
            return True
        if m == "SSB" and mode_up == "SSB":
            return True
        if m == "DIGI" and mode_up in DIGI_MODES:
            return True
    return False

def check_reference_filter(ref, user_id):
    blocked = get_blocked_prefixes(user_id)
    if not blocked:
        return True
    for prefix in blocked:
        if ref and ref.upper().startswith(prefix.upper()):
            return False
    return True

# ========== FORMATTING FUNCTIONS ==========
def make_bold(text):
    bold = {'A':'𝗔','B':'𝗕','C':'𝗖','D':'𝗗','E':'𝗘','F':'𝗙','G':'𝗚','H':'𝗛','I':'𝗜','J':'𝗝','K':'𝗞','L':'𝗟','M':'𝗠','N':'𝗡','O':'𝗢','P':'𝗣','Q':'𝗤','R':'𝗥','S':'𝗦','T':'𝗧','U':'𝗨','V':'𝗩','W':'𝗪','X':'𝗫','Y':'𝗬','Z':'𝗭',
            'a':'𝗮','b':'𝗯','c':'𝗰','d':'𝗱','e':'𝗲','f':'𝗳','g':'𝗴','h':'𝗵','i':'𝗶','j':'𝗷','k':'𝗸','l':'𝗹','m':'𝗺','n':'𝗻','o':'𝗼','p':'𝗽','q':'𝗾','r':'𝗿','s':'𝘀','t':'𝘁','u':'𝘂','v':'𝘃','w':'𝘄','x':'𝘅','y':'𝘆','z':'𝘇',
            '0':'𝟬','1':'𝟭','2':'𝟮','3':'𝟯','4':'𝟰','5':'𝟱','6':'𝟲','7':'𝟳','8':'𝟴','9':'𝟵','/':'／','-':'－'}
    return ''.join(bold.get(c, c) for c in str(text))

def make_italic(text):
    italic = {'A':'𝐴','B':'𝐵','C':'𝐶','D':'𝐷','E':'𝐸','F':'𝐹','G':'𝐺','H':'𝐻','I':'𝐼','J':'𝐽','K':'𝐾','L':'𝐿','M':'𝑀','N':'𝑁','O':'𝑂','P':'𝑃','Q':'𝑄','R':'𝑅','S':'𝑆','T':'𝑇','U':'𝑈','V':'𝑉','W':'𝑊','X':'𝑋','Y':'𝑌','Z':'𝑍',
              'a':'𝑎','b':'𝑏','c':'𝑐','d':'𝑑','e':'𝑒','f':'𝑓','g':'𝑔','h':'ℎ','i':'𝑖','j':'𝑗','k':'𝑘','l':'𝑙','m':'𝑚','n':'𝑛','o':'𝑜','p':'𝑝','q':'𝑞','r':'𝑟','s':'𝑠','t':'𝑡','u':'𝑢','v':'𝑣','w':'𝑤','x':'𝑥','y':'𝑦','z':'𝑧'}
    return ''.join(italic.get(c, c) for c in str(text))

def format_spot_line(spot):
    freq = spot.get('frequency', 'N/A')
    activator = spot.get('activator', 'N/A')
    mode = spot.get('mode', 'N/A')
    ref = spot.get('reference', 'N/A')
    name = spot.get('name', 'N/A')
    loc = spot.get('locationDesc', 'N/A')
    time_raw = spot.get('spotTime', '')
    time_short = time_raw.split('T')[1][:5] if time_raw and 'T' in time_raw else "??:??"
    return f"{time_short} {make_bold(activator)} {freq} kHz {mode} {make_bold(ref)} ({loc})\n{make_italic(name)}"

def format_interval(sec):
    if sec < 60:
        return f"{sec} sec"
    if sec == 60:
        return "1 min"
    if sec < 3600:
        return f"{sec//60} min"
    return f"{sec//3600} h"

# ========== KEYBOARDS ==========
def get_main_keyboard(user_id):
    active = is_user_active(user_id)
    buttons = [
        [KeyboardButton(text="🔄 Now")],
        [KeyboardButton(text="⏱️ Set Interval"), KeyboardButton(text="🎚️ Set Band")],
        [KeyboardButton(text="📡 Set Mode"), KeyboardButton(text="🚫 Block Reference")],
        [KeyboardButton(text="🛑 STOP" if active else "▶️ START"), KeyboardButton(text="📊 Status")],
        [KeyboardButton(text="🔄 Reset History"), KeyboardButton(text="❓ Help")]
    ]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True, one_time_keyboard=False)

def get_interval_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="1 min", callback_data="int_60"),
         InlineKeyboardButton(text="2 min", callback_data="int_120"),
         InlineKeyboardButton(text="5 min", callback_data="int_300")],
        [InlineKeyboardButton(text="📝 Custom", callback_data="int_custom")],
        [InlineKeyboardButton(text="❌ Cancel", callback_data="int_cancel")]
    ])

def get_bands_keyboard(user_id):
    selected = get_selected_bands(user_id)
    keyboard = []
    band_list = ["160m", "80m", "60m", "40m", "30m", "20m", "17m", "15m", "12m", "10m", "vhf"]
    for i in range(0, len(band_list), 2):
        row = []
        for band in band_list[i:i+2]:
            check = "✅ " if band in selected else ""
            row.append(InlineKeyboardButton(text=f"{check}{BANDS[band]['emoji']} {band}", callback_data=f"band_{band}"))
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton(text="🌍 All Bands" if "all" in selected else "📻 All Bands", callback_data="band_all"),
                     InlineKeyboardButton(text="❌ Clear", callback_data="band_clear")])
    keyboard.append([InlineKeyboardButton(text="✅ Apply", callback_data="band_apply"),
                     InlineKeyboardButton(text="❌ Cancel", callback_data="band_cancel")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_modes_keyboard(user_id):
    selected = get_selected_modes(user_id)
    keyboard = [
        [InlineKeyboardButton(text=f"{'✅ ' if 'CW' in selected else ''}📡 CW", callback_data="mode_CW"),
         InlineKeyboardButton(text=f"{'✅ ' if 'SSB' in selected else ''}🎙️ SSB", callback_data="mode_SSB")],
        [InlineKeyboardButton(text=f"{'✅ ' if 'DIGI' in selected else ''}💻 DIGI", callback_data="mode_DIGI")],
        [InlineKeyboardButton(text="🌍 All Modes" if "all" in selected else "📻 All Modes", callback_data="mode_all"),
         InlineKeyboardButton(text="❌ Clear", callback_data="mode_clear")],
        [InlineKeyboardButton(text="✅ Apply", callback_data="mode_apply"),
         InlineKeyboardButton(text="❌ Cancel", callback_data="mode_cancel")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_blocked_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Add", callback_data="block_add")],
        [InlineKeyboardButton(text="📋 Show / Remove", callback_data="block_show")],
        [InlineKeyboardButton(text="🗑️ Clear All", callback_data="block_clear")],
        [InlineKeyboardButton(text="❌ Cancel", callback_data="block_cancel")]
    ])

def get_blocked_list_keyboard(user_id):
    blocked = get_blocked_prefixes(user_id)
    keyboard = [[InlineKeyboardButton(text=f"❌ {p}", callback_data=f"block_remove_{p}")] for p in blocked]
    keyboard.append([InlineKeyboardButton(text="🔙 Back", callback_data="block_back")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

# ========== BOT CORE ==========
load_users_config()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler('bot.log', encoding='utf-8')]
)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ========== SPOT FUNCTIONS ==========
async def send_spots_to_user(user_id, spots, title):
    if not spots:
        return
    
    # Дедупликация по позывному (активатору)
    unique_spots = {}
    for spot in spots:
        activator = spot.get('activator', '')
        if activator not in unique_spots:
            unique_spots[activator] = spot
    
    unique_spots_list = list(unique_spots.values())
    
    full = "\n\n".join(format_spot_line(s) for s in unique_spots_list)
    prefix = f"{title}\nBands: {get_bands_display(user_id)} | Modes: {get_modes_display(user_id)} | Blocked: {get_blocked_display(user_id)}\n{'-'*40}\n\n"
    full = prefix + full
    
    # Добавляем информацию о дедупликации
    if len(spots) != len(unique_spots_list):
        full = f"{full}\n\n_({len(unique_spots_list)} unique activators out of {len(spots)} total spots)_"
    
    try:
        if len(full) > 4096:
            await bot.send_message(user_id, f"{title[:20]}... ({len(unique_spots_list)} unique activators)")
            for i in range(0, len(full), 4096):
                await bot.send_message(user_id, full[i:i+4096])
        else:
            await bot.send_message(user_id, full)
    except TelegramForbiddenError:
        logging.warning(f"User {user_id} blocked the bot, removing from config")
        remove_user(user_id)
    except Exception as e:
        logging.error(f"Send error to {user_id}: {e}")

async def check_new_for_user(user_id, all_spots):
    last_id = get_last_spot_id(user_id)
    new_spots = []
    max_id = 0
    for spot in all_spots:
        sid = spot.get('spotId', 0)
        max_id = max(max_id, sid)
        if sid > last_id and check_band_filter(spot.get('frequency', '0'), user_id) and check_reference_filter(spot.get('reference', ''), user_id) and check_mode_filter(spot.get('mode', ''), user_id):
            new_spots.append(spot)
    if max_id > last_id:
        save_last_spot_id(user_id, max_id)
    return new_spots

async def fetch_all_for_user(user_id):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(API_URL) as resp:
                if resp.status == 200:
                    spots = await resp.json()
                    filtered = [s for s in spots if check_band_filter(s.get('frequency', '0'), user_id) and check_reference_filter(s.get('reference', ''), user_id) and check_mode_filter(s.get('mode', ''), user_id)]
                    if spots:
                        save_last_spot_id(user_id, max(s.get('spotId', 0) for s in spots))
                    await send_spots_to_user(user_id, filtered, f"📡 ALL SPOTS ({len(filtered)}/{len(spots)})")
                else:
                    try:
                        await bot.send_message(user_id, f"❌ API error: {resp.status}")
                    except TelegramForbiddenError:
                        remove_user(user_id)
    except Exception as e:
        logging.error(f"Fetch error for {user_id}: {e}")

async def fetch_and_send_all():
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(API_URL) as resp:
                if resp.status == 200:
                    all_spots = await resp.json()
                    for uid_str, cfg in list(users_config.items()):
                        uid = int(uid_str)
                        if cfg.get("active", True):
                            new = await check_new_for_user(uid, all_spots)
                            if new:
                                await send_spots_to_user(uid, new, f"🆕 NEW ({len(new)})")
                                logging.info(f"Sent {len(new)} new spots to {uid} (after dedup: {len(set(s.get('activator') for s in new))} unique)")
    except Exception as e:
        logging.error(f"Fetch error: {e}")

async def periodic_check():
    while True:
        await fetch_and_send_all()
        await asyncio.sleep(current_interval)

# ========== COMMANDS ==========
@dp.message(Command("start"))
async def cmd_start(m: types.Message):
    uid = m.from_user.id
    restore_user(uid)
    set_user_active(uid, True)
    
    await m.answer(
        f"🤖 POTA Spotter Bot\n\n"
        f"✅ Auto-updates: ACTIVE\n"
        f"⏱️ Interval: {format_interval(current_interval)}\n\n"
        f"🎚️ Bands: {get_bands_display(uid)}\n"
        f"📡 Modes: {get_modes_display(uid)}\n"
        f"🚫 Blocked: {get_blocked_display(uid)}\n\n"
        f"Use buttons below:\n\n"
        f"ℹ️ Note: If the same callsign appears multiple times, it will be shown only once.",
        reply_markup=get_main_keyboard(uid))

@dp.message(Command("stop"))
async def cmd_stop(m: types.Message):
    uid = m.from_user.id
    set_user_active(uid, False)
    await m.answer("🛑 Auto-updates STOPPED\n\nUse /start_auto or ▶️ START button to resume.", reply_markup=get_main_keyboard(uid))

@dp.message(Command("start_auto"))
async def cmd_start_auto(m: types.Message):
    uid = m.from_user.id
    set_user_active(uid, True)
    await m.answer(f"▶️ Auto-updates RESUMED\n\nInterval: {format_interval(current_interval)}", reply_markup=get_main_keyboard(uid))
    await fetch_all_for_user(uid)

@dp.message(Command("help"))
async def cmd_help(m: types.Message):
    uid = m.from_user.id
    await m.answer(
        f"📖 Commands:\n\n"
        f"/now - all current spots\n"
        f"/interval - change interval\n"
        f"/band - select bands\n"
        f"/mode - select modes (CW/SSB/DIGI)\n"
        f"/block - block prefixes (US-)\n"
        f"/stop - pause updates\n"
        f"/start_auto - resume updates\n"
        f"/reset - reset history\n"
        f"/status - your settings\n"
        f"/start - welcome\n"
        f"/help - this\n\n"
        f"Your settings:\n"
        f"• Interval: {format_interval(current_interval)}\n"
        f"• Bands: {get_bands_display(uid)}\n"
        f"• Modes: {get_modes_display(uid)}\n"
        f"• Blocked: {get_blocked_display(uid)}\n"
        f"• Status: {'ACTIVE' if is_user_active(uid) else 'PAUSED'}\n\n"
        f"ℹ️ The bot shows each callsign only once per update.",
        reply_markup=get_main_keyboard(uid))

@dp.message(Command("interval"))
async def cmd_interval(m: types.Message):
    await m.answer(f"⏱️ Current interval: {format_interval(current_interval)}\n\nSelect:", reply_markup=get_interval_keyboard())

@dp.message(Command("band"))
async def cmd_band(m: types.Message):
    uid = m.from_user.id
    await m.answer(f"🎚️ Select bands\n\nCurrent: {get_bands_display(uid)}", reply_markup=get_bands_keyboard(uid))

@dp.message(Command("mode"))
async def cmd_mode(m: types.Message):
    uid = m.from_user.id
    await m.answer(f"📡 Select modes\n\nCurrent: {get_modes_display(uid)}\n\nCW - Morse | SSB - Voice | DIGI - FT4/FT8/etc", reply_markup=get_modes_keyboard(uid))

@dp.message(Command("block"))
async def cmd_block(m: types.Message):
    uid = m.from_user.id
    await m.answer(f"🚫 Block prefixes\n\nCurrent: {get_blocked_display(uid)}\n\nExamples: US-, GB-, DE-", reply_markup=get_blocked_keyboard())

@dp.message(Command("now"))
async def cmd_now(m: types.Message):
    uid = m.from_user.id
    msg = await m.answer("📡 Fetching...")
    await fetch_all_for_user(uid)
    await msg.delete()

@dp.message(Command("reset"))
async def cmd_reset(m: types.Message):
    uid = m.from_user.id
    old = get_last_spot_id(uid)
    save_last_spot_id(uid, 0)
    await m.answer(f"🔄 History reset\n\nLast ID: {old}")
    await fetch_all_for_user(uid)

@dp.message(Command("status"))
async def cmd_status(m: types.Message):
    uid = m.from_user.id
    await m.answer(
        f"📊 Your Status\n\n"
        f"• Status: {'ACTIVE' if is_user_active(uid) else 'PAUSED'}\n"
        f"• Last spotId: {get_last_spot_id(uid)}\n"
        f"• Interval: {format_interval(current_interval)}\n"
        f"• Bands: {get_bands_display(uid)}\n"
        f"• Modes: {get_modes_display(uid)}\n"
        f"• Blocked: {get_blocked_display(uid)}\n\n"
        f"ℹ️ The bot shows each callsign only once per update.")

# ========== CALLBACKS ==========
@dp.callback_query()
async def handle_callbacks(cb: CallbackQuery):
    uid = cb.from_user.id
    data = cb.data
    global current_interval

    if data == "int_cancel":
        await cb.message.edit_text("❌ Cancelled")
    elif data == "int_custom":
        await cb.message.edit_text("📝 Send interval: 90, 3m, 1h (min 60 sec)")
    elif data.startswith("int_"):
        try:
            new = int(data.split("_")[1])
            old = current_interval
            current_interval = new
            await cb.message.edit_text(f"✅ Interval changed!\nOld: {format_interval(old)}\nNew: {format_interval(new)}")
        except:
            await cb.message.edit_text("❌ Error")

    elif data == "band_cancel":
        await cb.message.edit_text("❌ Cancelled")
    elif data == "band_apply":
        bands = get_selected_bands(uid)
        if "all" in bands and len(bands) > 1:
            bands.remove("all")
        if not bands:
            bands = ["all"]
        save_selected_bands(uid, bands)
        await cb.message.edit_text(f"✅ Bands saved!\n{get_bands_display(uid)}")
    elif data == "band_all":
        save_selected_bands(uid, ["all"])
        await cb.message.edit_text("🎚️ All bands selected", reply_markup=get_bands_keyboard(uid))
    elif data == "band_clear":
        save_selected_bands(uid, [])
        await cb.message.edit_text("🎚️ Cleared", reply_markup=get_bands_keyboard(uid))
    elif data.startswith("band_"):
        band = data.replace("band_", "")
        if band not in ["apply", "cancel", "all", "clear"]:
            bands = get_selected_bands(uid)
            if band in bands:
                bands.remove(band)
            else:
                if "all" in bands:
                    bands.remove("all")
                bands.append(band)
            save_selected_bands(uid, bands)
            await cb.message.edit_text(f"🎚️ Current: {get_bands_display(uid)}", reply_markup=get_bands_keyboard(uid))

    elif data == "mode_cancel":
        await cb.message.edit_text("❌ Cancelled")
    elif data == "mode_apply":
        modes = get_selected_modes(uid)
        if "all" in modes and len(modes) > 1:
            modes.remove("all")
        if not modes:
            modes = ["all"]
        save_selected_modes(uid, modes)
        await cb.message.edit_text(f"✅ Modes saved!\n{get_modes_display(uid)}")
    elif data == "mode_all":
        save_selected_modes(uid, ["all"])
        await cb.message.edit_text("📡 All modes selected", reply_markup=get_modes_keyboard(uid))
    elif data == "mode_clear":
        save_selected_modes(uid, [])
        await cb.message.edit_text("📡 Cleared", reply_markup=get_modes_keyboard(uid))
    elif data.startswith("mode_"):
        mode = data.replace("mode_", "")
        if mode in ["CW", "SSB", "DIGI"]:
            modes = get_selected_modes(uid)
            if mode in modes:
                modes.remove(mode)
            else:
                if "all" in modes:
                    modes.remove("all")
                modes.append(mode)
            save_selected_modes(uid, modes)
            await cb.message.edit_text(f"📡 Current: {get_modes_display(uid)}", reply_markup=get_modes_keyboard(uid))

    elif data == "block_cancel":
        await cb.message.edit_text("❌ Cancelled")
    elif data == "block_add":
        await cb.message.edit_text("📝 Send prefix to block (e.g., US-)\nExamples: US-, GB-, DE-")
    elif data == "block_clear":
        save_blocked_prefixes(uid, [])
        await cb.message.edit_text(f"✅ All cleared!\nBlocked: {get_blocked_display(uid)}")
    elif data == "block_show":
        blocked = get_blocked_prefixes(uid)
        if not blocked:
            await cb.message.edit_text("📋 No blocked prefixes")
        else:
            await cb.message.edit_text("📋 Blocked prefixes\n\nClick to remove:", reply_markup=get_blocked_list_keyboard(uid))
    elif data == "block_back":
        await cb.message.edit_text(f"🚫 Block prefixes\nCurrent: {get_blocked_display(uid)}", reply_markup=get_blocked_keyboard())
    elif data.startswith("block_remove_"):
        prefix = data.replace("block_remove_", "")
        blocked = get_blocked_prefixes(uid)
        if prefix in blocked:
            blocked.remove(prefix)
            save_blocked_prefixes(uid, blocked)
        await cb.message.edit_text(f"✅ Removed {prefix}\nBlocked: {get_blocked_display(uid)}", reply_markup=get_blocked_list_keyboard(uid) if blocked else get_blocked_keyboard())

    await cb.answer()

# ========== TEXT HANDLERS ==========
@dp.message(lambda m: m.text and m.text.strip().upper().endswith('-') and len(m.text.strip()) <= 10)
async def add_blocked_text(m: types.Message):
    uid = m.from_user.id
    prefix = m.text.strip().upper()
    if not prefix.endswith('-'):
        await m.answer("❌ Must end with '-'")
        return
    blocked = get_blocked_prefixes(uid)
    if prefix in blocked:
        await m.answer(f"❌ {prefix} already blocked")
        return
    blocked.append(prefix)
    save_blocked_prefixes(uid, blocked)
    await m.answer(f"✅ Added {prefix}\nBlocked: {get_blocked_display(uid)}")

@dp.message(lambda m: m.text and m.text.isdigit())
async def set_interval_num(m: types.Message):
    try:
        new = int(m.text)
        if new < MIN_INTERVAL:
            await m.answer(f"❌ Min {MIN_INTERVAL} sec")
            return
        global current_interval
        old = current_interval
        current_interval = new
        await m.answer(f"✅ Interval set!\nOld: {format_interval(old)}\nNew: {format_interval(new)}")
    except:
        await m.answer("❌ Invalid")

@dp.message(lambda m: m.text and (m.text.endswith('m') or m.text.endswith('h')))
async def set_interval_custom(m: types.Message):
    try:
        txt = m.text.lower()
        if txt.endswith('h'):
            new = int(txt[:-1]) * 3600
        else:
            new = int(txt[:-1]) * 60
        if new < MIN_INTERVAL:
            await m.answer(f"❌ Min {MIN_INTERVAL} sec")
            return
        global current_interval
        old = current_interval
        current_interval = new
        await m.answer(f"✅ Interval set!\nOld: {format_interval(old)}\nNew: {format_interval(new)}")
    except:
        await m.answer("❌ Invalid. Use: 90, 3m, 1h")

# ========== BUTTON HANDLERS ==========
@dp.message(lambda m: m.text == "🔄 Now")
async def btn_now(m): await cmd_now(m)
@dp.message(lambda m: m.text == "⏱️ Set Interval")
async def btn_interval(m): await cmd_interval(m)
@dp.message(lambda m: m.text == "🎚️ Set Band")
async def btn_band(m): await cmd_band(m)
@dp.message(lambda m: m.text == "📡 Set Mode")
async def btn_mode(m): await cmd_mode(m)
@dp.message(lambda m: m.text == "🚫 Block Reference")
async def btn_block(m): await cmd_block(m)
@dp.message(lambda m: m.text == "🛑 STOP")
async def btn_stop(m): await cmd_stop(m)
@dp.message(lambda m: m.text == "▶️ START")
async def btn_start(m): await cmd_start_auto(m)
@dp.message(lambda m: m.text == "📊 Status")
async def btn_status(m): await cmd_status(m)
@dp.message(lambda m: m.text == "🔄 Reset History")
async def btn_reset(m): await cmd_reset(m)
@dp.message(lambda m: m.text == "❓ Help")
async def btn_help(m): await cmd_help(m)

# ========== MAIN ==========
async def main():
    global update_task
    logging.info(f"Starting POTA bot for {len(users_config)} users...")
    logging.info(f"Bot token loaded from environment variable")
    update_task = asyncio.create_task(periodic_check())
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Bot stopped")
        if update_task:
            update_task.cancel()
    except Exception as e:
        logging.error(f"Fatal: {e}")