
import logging
import phonenumbers
from phonenumbers import geocoder, carrier
import socket
import dns.resolver
import aiohttp
import os
import csv

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

TOKEN = os.getenv("TOKEN", "")
IPINFO_TOKEN = os.getenv("IPINFO_TOKEN", "")
HUNTER_API_KEY = os.getenv("HUNTER_API_KEY", "")
HIBP_API_KEY = os.getenv("HIBP_API_KEY", "")
CSV_FOLDER = "csv_data"

if not TOKEN:
    raise RuntimeError("❌ Укажите переменную окружения TOKEN")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
user_states: dict[int, str] = {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Привет! Я OSINT-бот.\n"
        "Команды:\n\n"
        "/phone — телефон\n"
        "/ip — IP-адрес\n"
        "/domain — домен\n"
        "/email — email\n"
        "/telegram — username\n"
        "/searchcsv — по CSV\n"
        "/listcsv — список CSV"
    )

async def cmd_generic(update: Update, context: ContextTypes.DEFAULT_TYPE, state: str, prompt: str):
    user_states[update.effective_user.id] = state
    await update.message.reply_text(prompt)

async def cmd_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await cmd_generic(update, context, "awaiting_phone", "📞 Введите номер:")

async def cmd_ip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await cmd_generic(update, context, "awaiting_ip", "🌍 Введите IP:")

async def cmd_domain(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await cmd_generic(update, context, "awaiting_domain", "🌐 Введите домен:")

async def cmd_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await cmd_generic(update, context, "awaiting_email", "📧 Введите email:")

async def cmd_hibp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await cmd_generic(update, context, "awaiting_hibp", "🕵 Введите email для проверки:")

async def cmd_telegram(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await cmd_generic(update, context, "awaiting_telegram", "🔍 Введите Telegram username (@user):")

async def cmd_telegramid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await cmd_generic(update, context, "awaiting_telegramid", "🆔 Введите Telegram ID:")

async def cmd_searchcsv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await cmd_generic(update, context, "awaiting_csv", "🔎 Введите слово для поиска в CSV:")

async def cmd_listcsv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        files = [f for f in os.listdir(CSV_FOLDER) if f.endswith(".csv")]
        msg = "📁 CSV-файлы:
" + "
".join(files) if files else "❌ Нет CSV-файлов."
    except FileNotFoundError:
        msg = "❌ Папка csv_data не найдена."
    await update.message.reply_text(msg)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    state = user_states.pop(user_id, "")
    text = update.message.text.strip()
    try:
        if state == "awaiting_phone":
            num = phonenumbers.parse(text, None)
            country = geocoder.description_for_number(num, "en")
            operator = carrier.name_for_number(num, "en")
            await update.message.reply_text(f"📞 Страна: {country}
Оператор: {operator}")
        elif state == "awaiting_ip":
            url = f"https://ipinfo.io/{text}?token={IPINFO_TOKEN}"
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as resp:
                    data = await resp.json()
            result = "\n".join(f"{k}: {v}" for k, v in data.items())
            await update.message.reply_text(result)
        elif state == "awaiting_domain":
            ip = socket.gethostbyname(text)
            answers = dns.resolver.resolve(text, 'NS')
            ns = ", ".join(str(r.target) for r in answers)
            await update.message.reply_text(f"IP: {ip}\nNS: {ns}")
        elif state == "awaiting_email":
            url = f"https://api.hunter.io/v2/email-verifier?email={text}&api_key={HUNTER_API_KEY}"
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as resp:
                    data = await resp.json()
            result = data.get("data", {})
            await update.message.reply_text("\n".join(f"{k}: {v}" for k, v in result.items()))
        elif state == "awaiting_hibp":
            url = f"https://haveibeenpwned.com/api/v3/breachedaccount/{text}"
            headers = {"hibp-api-key": HIBP_API_KEY, "User-Agent": "OSINTBot"}
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as resp:
                    if resp.status == 404:
                        await update.message.reply_text("✅ Без утечек")
                    elif resp.status == 200:
                        breaches = await resp.json()
                        names = ", ".join(b["Name"] for b in breaches)
                        await update.message.reply_text(f"⚠️ Утечки: {names}")
                    else:
                        await update.message.reply_text(f"❌ Ошибка HIBP: {resp.status}")
        elif state == "awaiting_telegram":
            user = text.lstrip("@")
            await update.message.reply_text(f"https://t.me/{user}")
        elif state in ("awaiting_telegramid", "awaiting_csv"):
            results = search_in_csv(text)
            for result in results:
                await update.message.reply_text(result)
        else:
            await update.message.reply_text("🤖 Напиши команду, например /phone")
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {e}")

def search_in_csv(keyword: str) -> list[str]:
    results = []
    if not os.path.exists(CSV_FOLDER):
        return ["❌ Папка csv_data не найдена"]
    for file in os.listdir(CSV_FOLDER):
        if not file.endswith(".csv"):
            continue
        path = os.path.join(CSV_FOLDER, file)
        try:
            with open(path, encoding="utf-8", errors="ignore") as f:
                for row in csv.reader(f):
                    if any(keyword.lower() in str(cell).lower() for cell in row):
                        results.append(f"[{file}] {' | '.join(row)}")
                        if len(results) >= 20:
                            return results
        except Exception as e:
            results.append(f"[{file}] Ошибка чтения: {e}")
    return results or ["❌ Ничего не найдено"]

def main():
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("phone", cmd_phone))
    app.add_handler(CommandHandler("ip", cmd_ip))
    app.add_handler(CommandHandler("domain", cmd_domain))
    app.add_handler(CommandHandler("email", cmd_email))
    app.add_handler(CommandHandler("hibp", cmd_hibp))
    app.add_handler(CommandHandler("telegram", cmd_telegram))
    app.add_handler(CommandHandler("telegramid", cmd_telegramid))
    app.add_handler(CommandHandler("searchcsv", cmd_searchcsv))
    app.add_handler(CommandHandler("listcsv", cmd_listcsv))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    logger.info("✅ OSINT-бот запущен")
    app.run_polling()

if __name__ == "__main__":
    main()
