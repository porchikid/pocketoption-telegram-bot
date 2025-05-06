import os
import json
import time
import threading
import datetime
import requests
import telebot
import websocket
import numpy as np
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

# === CONFIG ===
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
POCKET_OPTION_TOKEN = os.getenv("POCKET_OPTION_TOKEN")
USER_ID = int(os.getenv("USER_ID"))

SPREADSHEET_URL = "https://docs.google.com/spreadsheets/d/1VgO6Denw1tdgbYozTTXby3TagZCTbSItYGMVzP_8dJg"
SERVICE_ACCOUNT_FILE = "credentials.json"

bot = telebot.TeleBot(TELEGRAM_TOKEN)
user_data = {}
trade_stats = {"total": 0, "wins": 0, "losses": 0}
auto_thread = None
auto_running = False

# === Google Sheets Setup ===
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_name(SERVICE_ACCOUNT_FILE, scope)
sheet_client = gspread.authorize(creds)
sheet = sheet_client.open_by_url(SPREADSHEET_URL).sheet1

def log_to_sheet(data):
    sheet.append_row([
        data.get("timestamp"),
        data.get("pair"),
        data.get("rsi"),
        data.get("action"),
        data.get("status")
    ])

def get_binance_rsi(symbol="BTCUSDT", interval="1m", period=14):
    try:
        url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={period+1}"
        response = requests.get(url).json()
        closes = [float(candle[4]) for candle in response]
        deltas = np.diff(closes)
        seed = deltas[:period]
        up = seed[seed > 0].sum() / period
        down = -seed[seed < 0].sum() / period
        rs = up / down if down else 0
        rsi = 100 - (100 / (1 + rs))
        return round(rsi, 2)
    except Exception as e:
        return None

def market_is_open(pair):
    if "_otc" in pair.lower():
        return True
    return datetime.datetime.utcnow().weekday() < 5

def send_auth(ws):
    auth_payload = '42' + json.dumps(["auth", {
        "session": POCKET_OPTION_TOKEN,
        "uid": USER_ID,
        "lang": "en"
    }])
    ws.send(auth_payload)

def place_trade(pair, amount, action, duration):
    try:
        ws = websocket.create_connection("wss://socket.pocketoption.com/socket.io/?EIO=3&transport=websocket")
        send_auth(ws)
        time.sleep(1)
        trade_data = {
            "market": pair,
            "price": amount,
            "type": action,
            "time": duration
        }
        ws.send('42' + json.dumps(["buyv3", trade_data]))
        time.sleep(1)
        ws.close()
        return "✅ Executed"
    except Exception as e:
        return f"❌ {str(e)}"

def auto_trade_loop(chat_id):
    global auto_running
    while auto_running:
        info = user_data.get(chat_id, {"pair": "EURUSD_otc", "amount": 1, "time": 60})
        pair = info["pair"]
        amount = info["amount"]
        duration = info["time"]

        if not market_is_open(pair):
            bot.send_message(chat_id, "⛔ Market is currently closed for that pair.")
            time.sleep(60)
            continue

        rsi = get_binance_rsi("BTCUSDT")  # Could be mapped to forex-like proxy
        if rsi is None:
            bot.send_message(chat_id, "⚠️ Failed to fetch RSI.")
            time.sleep(60)
            continue

        if rsi < 30:
            action = "buy"
        elif rsi > 70:
            action = "sell"
        else:
            bot.send_message(chat_id, f"RSI: {rsi} ➤ Hold (no action)")
            time.sleep(60)
            continue

        status = place_trade(pair, amount, action, duration)
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_to_sheet({
            "timestamp": timestamp,
            "pair": pair,
            "rsi": rsi,
            "action": action,
            "status": status
        })
        bot.send_message(chat_id, f"🔁 {action.upper()} | {pair} | RSI: {rsi} → {status}")
        time.sleep(60)

@bot.message_handler(commands=['start'])
def start(message):
    cid = message.chat.id
    user_data[cid] = {"pair": "EURUSD_otc", "amount": 1, "time": 60}
    markup = InlineKeyboardMarkup()
    for pair in ["EURUSD", "EURUSD_otc"]:
        markup.add(InlineKeyboardButton(pair, callback_data=f"pair:{pair}"))
    bot.send_message(cid, "⚠️ *You are currently trading in DEMO mode.*", parse_mode="Markdown")
    bot.send_message(cid, "Select a pair:", reply_markup=markup)

@bot.message_handler(commands=['setpair'])
def set_pair(message):
    try:
        pair = message.text.split()[1]
        user_data[message.chat.id]["pair"] = pair
        bot.send_message(message.chat.id, f"✅ Pair set to {pair}")
    except:
        bot.send_message(message.chat.id, "Usage: /setpair EURUSD_otc")

@bot.message_handler(commands=['setamount'])
def set_amount(message):
    try:
        amount = float(message.text.split()[1])
        user_data[message.chat.id]["amount"] = amount
        bot.send_message(message.chat.id, f"✅ Amount set to ${amount}")
    except:
        bot.send_message(message.chat.id, "Usage: /setamount 5")

@bot.message_handler(commands=['auto_on'])
def auto_on(message):
    global auto_thread, auto_running
    if auto_running:
        bot.send_message(message.chat.id, "Already running.")
        return
    auto_running = True
    auto_thread = threading.Thread(target=auto_trade_loop, args=(message.chat.id,))
    auto_thread.start()
    bot.send_message(message.chat.id, "🤖 Auto trading started.")

@bot.message_handler(commands=['auto_off'])
def auto_off(message):
    global auto_running
    auto_running = False
    bot.send_message(message.chat.id, "🛑 Auto trading stopped.")

bot.polling()
