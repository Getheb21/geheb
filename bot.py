import os
import random
import string
import asyncio
import re
import uuid
import json
import aiohttp
import logging
from datetime import datetime, timezone
from fastapi import FastAPI, Request, Response
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

TOKEN = "8824915756:AAEYK27n7r3uLATXvJo8yej9A-iuF6ZDHmo"
GROUP_ID = -1004339334563
ADMIN_ID = 6790347169

app = FastAPI()
telegram_app = None
active_loops = set()

GOHUB_API = "https://api.gohub.com"
GOHUB_PARTNER_CODE = "APPFREE"
GOHUB_ITEM_CODE = "BUTECIDN3DF3HM0100"
ESIM_WAIT_TIMEOUT = 120  # 2 MENIT
ESIM_POLL_INTERVAL = 5

class GoHubBot:
    def __init__(self):
        self.base_url = GOHUB_API
        self.email = ""
        self.access_token = ""
        self.customer_id = ""
        self.device_code = str(uuid.uuid4())
        self.fcm_token = self.generate_fcm_token()
        self.device_name = self.generate_device_name()
        self.session_id = self.generate_session_id()
        self.mail_token = ""

    def generate_session_id(self):
        return f"{int(datetime.now().timestamp() * 1000)}_{random.randint(100, 999)}"

    def generate_device_name(self):
        return ''.join(random.choices(string.ascii_uppercase + string.digits, k=10))

    def generate_fcm_token(self):
        random_part = ''.join(random.choices(string.ascii_letters + string.digits, k=22))
        return f"f{random_part}:APA91b{''.join(random.choices(string.ascii_letters + string.digits + '-_', k=134))}"

    def get_base_headers(self):
        return {
            "user-agent": "Dart/3.12 (dart:io)",
            "x-session-id": self.session_id,
            "x-app-id": "gohub-app",
            "accept-encoding": "gzip",
            "host": "api.gohub.com"
        }

    def get_auth_headers(self):
        headers = self.get_base_headers()
        headers["authorization"] = f"Bearer {self.access_token}"
        headers["cookie"] = f"sid={self.access_token}"
        return headers

    async def create_mailtm_account(self):
        async with aiohttp.ClientSession() as session:
            async with session.get("https://api.mail.tm/domains") as r:
                domains = await r.json()
                domain = domains['hydra:member'][0]['domain']
                user = ''.join(random.choices(string.ascii_lowercase + string.digits, k=10))
                self.email = f"{user}@{domain}"
            
            payload = {"address": self.email, "password": "Password123!"}
            async with session.post("https://api.mail.tm/accounts", json=payload) as r:
                if r.status not in [200, 201]:
                    raise Exception(f"Gagal buat Mail.tm: {r.status}")
            
            async with session.post("https://api.mail.tm/token", json=payload) as r:
                data = await r.json()
                self.mail_token = data.get('token', '')
                if not self.mail_token:
                    raise Exception("Gagal token Mail.tm")
        
        logger.info(f"Email: {self.email}")

    async def fetch_otp(self, timeout=90):
        headers = {"Authorization": f"Bearer {self.mail_token}"}
        start = asyncio.get_event_loop().time()
        
        async with aiohttp.ClientSession(headers=headers) as session:
            while (asyncio.get_event_loop().time() - start) < timeout:
                try:
                    async with session.get("https://api.mail.tm/messages") as r:
                        data = await r.json()
                        if data.get('hydra:totalItems', 0) > 0:
                            for msg in data['hydra:member']:
                                async with session.get(f"https://api.mail.tm/messages/{msg['id']}") as r2:
                                    detail = await r2.json()
                                    raw_text = detail.get('text', '') or ''
                                    raw_html = detail.get('html', '') or ''
                                    subject = detail.get('subject', '') or ''
                                    
                                    if isinstance(raw_text, list):
                                        raw_text = " ".join(str(x) for x in raw_text)
                                    if isinstance(raw_html, list):
                                        raw_html = " ".join(str(x) for x in raw_html)
                                    if isinstance(subject, list):
                                        subject = " ".join(str(x) for x in subject)
                                    
                                    combined = f"{subject} {raw_text} {raw_html}"
                                    match = re.search(r'\b[0-9]{6}\b', combined)
                                    if match:
                                        return match.group(0)
                except Exception as e:
                    logger.error(f"Fetch OTP error: {e}")
                await asyncio.sleep(1)
        return None

    async def request_otp(self):
        headers = self.get_base_headers()
        headers["content-type"] = "application/json"
        payload = {"email": self.email, "language": "en", "currency": "USD"}
        
        async with aiohttp.ClientSession() as session:
            async with session.post(f"{self.base_url}/v1/app/auth/otp/request", json=payload, headers=headers) as r:
                data = await r.json()
                logger.info(f"OTP Request: {data}")
                return data.get('success', False)

    async def verify_otp(self, otp):
        headers = self.get_base_headers()
        headers["content-type"] = "application/json"
        payload = {"email": self.email, "code": otp}
        
        async with aiohttp.ClientSession() as session:
            async with session.post(f"{self.base_url}/v1/app/auth/otp/verify", json=payload, headers=headers) as r:
                data = await r.json()
                logger.info(f"OTP Verify: {data}")
                if data.get('success'):
                    self.access_token = data['data']['accessToken']
                    self.customer_id = data['data']['customerId']
                    return True
                return False

    async def register_device(self):
        headers = self.get_base_headers()
        headers["content-type"] = "application/json"
        payload = {
            "deviceCode": self.device_code,
            "fcmToken": self.fcm_token,
            "name": self.device_name,
            "customerId": self.customer_id
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(f"{self.base_url}/v1/app/auth/device/register", json=payload, headers=headers) as r:
                data = await r.json()
                logger.info(f"Device Register: {data}")
                return data.get('success', False)

    async def claim_esim(self):
        headers = self.get_auth_headers()
        headers["content-type"] = "application/json"
        payload = {"partnerCode": GOHUB_PARTNER_CODE, "itemCode": GOHUB_ITEM_CODE}
        
        async with aiohttp.ClientSession() as session:
            async with session.post(f"{self.base_url}/v1/app/redeem/claim", json=payload, headers=headers) as r:
                data = await r.json()
                logger.info(f"Claim: {data}")
                if data.get('success'):
                    return True, data['data']['info']
                return False, data.get('message', 'Unknown')

    async def poll_esim_list(self, status_callback=None):
        """POLLING eSIM LIST SAMPAI MUNCUL ATAU 2 MENIT"""
        start_time = asyncio.get_event_loop().time()
        
        while (asyncio.get_event_loop().time() - start_time) < ESIM_WAIT_TIMEOUT:
            elapsed = int(asyncio.get_event_loop().time() - start_time)
            remaining = ESIM_WAIT_TIMEOUT - elapsed
            
            try:
                headers = self.get_auth_headers()
                url = f"{self.base_url}/v1/app/customer/esim?page=1&perPage=20"
                
                async with aiohttp.ClientSession() as session:
                    async with session.get(url, headers=headers) as r:
                        data = await r.json()
                        
                        if data.get('success') and data.get('data'):
                            esim_list = data['data']
                            logger.info(f"eSIM MUNCUL! Setelah {elapsed} detik. Total: {len(esim_list)}")
                            if status_callback:
                                await status_callback(f"✅ eSIM muncul setelah {elapsed} detik!")
                            return esim_list
                        
                        if status_callback:
                            await status_callback(f"⏳ Menunggu eSIM... ({elapsed}s/{ESIM_WAIT_TIMEOUT}s)")
                        
                        logger.info(f"eSIM belum muncul. Elapsed: {elapsed}s, Remaining: {remaining}s")
                        
            except Exception as e:
                logger.error(f"Polling error: {e}")
            
            await asyncio.sleep(ESIM_POLL_INTERVAL)
        
        raise Exception(f"TIMEOUT! eSIM tidak muncul setelah {ESIM_WAIT_TIMEOUT} detik")

    async def get_esim_detail(self, esim_id):
        headers = self.get_auth_headers()
        url = f"{self.base_url}/v1/app/customer/esim/{esim_id}"
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as r:
                data = await r.json()
                if data.get('success'):
                    return data['data']
                return None

    async def full_registration_flow(self, status_callback=None):
        # 1. Mail.tm
        if status_callback:
            await status_callback("📧 [1/7] Membuat email sementara...")
        await self.create_mailtm_account()
        
        # 2. Request OTP
        if status_callback:
            await status_callback(f"📤 [2/7] Request OTP ke `{self.email}`...")
        if not await self.request_otp():
            raise Exception("Gagal request OTP")
        
        # 3. Fetch OTP
        if status_callback:
            await status_callback("⏳ [3/7] Menunggu OTP masuk...")
        otp = await self.fetch_otp()
        if not otp:
            raise Exception("OTP timeout")
        
        # 4. Verify OTP
        if status_callback:
            await status_callback(f"🔐 [4/7] Verify OTP: `{otp}`...")
        if not await self.verify_otp(otp):
            raise Exception("Gagal verify OTP")
        
        # 5. Register device
        if status_callback:
            await status_callback("📱 [5/7] Register device...")
        if not await self.register_device():
            raise Exception("Gagal register device")
        
        # 6. Claim eSIM
        if status_callback:
            await status_callback("🎁 [6/7] Claim eSIM...")
        claim_ok, claim_data = await self.claim_esim()
        
        if not claim_ok:
            if status_callback:
                await status_callback(f"❌ Redeem GAGAL: `{claim_data}`")
            raise Exception(f"Redeem gagal: {claim_data}")
        
        if status_callback:
            await status_callback(
                f"✅ **Redeem SUKSES!**\n"
                f"📦 Kode: `{claim_data.get('code', '')}`\n"
                f"⏳ [7/7] Menunggu eSIM diproses (max 2 menit)..."
            )
        
        # 7. POLLING eSIM - WAJIB NUNGGU SAMPAI MUNCUL
        esim_list = await self.poll_esim_list(status_callback)
        
        if not esim_list:
            raise Exception("eSIM list kosong")
        
        # Ambil detail eSIM pertama
        esim_detail = await self.get_esim_detail(esim_list[0]['id'])
        if not esim_detail:
            raise Exception("Gagal ambil detail eSIM")
        
        result = {
            "email": self.email,
            "customer_id": self.customer_id,
            "order_code": claim_data.get('code', ''),
            "iccid": esim_detail.get('iccid', ''),
            "qr_image_url": esim_detail.get('esimQrImageUrl', ''),
            "smdp": esim_detail.get('lpa', {}).get('iosLPA', {}).get('smdp', ''),
            "activation_code": esim_detail.get('lpa', {}).get('iosLPA', {}).get('activationCode', ''),
            "qr_content": esim_detail.get('qrImageUrl', ''),
            "display_name": esim_detail.get('productInformation', {}).get('displayName', '')
        }
        
        logger.info(f"SUKSES! ICCID: {result['iccid']}")
        return result

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    
    user = update.effective_user
    username = f"@{user.username}" if user.username else user.first_name
    chat_id = update.effective_chat.id
    
    msg = await update.message.reply_text("🚀 Bot GoHub eSIM aktif! Memproses...")
    
    async def update_status(text):
        try:
            await context.bot.edit_message_text(
                text=text,
                chat_id=chat_id,
                message_id=msg.message_id,
                parse_mode="Markdown"
            )
        except Exception:
            pass
    
    bot = GoHubBot()
    try:
        result = await bot.full_registration_flow(update_status)
        
        success_text = (
            f"✅ **eSIM BERHASIL!**\n\n"
            f"📧 Email: `{result['email']}`\n"
            f"📦 Order: `{result['order_code']}`\n"
            f"💳 ICCID: `{result['iccid']}`\n"
            f"📱 Produk: `{result['display_name']}`\n\n"
            f"🔗 SM-DP+: `{result['smdp']}`\n"
            f"🔑 Activation: `{result['activation_code']}`\n\n"
            f"📲 QR: {result['qr_image_url']}"
        )
        
        if result['qr_image_url']:
            await context.bot.send_photo(
                chat_id=chat_id,
                photo=result['qr_image_url'],
                caption=success_text,
                parse_mode="Markdown"
            )
        else:
            await update_status(success_text)
        
        grup_text = (
            f"Halo {username}\n\n"
            f"✅ eSIM GoHub berhasil!\n\n"
            f"📧 Email: {result['email']}\n"
            f"💳 ICCID: {result['iccid']}\n"
            f"🔑 Activation: {result['activation_code']}\n\n"
            f"CREATED BY: {username}"
        )
        await context.bot.send_message(chat_id=GROUP_ID, text=grup_text)
        
    except Exception as e:
        error_text = f"❌ **Gagal:**\n`{str(e)}`"
        await update_status(error_text)

async def loop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    
    await update.message.reply_text(f"🔄 **Looping dimulai!** Target: {target}")
    
    while chat_id in active_loops and success_count < target:
        msg = await update.message.reply_text(f"🚀 [Loop {success_count + 1}] Memproses...")
        
        async def update_status(text):
            try:
                await context.bot.edit_message_text(
                    text=text,
                    chat_id=chat_id,
                    message_id=msg.message_id,
                    parse_mode="Markdown"
                )
            except Exception:
                pass
        
        bot = GoHubBot()
        try:
            result = await bot.full_registration_flow(update_status)
            
            if result and result.get('iccid'):
                success_count += 1
                success_text = (
                    f"✅ **[BERHASIL {success_count}/{target}]**\n\n"
                    f"📧 Email: `{result['email']}`\n"
                    f"💳 ICCID: `{result['iccid']}`\n"
                    f"🔑 Activation: `{result['activation_code']}`\n"
                    f"📲 QR: {result['qr_image_url']}"
                )
                
                if result['qr_image_url']:
                    await context.bot.send_photo(
                        chat_id=chat_id,
                        photo=result['qr_image_url'],
                        caption=success_text,
                        parse_mode="Markdown"
                    )
                else:
                    await update_status(success_text)
                
                grup_text = (
                    f"Halo {username}\n\n"
                    f"✅ GoHub eSIM berhasil! (Loop {success_count})\n\n"
                    f"📧 Email: {result['email']}\n"
                    f"💳 ICCID: {result['iccid']}\n"
                    f"🔑 Activation: {result['activation_code']}\n\n"
                    f"CREATED BY: {username}"
                )
                await context.bot.send_message(chat_id=GROUP_ID, text=grup_text)
            else:
                raise Exception("Hasil tidak valid")
                
        except Exception as e:
            error_text = f"❌ **Gagal Loop {success_count + 1}:**\n`{str(e)}`"
            await update_status(error_text)
        
        if chat_id in active_loops and success_count < target:
            await asyncio.sleep(3)
    
    if chat_id in active_loops:
        active_loops.remove(chat_id)
    
    await update.message.reply_text(f"🏁 **Selesai!** Berhasil: {success_count}")

async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    await telegram_app.initialize()
    await telegram_app.start()
    logger.info("Bot ready!")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
