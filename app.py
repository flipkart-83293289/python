import os
import re
import io
import json
import asyncio
import time
import requests
from threading import Thread
from flask import Flask
from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
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
DB_CHANNEL_ID = -1003936910985
LOGO_URL_FALLBACK = "https://ik.imagekit.io/Rajmalik99/1786595036231.png"
BOT_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GOOGLE_WEBAPP_URL = os.environ.get("GOOGLE_WEBAPP_URL")
SEARCH_API_URL = "https://searchapi-abch.onrender.com/search"

admin_sessions = {}
click_locks = set()

flask_app = Flask(__name__)
@flask_app.route('/')
def home(): return "Rebrand Server Online"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    flask_app.run(host="0.0.0.0", port=port)

# ---------------- CORE UTILS ---------------- #

def format_inr(number_val) -> str:
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

async def sync_user_to_db(context, user_id, points, status="Active"):
    user_records = context.bot_data.setdefault("user_records", {})
    user_records[user_id] = {
        "userid": user_id,
        "discountpoint": points,
        "status": status
    }
    # Payload for Google Sheets
    payload = {"action": "sync_user", "userid": str(user_id), "discountpoint": points, "status": status}
    try: requests.post(GOOGLE_WEBAPP_URL, json=payload, timeout=10)
    except: pass

async def get_search_suggestions(target_price):
    """Search for electronics in the target price range (Target to Target + 2000)"""
    try:
        upper_bound = target_price + 2000
        # Searching for 'electronics' to get a wide variety
        resp = requests.get(f"{SEARCH_API_URL}?q=electronics", timeout=15)
        if resp.status_code == 200:
            products = resp.json() # Assuming it returns a list of product objects
            suggestions = []
            for p in products:
                # Clean price from API
                p_price = int(re.sub(r'\D', '', str(p.get('price', '0'))))
                if target_price <= p_price <= upper_bound:
                    suggestions.append(f"• {p.get('title')[:40]}... - ₹{p_price}")
                if len(suggestions) >= 5: break
            return "\n".join(suggestions) if suggestions else "No electronics found in this range."
    except:
        return "Search API Error."
    return "No suggestions found."

def fetch_flipkart_metadata(url: str):
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0"})
    try:
        resp = session.get(url, timeout=10)
        html = resp.text
        # Title
        title = "Flipkart Product"
        title_match = re.search(r'<title>(.*?)</title>', html, re.I)
        if title_match: title = title_match.group(1).split('|')[0].strip()

        # Price Detection
        price = 0
        sp_matches = re.findall(r'class=["\'][^"\']*(?:Nx9bqj|_30jeq3)[^"\']*["\'][^>]*>₹?\s*([\d,]+)', html)
        if sp_matches:
            price = int(re.sub(r'\D', '', sp_matches[0]))
        
        # Image
        img_url = None
        og_image = re.search(r'property="og:image" content="(.*?)"', html)
        if og_image: img_url = og_image.group(1)
        
        img_bytes = None
        if img_url:
            img_res = session.get(img_url)
            if img_res.status_code == 200: img_bytes = img_res.content

        return title, price, img_bytes
    except:
        return "Unknown Product", 0, None

# ---------------- HANDLERS ---------------- #

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_records = context.bot_data.setdefault("user_records", {})
    
    # 1 Free Point for new users
    if user_id not in user_records:
        await sync_user_to_db(context, user_id, 1)
        welcome = f"Hello {update.effective_user.first_name}! You received 1 Free Discount Point for joining."
    else:
        welcome = f"Welcome back, {update.effective_user.first_name}!"

    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🚀 Get Discount Now", callback_data="direct_start")]])
    await update.message.reply_text(welcome, reply_markup=kb)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data
    await query.answer()

    user_records = context.bot_data.get("user_records", {})
    pts = user_records.get(user_id, {}).get("discountpoint", 0)

    if data == "direct_start":
        if pts <= 0:
            await query.message.reply_text("❌ You have 0 points.")
            return
        context.user_data["state"] = "WAITING_LINK"
        await query.message.reply_text("Please send your Flipkart Product Link:")

    elif data == "continue_submit":
        # Deduct point
        new_pts = pts - 1
        await sync_user_to_db(context, user_id, new_pts)
        
        # Notify Admin + Suggestions
        p_price = context.user_data.get("product_price", 0)
        target_val = int(p_price * 0.65)
        suggestions = await get_search_suggestions(target_val)
        
        admin_msg = (
            f"📥 <b>New Request</b>\n"
            f"User: <code>{user_id}</code>\n"
            f"Product: {context.user_data.get('product_name')}\n"
            f"Price: {format_inr(p_price)}\n"
            f"Mobile: {context.user_data.get('mobile_num')}\n\n"
            f"💡 <b>Admin Recommendations (Electronics ~35% off):</b>\n{suggestions}"
        )
        await context.bot.send_message(chat_id=ADMIN_ID, text=admin_msg, parse_mode="HTML")
        await query.message.reply_text("✅ Submitted! Waiting for Admin verification.")

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = context.user_data.get("state")
    text = update.message.text
    user_id = update.effective_user.id

    if state == "WAITING_LINK":
        title, price, img = fetch_flipkart_metadata(text)
        
        # Error or Price detection failure
        if price == 0:
            await update.message.reply_text("❌ Could not detect price. Try a different link.")
            return

        # NEW RULE: Under 10k check
        if price < 10000:
            await asyncio.sleep(2) # Brief pause to simulate check
            await update.message.reply_text("❌ Offer is not available for this product (Price below 10k).")
            return

        context.user_data.update({"product_name": title, "product_price": price, "product_link": text})
        context.user_data["state"] = "WAITING_MOB"
        await update.message.reply_text(f"Product: {title}\nPrice: {format_inr(price)}\n\nSend your Flipkart Mobile Number:")

    elif state == "WAITING_MOB":
        context.user_data["mobile_num"] = text
        context.user_data["state"] = None
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("Confirm & Use 1 Point", callback_data="continue_submit")]])
        await update.message.reply_text("Confirm details to proceed:", reply_markup=kb)

# ---------------- MAIN ---------------- #

def main():
    Thread(target=run_flask, daemon=True).start()
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

    print("Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
