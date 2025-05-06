from flask import Flask
import threading
import main  # this imports and starts your Telegram bot

app = Flask(__name__)

@app.route('/')
def index():
    return "PocketOption Bot is running."

# Bot already starts from main.py during import