import os
import logging
import requests
from flask import Flask, request

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("bot")

app = Flask(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
SCRAPER_API = os.environ.get("SCRAPER_API_URL", "").rstrip("/")
TG_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

if not BOT_TOKEN:
    log.error("BOT_TOKEN is not set! Check Render Environment tab.")
if not SCRAPER_API:
    log.error("SCRAPER_API_URL is not set! Check Render Environment tab.")

user_state = {}


def send_message(chat_id, text):
    r = requests.post(f"{TG_API}/sendMessage", json={"chat_id": chat_id, "text": text})
    log.info("sendMessage -> %s %s", r.status_code, r.text[:300])


def send_photo(chat_id, photo_url, caption):
    r = requests.post(
        f"{TG_API}/sendPhoto",
        json={"chat_id": chat_id, "photo": photo_url, "caption": caption},
    )
    log.info("sendPhoto -> %s %s", r.status_code, r.text[:300])


@app.route("/", methods=["GET"])
def health():
    return "Bot is running.", 200


@app.route("/set_webhook", methods=["GET"])
def set_webhook():
    webhook_url = request.url_root.rstrip("/") + "/webhook"
    r = requests.get(f"{TG_API}/setWebhook", params={"url": webhook_url})
    log.info("setWebhook -> %s", r.text)
    return r.json()


@app.route("/webhook_info", methods=["GET"])
def webhook_info():
    r = requests.get(f"{TG_API}/getWebhookInfo")
    return r.json()


@app.route("/webhook", methods=["POST"])
def webhook():
    update = request.get_json(silent=True) or {}
    log.info("Incoming update: %s", update)

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
            log.exception("Scraper API call failed")
            send_message(chat_id, "Couldn't reach the search service right now. Try again in a bit.")
            user_state[chat_id] = {"stage": "idle"}
            return "ok"

        items = data.get("result", [])
        filtered = [
            i for i in items
            if i.get("current_price") is not None and low <= i["current_price"] <= high
        ]

        if not filtered:
            send_message(chat_id, f"No results for '{product}' between price {low} and {high}.")
        else:
            for item in filtered[:10]:
                caption = (
                    f"{item['name']}\n"
                    f"Price {item['current_price']} (was {item['original_price']})\n"
                    f"{item['link']}"
                )
                send_photo(chat_id, item["thumbnail"], caption)

        user_state[chat_id] = {"stage": "idle"}

    return "ok"


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
