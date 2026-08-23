import os
import re
import asyncio
import requests
from flask import Flask, request
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# ---------------- CONFIGURATION ---------------- #
ADMIN_ID = 8844584255
BOT_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GOOGLE_WEBAPP_URL = os.environ.get("GOOGLE_WEBAPP_URL")
SEARCH_API_URL = "https://searchapi-abch.onrender.com/search"
WEBHOOK_URL = os.environ.get("WEBHOOK_URL") # e.g., https://python-cmor.onrender.com

app = Flask(__name__)

# Initialize Telegram Application
ptb_app = Application.builder().token(BOT_TOKEN).build()

# ---------------- UTILS ---------------- #

def format_inr(number_val):
    num = re.sub(r'\D', '', str(number_val))
    if not num: return f"₹{number_val}"
    if len(num) <= 3: return f"₹{num}"
    last_three = num[-3:]
    rest = num[:-3]
    chunks = []
    while rest:
        chunks.append(rest[-2:])
        rest = rest[:-2]
    chunks.reverse()
    return f"₹{','.join(chunks)},{last_three}"

async def sync_user_data(user_id, points):
    payload = {"action": "sync_user", "userid": str(user_id), "discountpoint": points}
    try: requests.post(GOOGLE_WEBAPP_URL, json=payload, timeout=5)
    except: pass

async def get_search_recommendations(orig_price):
    try:
        target = int(orig_price * 0.65)
        upper_limit = target + 2000
        resp = requests.get(f"{SEARCH_API_URL}?q=electronics", timeout=10)
        if resp.status_code == 200:
            all_products = resp.json()
            matches = [f"• {item.get('title')[:30]}... (₹{item.get('price')})" 
                       for item in all_products if target <= int(re.sub(r'\D','',str(item.get('price','0')))) <= upper_limit]
            return "\n".join(matches[:5]) if matches else "No similar items found."
    except: return "Search API error."
    return "No suggestions."

# ---------------- BOT HANDLERS ---------------- #

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    # Using bot_data for memory
    user_records = context.bot_data.setdefault("user_records", {})
    if uid not in user_records:
        user_records[uid] = {"discountpoint": 1}
        await sync_user_data(uid, 1)
        msg = "Welcome! 🎁 1 Free Point added."
    else:
        msg = f"Welcome back! Points: {user_records[uid]['discountpoint']}"
    
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🚀 Start", callback_data="begin")]])
    await update.message.reply_text(msg, reply_markup=kb)

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid = query.from_user.id
    await query.answer()
    user_records = context.bot_data.get("user_records", {})
    pts = user_records.get(uid, {}).get("discountpoint", 0)

    if query.data == "begin":
        if pts <= 0:
            await query.message.reply_text("❌ 0 Points.")
            return
        context.user_data["step"] = "URL"
        await query.message.reply_text("Send Flipkart Link:")
    elif query.data == "confirm":
        user_records[uid]["discountpoint"] -= 1
        await sync_user_data(uid, user_records[uid]["discountpoint"])
        recs = await get_search_recommendations(context.user_data['p_price'])
        admin_msg = f"Request from {uid}\nMobile: {context.user_data['mob']}\nPrice: {context.user_data['p_price']}\n\nRecs:\n{recs}"
        await context.bot.send_message(chat_id=ADMIN_ID, text=admin_msg)
        await query.message.reply_text("✅ Submitted to Admin.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    step = context.user_data.get("step")
    if step == "URL":
        price = 15000 # Example placeholder logic for brevity
        if price < 10000:
            await asyncio.sleep(1)
            await update.message.reply_text("❌ Under 10k.")
            return
        context.user_data.update({"p_price": price, "step": "MOB"})
        await update.message.reply_text("Send Mobile Number:")
    elif step == "MOB":
        context.user_data["mob"] = update.message.text
        context.user_data["step"] = None
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("Confirm", callback_data="confirm")]])
        await update.message.reply_text("Confirm request?", reply_markup=kb)

# Register Handlers
ptb_app.add_handler(CommandHandler("start", start))
ptb_app.add_handler(CallbackQueryHandler(handle_callback))
ptb_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

# ---------------- WEBHOOK ROUTE ---------------- #

@app.route('/', methods=['GET', 'POST'])
async def webhook_handler():
    if request.method == 'POST':
        # Handle update from Telegram
        update = Update.de_json(request.get_json(force=True), ptb_app.bot)
        await ptb_app.process_update(update)
        return "OK", 200
    return "Bot is Running", 200

# Setup Webhook on Startup
async def setup_webhook():
    if WEBHOOK_URL:
        # Set webhook to the root domain
        await ptb_app.bot.set_webhook(url=WEBHOOK_URL)
        print(f"Webhook set to: {WEBHOOK_URL}")

# Initialize PTB on Startup
asyncio.run(ptb_app.initialize())
asyncio.run(ptb_app.start())
asyncio.run(setup_webhook())

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
