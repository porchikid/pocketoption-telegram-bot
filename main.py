import os
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import websocket
import json
import time

# CONFIGURE THESE:
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
POCKET_OPTION_TOKEN = os.getenv("POCKET_OPTION_TOKEN")
USER_ID = int(os.getenv("USER_ID"))

bot = telebot.TeleBot(TELEGRAM_TOKEN)
user_data = {}
trade_stats = {"total": 0, "wins": 0, "losses": 0}

def send_auth(ws):
    auth_payload = '42' + json.dumps(["auth", {
        "session": POCKET_OPTION_TOKEN,
        "uid": USER_ID,
        "lang": "en"
    }])
    ws.send(auth_payload)

@bot.message_handler(commands=['start'])
def start(message):
    user_data[message.chat.id] = {"mode": "demo"}
    markup = InlineKeyboardMarkup()
    pairs = ["EURUSD", "USDJPY", "GBPUSD", "EURUSD_otc", "USDJPY_otc"]
    for pair in pairs:
        markup.add(InlineKeyboardButton(pair, callback_data=f"pair:{pair}"))
    bot.send_message(message.chat.id, "⚠️ *You are currently trading in DEMO mode.*", parse_mode="Markdown")
    bot.send_message(message.chat.id, "Select a pair:", reply_markup=markup, parse_mode='Markdown')

@bot.message_handler(commands=['check'])
def check_balance(message):
    try:
        ws = websocket.create_connection("wss://socket.pocketoption.com/socket.io/?EIO=3&transport=websocket")
        send_auth(ws)
        time.sleep(1)
        ws.send('42["get_balances",{}]')
        time.sleep(1)
        response = ws.recv()
        ws.close()
        bot.send_message(message.chat.id, f"💰 Balance Info (raw):\n{response}")
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Could not check balance: {e}")

@bot.message_handler(commands=['stats'])
def check_stats(message):
    bot.send_message(message.chat.id, f"📊 Trades: {trade_stats['total']} | Wins: {trade_stats['wins']} | Losses: {trade_stats['losses']}")

@bot.callback_query_handler(func=lambda call: True)
def handle_query(call):
    cid = call.message.chat.id
    data = call.data

    if data.startswith("pair:"):
        pair = data.split(":")[1]
        user_data[cid]["pair"] = pair
        markup = InlineKeyboardMarkup()
        for amt in [1, 5, 10]:
            markup.add(InlineKeyboardButton(f"${amt}", callback_data=f"amount:{amt}"))
        bot.edit_message_text("Select trade amount:", cid, call.message.message_id, reply_markup=markup)

    elif data.startswith("amount:"):
        amt = int(data.split(":")[1])
        user_data[cid]["amount"] = amt
        markup = InlineKeyboardMarkup()
        for sec in [30, 60, 120]:
            markup.add(InlineKeyboardButton(f"{sec}s", callback_data=f"time:{sec}"))
        bot.edit_message_text("Select trade duration:", cid, call.message.message_id, reply_markup=markup)

    elif data.startswith("time:"):
        secs = int(data.split(":")[1])
        user_data[cid]["time"] = secs
        markup = InlineKeyboardMarkup()
        markup.row(
            InlineKeyboardButton("📈 Buy", callback_data="action:buy"),
            InlineKeyboardButton("📉 Sell", callback_data="action:sell")
        )
        bot.edit_message_text("Choose Buy or Sell:", cid, call.message.message_id, reply_markup=markup)

    elif data.startswith("action:"):
        action = data.split(":")[1]
        info = user_data.get(cid, {})
        try:
            ws = websocket.create_connection("wss://socket.pocketoption.com/socket.io/?EIO=3&transport=websocket")
            send_auth(ws)
            time.sleep(1)
            trade_data = {
                "market": info["pair"],
                "price": info["amount"],
                "type": action,
                "time": info["time"]
            }
            ws.send('42' + json.dumps(["buyv3", trade_data]))
            time.sleep(1.5)
            ws.close()

            trade_stats["total"] += 1
            bot.send_message(cid, f"✅ {action.upper()} placed for {info['pair']} — ${info['amount']} / {info['time']}s")
        except Exception as e:
            trade_stats["losses"] += 1
            bot.send_message(cid, f"❌ Error placing trade: {e}")

bot.polling()
