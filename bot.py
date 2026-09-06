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

# Konfigurasi GoHub API
GOHUB_API = "https://api.gohub.com"
GOHUB_PARTNER_CODE = "APPFREE"
GOHUB_ITEM_CODE = "BUTECIDN3DF3HM0100"
ESIM_DELAY_TIMEOUT = 120
ESIM_POLL_INTERVAL = 5

class GoHubBot:
    def __init__(self):
        self.base_url = GOHUB_API
        self.email = ""
        self.access_token = ""
        self.refresh_token = ""
        self.customer_id = ""
        self.device_code = ""
        self.fcm_token = ""
        self.session_id = ""
        self.mail_token = ""

    def generate_session_id(self):
        timestamp = int(datetime.now().timestamp() * 1000)
        random_suffix = random.randint(100, 999)
        return f"{timestamp}_{random_suffix}"

    def generate_device_name(self):
        return ''.join(random.choices(string.ascii_uppercase + string.digits, k=10))

    def generate_fcm_token(self):
        random_part = ''.join(random.choices(string.ascii_letters + string.digits, k=22))
        return f"f{random_part}:APA91b{''.join(random.choices(string.ascii_letters + string.digits + '-_', k=134))}"

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
                    raise Exception(f"Gagal buat akun Mail.tm: {r.status}")
            
            async with session.post("https://api.mail.tm/token", json=payload) as r:
                data = await r.json()
                self.mail_token = data.get('token', '')
                if not self.mail_token:
                    raise Exception("Gagal dapat token Mail.tm")
        
        logger.info(f"Mail.tm account: {self.email}")
        return self.mail_token

    async def fetch_otp_from_email(self, timeout=90):
        headers = {"Authorization": f"Bearer {self.mail_token}"}
        start_time = asyncio.get_event_loop().time()
        
        async with aiohttp.ClientSession(headers=headers) as session:
            while (asyncio.get_event_loop().time() - start_time) < timeout:
                try:
                    async with session.get("https://api.mail.tm/messages") as r:
                        data = await r.json()
                        if data.get('hydra:totalItems', 0) > 0:
                            for msg in data['hydra:member']:
                                msg_id = msg['id']
                                async with session.get(f"https://api.mail.tm/messages/{msg_id}") as r2:
                                    msg_detail = await r2.json()
                                    raw_text = msg_detail.get('text', '') or ''
                                    raw_html = msg_detail.get('html', '') or ''
                                    subject = msg_detail.get('subject', '') or ''
                                    
                                    if isinstance(raw_text, list):
                                        raw_text = "\n".join(str(x) for x in raw_text)
                                    if isinstance(raw_html, list):
                                        raw_html = "\n".join(str(x) for x in raw_html)
                                    if isinstance(subject, list):
                                        subject = " ".join(str(x) for x in subject)

                                    combined = f"{subject} {raw_text} {raw_html}"
                                    logger.info(f"Email content: {combined[:200]}")
                                    
                                    match = re.search(r'(?:otp|code|verification|login)[:\s\-]*([0-9]{6})', combined, re.IGNORECASE)
                                    if match:
                                        otp = match.group(1).strip()
                                        logger.info(f"OTP found: {otp}")
                                        return otp
                                    
                                    words = re.findall(r'\b[0-9]{6}\b', combined)
                                    if words:
                                        logger.info(f"OTP found (fallback): {words[0]}")
                                        return words[0]
                except Exception as e:
                    logger.error(f"Error fetching OTP: {e}")
                await asyncio.sleep(1)
        return None

    async def request_otp(self):
        self.session_id = self.generate_session_id()
        headers = {
            "user-agent": "Dart/3.12 (dart:io)",
            "x-session-id": self.session_id,
            "x-app-id": "gohub-app",
            "content-type": "application/json"
        }
        payload = {
            "email": self.email,
            "language": "en",
            "currency": "USD"
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.base_url}/v1/app/auth/otp/request",
                json=payload,
                headers=headers
            ) as r:
                data = await r.json()
                logger.info(f"Request OTP status: {r.status}, response: {data}")
                if data.get('success'):
                    return True
                return False

    async def verify_otp(self, otp_code):
        headers = {
            "user-agent": "Dart/3.12 (dart:io)",
            "x-session-id": self.session_id,
            "x-app-id": "gohub-app",
            "content-type": "application/json"
        }
        payload = {
            "email": self.email,
            "code": otp_code
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.base_url}/v1/app/auth/otp/verify",
                json=payload,
                headers=headers
            ) as r:
                data = await r.json()
                logger.info(f"Verify OTP status: {r.status}, response: {data}")
                if data.get('success'):
                    self.access_token = data['data']['accessToken']
                    self.refresh_token = data['data']['refreshToken']
                    self.customer_id = data['data']['customerId']
                    return True
                return False

    async def register_device(self):
        self.device_code = str(uuid.uuid4())
        self.fcm_token = self.generate_fcm_token()
        device_name = self.generate_device_name()
        
        headers = {
            "user-agent": "Dart/3.12 (dart:io)",
            "x-session-id": self.session_id,
            "x-app-id": "gohub-app",
            "content-type": "application/json"
        }
        payload = {
            "deviceCode": self.device_code,
            "fcmToken": self.fcm_token,
            "name": device_name,
            "customerId": self.customer_id
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.base_url}/v1/app/auth/device/register",
                json=payload,
                headers=headers
            ) as r:
                data = await r.json()
                logger.info(f"Register device status: {r.status}, response: {data}")
                if data.get('success'):
                    return True
                return False

    def get_headers_with_auth(self):
        """Headers dengan auth - MATCH PERSIS dengan sniff"""
        return {
            "user-agent": "Dart/3.12 (dart:io)",
            "x-session-id": self.session_id,
            "x-app-id": "gohub-app",
            "accept-encoding": "gzip",
            "authorization": f"Bearer {self.access_token}",
            "cookie": f"sid={self.access_token}",
            "host": "api.gohub.com"
        }

    async def claim_esim(self):
        headers = self.get_headers_with_auth()
        # Remove content-type for GET, keep for POST
        headers["content-type"] = "application/json"
        payload = {
            "partnerCode": GOHUB_PARTNER_CODE,
            "itemCode": GOHUB_ITEM_CODE
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.base_url}/v1/app/redeem/claim",
                json=payload,
                headers=headers
            ) as r:
                data = await r.json()
                logger.info(f"Claim eSIM status: {r.status}, response: {data}")
                if data.get('success'):
                    return data['data']['info']
                return None

    async def get_esim_list(self):
        """Dapatkan daftar eSIM customer"""
        headers = self.get_headers_with_auth()
        # JANGAN kirim content-type untuk GET
        headers.pop("content-type", None)
        
        url = f"{self.base_url}/v1/app/customer/esim?page=1&perPage=20"
        logger.info(f"GET URL: {url}")
        logger.info(f"Headers: {json.dumps(headers, indent=2)}")
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as r:
                response_text = await r.text()
                logger.info(f"Get eSIM list status: {r.status}")
                logger.info(f"Get eSIM list raw response: {response_text}")
                
                try:
                    data = json.loads(response_text)
                except:
                    logger.error(f"Failed to parse JSON: {response_text}")
                    return []
                
                if data.get('success') and data.get('data'):
                    return data['data']
                
                logger.warning(f"eSIM list kosong atau gagal: {data}")
                return []

    async def get_esim_detail(self, esim_id):
        headers = self.get_headers_with_auth()
        headers.pop("content-type", None)
        
        url = f"{self.base_url}/v1/app/customer/esim/{esim_id}"
        logger.info(f"GET Detail URL: {url}")
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as r:
                response_text = await r.text()
                logger.info(f"Get eSIM detail status: {r.status}")
                logger.info(f"Get eSIM detail raw response: {response_text}")
                
                try:
                    data = json.loads(response_text)
                except:
                    logger.error(f"Failed to parse JSON: {response_text}")
                    return None
                
                if data.get('success'):
                    return data['data']
                return None

    async def wait_for_esim(self, status_callback=None, timeout=ESIM_DELAY_TIMEOUT):
        """Polling eSIM list sampai muncul atau timeout"""
        start_time = asyncio.get_event_loop().time()
        
        while (asyncio.get_event_loop().time() - start_time) < timeout:
            try:
                esim_list = await self.get_esim_list()
                
                if esim_list:
                    elapsed = int(asyncio.get_event_loop().time() - start_time)
                    logger.info(f"eSIM muncul setelah {elapsed} detik!")
                    return esim_list
                
                elapsed = int(asyncio.get_event_loop().time() - start_time)
                remaining = timeout - elapsed
                
                if status_callback:
                    await status_callback(f"⏳ Menunggu eSIM... ({elapsed}s/{timeout}s)")
                
                logger.info(f"eSIM belum muncul, elapsed: {elapsed}s")
                
            except Exception as e:
                logger.error(f"Error polling eSIM: {e}")
            
            await asyncio.sleep(ESIM_POLL_INTERVAL)
        
        raise Exception(f"Timeout! eSIM tidak muncul setelah {timeout} detik")

    async def full_registration_flow(self, status_callback=None):
        try:
            # Step 1: Buat akun Mail.tm
            if status_callback:
                await status_callback("📧 [1/7] Membuat akun email sementara...")
            await self.create_mailtm_account()
            
            # Step 2: Request OTP
            if status_callback:
                await status_callback(f"📤 [2/7] Request OTP ke `{self.email}`...")
            if not await self.request_otp():
                raise Exception("Gagal request OTP")
            
            # Step 3: Fetch OTP dari email
            if status_callback:
                await status_callback("⏳ [3/7] Menunggu OTP masuk...")
            otp = await self.fetch_otp_from_email()
            if not otp:
                raise Exception("OTP timeout - email tidak diterima")
            
            # Step 4: Verify OTP
            if status_callback:
                await status_callback(f"🔐 [4/7] Verify OTP: `{otp}`...")
            if not await self.verify_otp(otp):
                raise Exception("Gagal verify OTP - kode salah")
            
            # Step 5: Register device
            if status_callback:
                await status_callback("📱 [5/7] Register device...")
            if not await self.register_device():
                raise Exception("Gagal register device")
            
            # Step 6: Claim eSIM
            if status_callback:
                await status_callback("🎁 [6/7] Claim eSIM...")
            order_info = await self.claim_esim()
            if not order_info:
                raise Exception("Gagal claim eSIM - mungkin rate limit")
            
            # Step 7: Tunggu eSIM muncul dengan polling
            if status_callback:
                await status_callback("📋 [7/7] Menunggu eSIM diproses...")
            
            # Polling eSIM sampai muncul
            esim_list = await self.wait_for_esim(status_callback, timeout=ESIM_DELAY_TIMEOUT)
            
            # Ambil eSIM pertama (terbaru)
            latest_esim = esim_list[0]
            logger.info(f"Latest eSIM ID: {latest_esim.get('id')}")
            
            # Ambil detail eSIM
            esim_detail = await self.get_esim_detail(latest_esim['id'])
            if not esim_detail:
                raise Exception("Gagal mengambil detail eSIM")
            
            # Format output
            result = {
                "email": self.email,
                "customer_id": self.customer_id,
                "device_code": self.device_code,
                "order_code": order_info.get('code', ''),
                "iccid": esim_detail.get('iccid', ''),
                "qr_image_url": esim_detail.get('esimQrImageUrl', ''),
                "lpa": esim_detail.get('lpa', {}),
                "smdp": esim_detail.get('lpa', {}).get('iosLPA', {}).get('smdp', ''),
                "activation_code": esim_detail.get('lpa', {}).get('iosLPA', {}).get('activationCode', ''),
                "qr_content": esim_detail.get('qrImageUrl', ''),
                "display_name": esim_detail.get('productInformation', {}).get('displayName', ''),
                "expiry_date": esim_detail.get('expiryDate', ''),
                "created_at": esim_detail.get('createdAt', '')
            }
            
            logger.info(f"Full flow completed! ICCID: {result['iccid']}")
            return result
            
        except Exception as e:
            logger.error(f"Error in full flow: {e}", exc_info=True)
            raise e

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    
    user = update.effective_user
    username = f"@{user.username}" if user.username else user.first_name
    chat_id = update.effective_chat.id
    
    msg = await update.message.reply_text("🚀 Bot GoHub eSIM aktif! Memproses klaim...")
    
    async def update_status(text):
        try:
            await context.bot.edit_message_text(
                text=text,
                chat_id=chat_id,
                message_id=msg.message_id,
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.error(f"Error update status: {e}")
    
    bot = GoHubBot()
    try:
        result = await bot.full_registration_flow(update_status)
        
        success_text = (
            f"✅ **eSIM BERHASIL DIBUAT!**\n\n"
            f"📧 Email: `{result['email']}`\n"
            f"🆔 Customer ID: `{result['customer_id']}`\n"
            f"📦 Order Code: `{result['order_code']}`\n"
            f"💳 ICCID: `{result['iccid']}`\n"
            f"📱 Produk: `{result['display_name']}`\n"
            f"📅 Expiry: `{result['expiry_date']}`\n\n"
            f"🔗 **SM-DP+ Address:** `{result['smdp']}`\n"
            f"🔑 **Activation Code:** `{result['activation_code']}`\n\n"
            f"📲 **QR Content:**\n`{result['qr_content']}`\n\n"
            f"🖼️ QR Image: {result['qr_image_url']}\n\n"
            f"CREATED BY: {username}\n"
            f"Bot: @kopikapal1"
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
            f"✅ eSIM GoHub berhasil dibuat!\n\n"
            f"📧 Email: {result['email']}\n"
            f"💳 ICCID: {result['iccid']}\n"
            f"🔑 Activation Code: {result['activation_code']}\n"
            f"📱 Produk: {result['display_name']}\n\n"
            f"CREATED BY: {username}"
        )
        await context.bot.send_message(chat_id=GROUP_ID, text=grup_text)
        
    except Exception as e:
        error_text = f"❌ **Gagal Memproses:**\n`{str(e)}`"
        await update_status(error_text)

async def loop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    
    user = update.effective_user
    username = f"@{user.username}" if user.username else user.first_name
    chat_id = update.effective_chat.id
    
    if chat_id in active_loops:
        await update.message.reply_text("⚠️ Looping sudah berjalan di chat ini.")
        return
    
    active_loops.add(chat_id)
    success_count = 0
    target_success = 50
    
    await update.message.reply_text(
        f"🔄 **Looping GoHub eSIM Dimulai!**\n"
        f"Target: {target_success} kali berhasil\n"
        f"Kirim /stop untuk menghentikan."
    )
    
    while chat_id in active_loops and success_count < target_success:
        msg = await update.message.reply_text(f"🚀 [Loop ke-{success_count + 1}] Memproses klaim...")
        
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
                    f"✅ **[BERHASIL {success_count}/{target_success}]**\n\n"
                    f"📧 Email: `{result['email']}`\n"
                    f"💳 ICCID: `{result['iccid']}`\n"
                    f"🔑 Activation: `{result['activation_code']}`\n"
                    f"📱 Produk: `{result['display_name']}`\n\n"
                    f"🔗 SM-DP+: `{result['smdp']}`\n\n"
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
                    f"✅ GoHub eSIM berhasil! (Loop ke-{success_count})\n\n"
                    f"📧 Email: {result['email']}\n"
                    f"💳 ICCID: {result['iccid']}\n"
                    f"🔑 Activation: {result['activation_code']}\n"
                    f"📱 Produk: {result['display_name']}\n\n"
                    f"CREATED BY: {username}"
                )
                await context.bot.send_message(chat_id=GROUP_ID, text=grup_text)
            else:
                raise Exception("Hasil tidak valid - tidak ada ICCID")
                
        except Exception as e:
            error_text = f"❌ **Gagal di Loop {success_count + 1}:**\n`{str(e)}`\nMelanjutkan..."
            await update_status(error_text)
        
        if chat_id in active_loops and success_count < target_success:
            await asyncio.sleep(5)
    
    if chat_id in active_loops:
        active_loops.remove(chat_id)
    
    await update.message.reply_text(f"🏁 **Looping Selesai!** Berhasil: {success_count} eSIM")

async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id in active_loops:
        active_loops.remove(chat_id)
        await update.message.reply_text("🛑 Looping dihentikan!")
    else:
        await update.message.reply_text("⚠️ Tidak ada looping aktif.")

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
    return Response(content="GoHub eSIM Bot is running!", status_code=200)

@app.on_event("startup")
async def startup_event():
    global telegram_app
    telegram_app = Application.builder().token(TOKEN).build()
    telegram_app.add_handler(CommandHandler("start", start_command))
    telegram_app.add_handler(CommandHandler("loop", loop_command))
    telegram_app.add_handler(CommandHandler("stop", stop_command))
    await telegram_app.initialize()
    await telegram_app.start()
    logger.info("GoHub eSIM Bot ready!")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))

        
