import os
import requests
from flask import Flask, request

app = Flask(__name__)

# --- Config: set these as Environment Variables on Render, not hardcoded here ---
BOT_TOKEN = os.environ["BOT_TOKEN"]              # your Telegram bot token from @BotFather
SCRAPER_API = os.environ["SCRAPER_API_URL"].rstrip("/")  # e.g. https://searchapi-abch.onrender.com
TG_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

# Simple in-memory per-user conversation state.
# NOTE: this resets whenever the Render service restarts/spins down (free tier).
# { chat_id: {"stage": "idle" | "awaiting_product" | "awaiting_price", "product": "..."} }
user_state = {}


def send_message(chat_id, text):
    requests.post(f"{TG_API}/sendMessage", json={"chat_id": chat_id, "text": text})


def send_photo(chat_id, photo_url, caption):
    requests.post(
        f"{TG_API}/sendPhoto",
        json={"chat_id": chat_id, "photo": photo_url, "caption": caption},
    )


@app.route("/", methods=["GET"])
def health():
    # Render (and you, manually) can hit this to confirm the service is alive.
    return "Bot is running.", 200


@app.route("/webhook", methods=["POST"])
def webhook():
    update = request.get_json(silent=True) or {}
    message = update.get("message")
    if not message or "text" not in message:
        return "ok"

    chat_id = message["chat"]["id"]
    text = message["text"].strip()
    state = user_state.get(chat_id, {"stage": "idle"})

    if text == "/start" or state["stage"] == "idle":
        user_state[chat_id] = {"stage": "awaiting_product"}
        send_message(chat_id, "What product are you looking for?")

    elif state["stage"] == "awaiting_product":
        user_state[chat_id] = {"stage": "awaiting_price", "product": text}
        send_message(chat_id, "What's your price range? (e.g. 2000-8000)")

    elif state["stage"] == "awaiting_price":
        try:
            low, high = (int(x.strip()) for x in text.split("-"))
        except ValueError:
            send_message(chat_id, "Please send it like: 2000-8000")
            return "ok"

        product = state["product"]

        try:
            resp = requests.get(f"{SCRAPER_API}/search/{product}", timeout=20)
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            send_message(chat_id, "Couldn't reach the search service right now. Try again in a bit.")
            user_state[chat_id] = {"stage": "idle"}
            return "ok"

        items = data.get("result", [])
        filtered = [
            i for i in items
            if i.get("current_price") is not None and low <= i["current_price"] <= high
        ]

        if not filtered:
            send_message(chat_id, f"No results for '{product}' between â‚¹{low} and â‚¹{high}.")
        else:
            for item in filtered[:10]:  # cap so we don't spam
                caption = (
                    f"{item['name']}\n"
                    f"â‚¹{item['current_price']} (was â‚¹{item['original_price']})\n"
                    f"{item['link']}"
                )
                send_photo(chat_id, item["thumbnail"], caption)

        user_state[chat_id] = {"stage": "idle"}

    return "ok"


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
