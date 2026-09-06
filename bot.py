import os
import random
import string
import asyncio
import re
import uuid
import json
import aiohttp
import logging
from datetime import datetime
from fastapi import FastAPI, Request, Response
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

TOKEN = "8824915756:AAEYK27n7r3uLATXvJo8yej9A-iuF6ZDHmo"
GROUP_ID = -1004339334563
QRIS_URL = "https://r9.paidweh1.workers.dev/public/1776930765841_ec1ed32c-db99-4023-aede-176bf5f2b1c0.jpeg"

app = FastAPI()
telegram_app = None
active_loops = set()

GOHUB_API = "https://api.gohub.com"
ITEM_CODE = "BUTECIDN3DF3HM0100"
SMDP_ADDRESS = "hthk.esimcase.com"

class GoHub:
    def __init__(self):
        self.email = ""
        self.access_token = ""
        self.customer_id = ""
        self.device_code = str(uuid.uuid4())
        self.session_id = f"{int(datetime.now().timestamp() * 1000)}_{random.randint(100,999)}"
        self.mail_token = ""
        self.fcm_token = f"f{''.join(random.choices(string.ascii_letters + string.digits, k=22))}:APA91b{''.join(random.choices(string.ascii_letters + string.digits + '-_', k=134))}"
        self.device_name = ''.join(random.choices(string.ascii_uppercase + string.digits, k=10))

    def base_headers(self):
        return {
            "user-agent": "Dart/3.12 (dart:io)",
            "x-session-id": self.session_id,
            "x-app-id": "gohub-app",
            "host": "api.gohub.com"
        }

    def auth_headers(self):
        h = self.base_headers()
        h["authorization"] = f"Bearer {self.access_token}"
        h["cookie"] = f"sid={self.access_token}"
        return h

    async def create_email(self):
        async with aiohttp.ClientSession() as s:
            async with s.get("https://api.mail.tm/domains") as r:
                domains = await r.json()
                domain = domains['hydra:member'][0]['domain']
                user = ''.join(random.choices(string.ascii_lowercase + string.digits, k=10))
                self.email = f"{user}@{domain}"
            
            payload = {"address": self.email, "password": "Password123!"}
            await s.post("https://api.mail.tm/accounts", json=payload)
            async with s.post("https://api.mail.tm/token", json=payload) as r:
                data = await r.json()
                self.mail_token = data.get('token', '')
        
        logger.info(f"Email: {self.email}")

    async def get_otp(self):
        headers = {"Authorization": f"Bearer {self.mail_token}"}
        start = asyncio.get_event_loop().time()
        
        async with aiohttp.ClientSession(headers=headers) as s:
            while (asyncio.get_event_loop().time() - start) < 90:
                try:
                    async with s.get("https://api.mail.tm/messages") as r:
                        data = await r.json()
                        if data.get('hydra:totalItems', 0) > 0:
                            msg_id = data['hydra:member'][0]['id']
                            async with s.get(f"https://api.mail.tm/messages/{msg_id}") as r2:
                                detail = await r2.json()
                                text = detail.get('text', '') or ''
                                html = detail.get('html', '') or ''
                                subject = detail.get('subject', '') or ''
                                combined = f"{subject} {text} {html}"
                                match = re.search(r'\b[0-9]{6}\b', combined)
                                if match:
                                    return match.group(0)
                except:
                    pass
                await asyncio.sleep(1)
        return None

    async def request_otp(self):
        h = self.base_headers()
        h["content-type"] = "application/json"
        payload = {"email": self.email, "language": "en", "currency": "USD"}
        
        async with aiohttp.ClientSession() as s:
            async with s.post(f"{GOHUB_API}/v1/app/auth/otp/request", json=payload, headers=h) as r:
                data = await r.json()
                return data.get('success', False)

    async def verify_otp(self, otp):
        h = self.base_headers()
        h["content-type"] = "application/json"
        payload = {"email": self.email, "code": otp}
        
        async with aiohttp.ClientSession() as s:
            async with s.post(f"{GOHUB_API}/v1/app/auth/otp/verify", json=payload, headers=h) as r:
                data = await r.json()
                if data.get('success'):
                    self.access_token = data['data']['accessToken']
                    self.customer_id = data['data']['customerId']
                    return True
                return False

    async def register_device(self):
        h = self.base_headers()
        h["content-type"] = "application/json"
        payload = {
            "deviceCode": self.device_code,
            "fcmToken": self.fcm_token,
            "name": self.device_name,
            "customerId": self.customer_id
        }
        
        async with aiohttp.ClientSession() as s:
            async with s.post(f"{GOHUB_API}/v1/app/auth/device/register", json=payload, headers=h) as r:
                data = await r.json()
                return data.get('success', False)

    async def claim(self):
        h = self.auth_headers()
        h["content-type"] = "application/json"
        payload = {"partnerCode": "APPFREE", "itemCode": ITEM_CODE}
        
        async with aiohttp.ClientSession() as s:
            async with s.post(f"{GOHUB_API}/v1/app/redeem/claim", json=payload, headers=h) as r:
                data = await r.json()
                if data.get('success'):
                    return True, data['data']['info']
                return False, data.get('message', 'error')

    async def get_esim_detail_with_retry(self, esim_id, max_retry=5):
        h = self.auth_headers()
        url = f"{GOHUB_API}/v1/app/customer/esim/{esim_id}"
        
        for attempt in range(max_retry):
            try:
                async with aiohttp.ClientSession() as s:
                    async with s.get(url, headers=h, timeout=aiohttp.ClientTimeout(total=30)) as r:
                        response_text = await r.text()
                        logger.info(f"Detail attempt {attempt+1}: HTTP {r.status}")
                        
                        data = json.loads(response_text)
                        if data.get('success') and data.get('data'):
                            return data['data']
                        
            except Exception as e:
                logger.error(f"Detail error attempt {attempt+1}: {e}")
            
            if attempt < max_retry - 1:
                await asyncio.sleep(3)
        
        return None

    async def run(self, progress_callback=None):
        # 1. Email
        if progress_callback: await progress_callback("📧 [1/7] Buat email...")
        await self.create_email()
        
        # 2. Request OTP
        if progress_callback: await progress_callback(f"📤 [2/7] Request OTP...")
        if not await self.request_otp():
            raise Exception("Gagal request OTP")
        
        # 3. Get OTP
        if progress_callback: await progress_callback("⏳ [3/7] Tunggu OTP...")
        otp = await self.get_otp()
        if not otp:
            raise Exception("OTP timeout")
        
        # 4. Verify
        if progress_callback: await progress_callback(f"🔐 [4/7] Verify: `{otp}`")
        if not await self.verify_otp(otp):
            raise Exception("Verify gagal")
        
        # 5. Device
        if progress_callback: await progress_callback("📱 [5/7] Register device...")
        if not await self.register_device():
            raise Exception("Device gagal")
        
        # 6. Claim
        if progress_callback: await progress_callback("🎁 [6/7] Claim eSIM...")
        ok, info = await self.claim()
        
        if not ok:
            if progress_callback: await progress_callback(f"❌ Redeem GAGAL: `{info}`")
            raise Exception(f"Redeem gagal: {info}")
        
        if progress_callback:
            await progress_callback(f"✅ Redeem SUKSES!\n⏳ [7/7] Tunggu eSIM...")
        
        # 7. POLLING
        start = asyncio.get_event_loop().time()
        attempt = 0
        
        while True:
            attempt += 1
            elapsed = int(asyncio.get_event_loop().time() - start)
            
            if elapsed >= 120:
                raise Exception(f"TIMEOUT 120 detik!")
            
            try:
                h = self.auth_headers()
                url = f"{GOHUB_API}/v1/app/customer/esim?page=1&perPage=20"
                
                async with aiohttp.ClientSession() as s:
                    async with s.get(url, headers=h, timeout=aiohttp.ClientTimeout(total=30)) as r:
                        response_text = await r.text()
                        data = json.loads(response_text)
                        
                        if data.get('success') and data.get('data') and len(data['data']) > 0:
                            esim_data = data['data'][0]
                            esim_id = esim_data.get('id', '')
                            iccid = esim_data.get('iccid', '')
                            display_name = esim_data.get('productInformation', {}).get('displayName', 'eSIM Indonesia')
                            expiry = esim_data.get('expiryDate', '')
                            
                            if progress_callback:
                                await progress_callback(f"✅ eSIM muncul!\n🔍 Ambil detail...")
                            
                            await asyncio.sleep(3)
                            
                            detail = await self.get_esim_detail_with_retry(esim_id)
                            
                            if detail:
                                activation_code = detail.get('lpa', {}).get('iosLPA', {}).get('activationCode', '')
                                qr_image_url = detail.get('esimQrImageUrl', '')
                                qr_content = detail.get('qrImageUrl', '')
                                
                                if not qr_content and activation_code:
                                    qr_content = f"LPA:1${SMDP_ADDRESS}${activation_code}"
                                
                                return {
                                    "email": self.email,
                                    "order_code": info.get('code', ''),
                                    "iccid": iccid,
                                    "smdp": SMDP_ADDRESS,
                                    "activation_code": activation_code,
                                    "qr_content": qr_content,
                                    "qr_image_url": qr_image_url,
                                    "display_name": display_name,
                                    "expiry_date": expiry
                                }
                            else:
                                raw_code = info.get('code', '')
                                if len(raw_code) == 8:
                                    activation_code = f"{raw_code[:4]}-{raw_code[4:]}-{raw_code[:4]}-{raw_code[4:]}"
                                else:
                                    activation_code = raw_code
                                
                                qr_content = f"LPA:1${SMDP_ADDRESS}${activation_code}"
                                
                                return {
                                    "email": self.email,
                                    "order_code": raw_code,
                                    "iccid": iccid,
                                    "smdp": SMDP_ADDRESS,
                                    "activation_code": activation_code,
                                    "qr_content": qr_content,
                                    "qr_image_url": "",
                                    "display_name": display_name,
                                    "expiry_date": expiry
                                }
                        
                        if progress_callback:
                            await progress_callback(f"⏳ Menunggu eSIM... ({elapsed}s/120s)")
                        
            except Exception as e:
                if progress_callback:
                    await progress_callback(f"⚠️ Error: `{str(e)[:80]}`")
                logger.error(f"Polling error: {e}")
            
            await asyncio.sleep(5)

