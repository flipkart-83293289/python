import os
import re
import io
import json
import asyncio
import requests
from threading import Thread
from flask import Flask
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
BOT_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GOOGLE_WEBAPP_URL = os.environ.get("GOOGLE_WEBAPP_URL")
SEARCH_API_URL = "https://searchapi-abch.onrender.com/search"

# Gunicorn looks for 'app' variable in 'app.py'
app = Flask(__name__)

@app.route('/')
def home():
    return "Rebrand Server Online 24/7"

# ---------------- UTILS ---------------- #

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

async def sync_user_data(context, user_id, points):
    user_records = context.bot_data.setdefault("user_records", {})
    user_records[user_id] = {"userid": user_id, "discountpoint": points}
    payload = {"action": "sync_user", "userid": str(user_id), "discountpoint": points}
    try:
        requests.post(GOOGLE_WEBAPP_URL, json=payload, timeout=8)
    except:
        pass

async def get_search_recommendations(orig_price):
    """Calculate 35% off, then find 5 items in [Target to Target+2000] range"""
    try:
        target = int(orig_price * 0.65)  # 35% discount
        upper_limit = target + 2000
        
        # Search API Call for Electronics
        resp = requests.get(f"{SEARCH_API_URL}?q=electronics", timeout=15)
        if resp.status_code == 200:
            all_products = resp.json()
            matches = []
            for item in all_products:
                raw_p = str(item.get("price", "0"))
                p_val = int(re.sub(r'\D', '', raw_p)) if re.sub(r'\D', '', raw_p) else 0
                
                if target <= p_val <= upper_limit:
                    matches.append(f"• {item.get('title')[:35]}... - ₹{p_val}")
                
                if len(matches) >= 5: break
            
            return "\n".join(matches) if matches else "No similar electronics in this price range."
    except Exception as e:
        return f"Search API error: {str(e)}"
    return "Could not fetch suggestions."

def get_flipkart_details(url: str):
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0"})
    try:
        res = session.get(url, timeout=10)
        html = res.text
        
        # Extract Title
        title = "Flipkart Product"
        t_match = re.search(r'<title>(.*?)</title>', html, re.I)
        if t_match: title = t_match.group(1).split('|')[0].strip()

        # Extract Price
        price = 0
        p_matches = re.findall(r'class=["\'][^"\']*(?:Nx9bqj|_30jeq3)[^"\']*["\'][^>]*>₹?\s*([\d,]+)', html)
        if p_matches:
            price = int(re.sub(r'\D', '', p_matches[0]))

        # Extract Image
        img_bytes = None
        img_url_match = re.search(r'property="og:image" content="(.*?)"', html)
        if img_url_match:
            img_res = session.get(img_url_match.group(1))
            if img_res.status_code == 200: img_bytes = img_res.content
            
        return title, price, img_bytes
    except:
        return "Unknown", 0, None

# ---------------- BOT LOGIC ---------------- #

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    user_records = context.bot_data.setdefault("user_records", {})
    
    # 1 Free point for new users
    if uid not in user_records:
        await sync_user_data(context, uid, 1)
        welcome = f"Hello {update.effective_user.first_name}!\nYou have received <b>1 Free Discount Point</b> as a joining bonus."
    else:
        pts = user_records[uid].get("discountpoint", 0)
        welcome = f"Welcome back! You have <b>{pts} Discount Points</b>."

    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🚀 Start Liquidating", callback_data="begin")]])
    await update.message.reply_text(welcome, parse_mode="HTML", reply_markup=kb)

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid = query.from_user.id
    await query.answer()

    user_records = context.bot_data.get("user_records", {})
    pts = user_records.get(uid, {}).get("discountpoint", 0)

    if query.data == "begin":
        if pts <= 0:
            await query.message.reply_text("❌ You have 0 points left.")
            return
        context.user_data["step"] = "GET_URL"
        await query.message.reply_text("Please send the Flipkart Product Link:")

    elif query.data == "confirm_req":
        # Final Step: Deduct point and Notify Admin
        new_pts = pts - 1
        await sync_user_data(context, uid, new_pts)
        
        orig_p = context.user_data.get("p_price", 0)
        await query.edit_message_text("⏳ Processing your request with Admin recommendations...")
        
        # Get Suggestions for Admin
        recs = await get_search_recommendations(orig_p)
        
        admin_report = (
            f"👑 <b>NEW DISCOUNT REQUEST</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 <b>User ID:</b> <code>{uid}</code>\n"
            f"📱 <b>Mobile:</b> <code>{context.user_data.get('mob')}</code>\n"
            f"📦 <b>Product:</b> {context.user_data.get('p_title')}\n"
            f"💰 <b>Orig Price:</b> {format_inr(orig_p)}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"💡 <b>Suggested Items (Electronic ~35% Off):</b>\n{recs}"
        )
        await context.bot.send_message(chat_id=ADMIN_ID, text=admin_report, parse_mode="HTML")
        await query.message.reply_text("✅ Submitted! Please wait for Admin to verify and send your link.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    step = context.user_data.get("step")
    txt = update.message.text
    
    if step == "GET_URL":
        status_msg = await update.message.reply_text("🔍 Fetching product details...")
        title, price, img = get_flipkart_details(txt)
        await status_msg.delete()

        if price == 0:
            await update.message.reply_text("❌ Price detection failed. Please send a valid Flipkart link.")
            return

        # 10k Rule with delay
        if price < 10000:
            # We don't block the bot, we just wait to simulate a "check"
            await asyncio.sleep(2) 
            await update.message.reply_text("❌ Offer is not available for this product (Price is under ₹10,000).")
            context.user_data["step"] = None
            return

        context.user_data.update({"p_title": title, "p_price": price, "p_img": img, "step": "GET_MOB"})
        await update.message.reply_text(f"✅ <b>Product Found:</b>\n{title}\nPrice: {format_inr(price)}\n\n<b>Send Flipkart Mobile Number:</b>", parse_mode="HTML")

    elif step == "GET_MOB":
        context.user_data["mob"] = txt
        context.user_data["step"] = None
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("Confirm & Use 1 Point", callback_data="confirm_req")]])
        summary = f"Confirm your request:\n\nProduct: {context.user_data['p_title']}\nMobile: {txt}"
        await update.message.reply_text(summary, reply_markup=kb)

# ---------------- RUNNER ---------------- #

def start_telegram():
    # Persistence not used here as per your simple requirements
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(handle_callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.run_polling()

if __name__ == "__main__":
    # Start bot in background
    Thread(target=start_telegram, daemon=True).start()
    
    # Start Flask on Main Thread for Render Port detection
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