def build_result_keyboard(qr_content):
    """Build inline keyboard dengan tombol salin QR content dan QRIS"""
    keyboard = [
        [
            InlineKeyboardButton("📋 Salin QR Content", callback_data=f"copy|{qr_content[:50]}")
        ],
        [
            InlineKeyboardButton("💳 QRIS Donasi", url="https://t.me/kopi_kapal1")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

async def start_command(update, context):
    if not update.message or not update.message.text:
        return
    
    user = update.effective_user
    username = f"@{user.username}" if user.username else user.first_name
    chat_id = update.effective_chat.id
    
    msg = await update.message.reply_text("🚀 Mulai...")
    msg_id = msg.message_id
    
    async def update_status(text):
        try:
            await context.bot.edit_message_text(
                text=text,
                chat_id=chat_id,
                message_id=msg_id,
                parse_mode="Markdown"
            )
        except:
            pass
    
    bot = GoHub()
    try:
        result = await bot.run(update_status)
        
        qr_content = result['qr_content']
        
        final_text = (
            f"✅ **eSIM BERHASIL!**\n\n"
            f"📧 `{result['email']}`\n"
            f"📦 `{result['order_code']}`\n"
            f"💳 `{result['iccid']}`\n"
            f"📱 `{result['display_name']}`\n"
            f"📅 `{result['expiry_date']}`\n\n"
            f"🔗 SM-DP+: `{result['smdp']}`\n"
            f"🔑 Activation: `{result['activation_code']}`\n\n"
            f"📲 QR Content:\n`{qr_content}`\n\n"
            f"BY: {username}"
        )
        
        # Keyboard
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📋 Salin QR Content", callback_data=f"copy|{qr_content}")],
            [InlineKeyboardButton("💳 QRIS Donasi", url=QRIS_URL)]
        ])
        
        # Kirim QR image + text dengan keyboard
        if result.get('qr_image_url'):
            try:
                await context.bot.send_photo(
                    chat_id=chat_id,
                    photo=result['qr_image_url'],
                    caption=final_text,
                    parse_mode="Markdown",
                    reply_markup=keyboard
                )
            except:
                try:
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=final_text,
                        parse_mode="Markdown",
                        reply_markup=keyboard
                    )
                except:
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=final_text,
                        reply_markup=keyboard
                    )
        else:
            try:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=final_text,
                    parse_mode="Markdown",
                    reply_markup=keyboard
                )
            except:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=final_text,
                    reply_markup=keyboard
                )
        
        # Kirim ke grup
        grup_text = (
            f"Halo {username}\n\n"
            f"✅ eSIM GoHub berhasil!\n\n"
            f"📧 {result['email']}\n"
            f"💳 {result['iccid']}\n"
            f"🔑 {result['activation_code']}\n"
            f"📱 {result['display_name']}\n\n"
            f"BY: {username}"
        )
        
        try:
            await context.bot.send_message(chat_id=GROUP_ID, text=grup_text)
        except:
            pass
        
    except Exception as e:
        error_text = f"❌ **Gagal:**\n`{str(e)}`"
        try:
            await context.bot.send_message(chat_id=chat_id, text=error_text, parse_mode="Markdown")
        except:
            pass

async def button_callback(update, context):
    """Handle inline button callback"""
    query = update.callback_query
    
    if query.data.startswith("copy|"):
        qr_content = query.data.split("|", 1)[1]
        
        # Kirim sebagai pesan yang bisa di-copy
        await query.answer("QR Content berhasil disalin!")
        
        try:
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=f"📋 **QR Content:**\n`{qr_content}`",
                parse_mode="Markdown"
            )
        except:
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=f"📋 QR Content:\n{qr_content}"
            )
    
    await query.answer()

async def loop_command(update, context):
    if not update.message or not update.message.text:
        return
    
    user = update.effective_user
    username = f"@{user.username}" if user.username else user.first_name
    chat_id = update.effective_chat.id
    
    if chat_id in active_loops:
        await update.message.reply_text("⚠️ Looping sudah jalan.")
        return
    
    active_loops.add(chat_id)
    success_count = 0
    target = 50
    
    await update.message.reply_text(f"🔄 **Looping!** Target: {target}")
    
    while chat_id in active_loops and success_count < target:
        msg = await update.message.reply_text(f"🚀 [Loop {success_count + 1}]")
        msg_id = msg.message_id
        
        async def update_status(text):
            try:
                await context.bot.edit_message_text(
                    text=text,
                    chat_id=chat_id,
                    message_id=msg_id,
                    parse_mode="Markdown"
                )
            except:
                pass
        
        bot = GoHub()
        try:
            result = await bot.run(update_status)
            
            if result and result.get('iccid'):
                success_count += 1
                
                qr_content = result['qr_content']
                
                success = (
                    f"✅ **[{success_count}/{target}]**\n\n"
                    f"📧 `{result['email']}`\n"
                    f"💳 `{result['iccid']}`\n"
                    f"🔑 `{result['activation_code']}`\n"
                    f"📱 `{result['display_name']}`\n\n"
                    f"📲 QR Content:\n`{qr_content}`"
                )
                
                keyboard = InlineKeyboardMarkup([
                    [InlineKeyboardButton("📋 Salin QR Content", callback_data=f"copy|{qr_content}")],
                    [InlineKeyboardButton("💳 QRIS Donasi", url=QRIS_URL)]
                ])
                
                if result.get('qr_image_url'):
                    try:
                        await context.bot.send_photo(
                            chat_id=chat_id,
                            photo=result['qr_image_url'],
                            caption=success,
                            parse_mode="Markdown",
                            reply_markup=keyboard
                        )
                    except:
                        try:
                            await context.bot.send_message(
                                chat_id=chat_id,
                                text=success,
                                parse_mode="Markdown",
                                reply_markup=keyboard
                            )
                        except:
                            pass
                else:
                    try:
                        await context.bot.send_message(
                            chat_id=chat_id,
                            text=success,
                            parse_mode="Markdown",
                            reply_markup=keyboard
                        )
                    except:
                        pass
                
                grup = (
                    f"Halo {username}\n\n"
                    f"✅ eSIM GoHub! (Loop {success_count})\n\n"
                    f"📧 {result['email']}\n"
                    f"💳 {result['iccid']}\n"
                    f"🔑 {result['activation_code']}\n\n"
                    f"BY: {username}"
                )
                
                try:
                    await context.bot.send_message(chat_id=GROUP_ID, text=grup)
                except:
                    pass
            else:
                raise Exception("Hasil tidak valid")
                
        except Exception as e:
            error_text = f"❌ **Gagal Loop {success_count + 1}:**\n`{str(e)}`"
            try:
                await context.bot.send_message(chat_id=chat_id, text=error_text)
            except:
                pass
        
        if chat_id in active_loops and success_count < target:
            await asyncio.sleep(3)
    
    if chat_id in active_loops:
        active_loops.remove(chat_id)
    
    try:
        await update.message.reply_text(f"🏁 **Selesai!** Berhasil: {success_count}")
    except:
        pass

async def stop_command(update, context):
    chat_id = update.effective_chat.id
    if chat_id in active_loops:
        active_loops.remove(chat_id)
        await update.message.reply_text("🛑 Dihentikan!")
    else:
        await update.message.reply_text("⚠️ Tidak ada looping.")

@app.post("/")
async def webhook(request: Request):
    global telegram_app
    try:
        data = await request.json()
        if "message" in data and "text" in data["message"]:
            update = Update.de_json(data, telegram_app.bot)
            if update and update.message:
                await telegram_app.process_update(update)
        elif "callback_query" in data:
            update = Update.de_json(data, telegram_app.bot)
            if update and update.callback_query:
                await telegram_app.process_update(update)
    except Exception as e:
        logger.error(f"Webhook error: {e}")
    return {"status": "ok"}

@app.get("/")
async def health_check():
    return Response(content="Bot running!", status_code=200)

@app.on_event("startup")
async def startup_event():
    global telegram_app
    telegram_app = Application.builder().token(TOKEN).build()
    telegram_app.add_handler(CommandHandler("start", start_command))
    telegram_app.add_handler(CommandHandler("loop", loop_command))
    telegram_app.add_handler(CommandHandler("stop", stop_command))
    telegram_app.add_handler(CallbackQueryHandler(button_callback))
    await telegram_app.initialize()
    await telegram_app.start()
    logger.info("Bot ready!")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
