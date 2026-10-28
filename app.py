import os
import json
import re
from datetime import datetime
import threading
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

# Load local student database
DB_PATH = os.path.join(os.path.dirname(__file__), 'STUDENTS_WHATSAPP_BOT_DATABASE.json')
with open(DB_PATH, 'r', encoding='utf-8') as f:
    STUDENT_DB = json.load(f)

# Environment variables for Telegram Admin Notification
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "8965596009:AAHRANWd1oJpVapa7tHmVJqi3oXbdt-nCsI")
TELEGRAM_ADMIN_CHAT_ID = os.environ.get("TELEGRAM_ADMIN_CHAT_ID", "6161463701")

# Exam schedule definition
SCHEDULE = {
    '2026-10-29': {
        'label': 'Day 1 (29-10-2026 - Thursday)',
        '1st_year': {
            'Science': ('English', '1st Sitting (12:30 PM to 01:15 PM)'),
            'Commerce': ('English', '1st Sitting (12:30 PM to 01:15 PM)'),
            'Arts': ('MIL (Odia)', '2nd Sitting (01:30 PM to 02:15 PM)')
        },
        '2nd_year': {
            'Science': ('English', '1st Sitting (10:30 AM to 11:15 AM)'),
            'Commerce': ('English', '1st Sitting (10:30 AM to 11:15 AM)'),
            'Arts': ('MIL (Odia)', '2nd Sitting (11:30 AM to 12:15 PM)')
        }
    },
    '2026-10-30': {
        'label': 'Day 2 (30-10-2026 - Friday)',
        '1st_year': {
            'Science': ('MIL (Odia / Alt English)', '1st Sitting (12:30 PM to 01:15 PM)'),
            'Commerce': ('MIL (Odia)', '1st Sitting (12:30 PM to 01:15 PM)'),
            'Arts': ('English', '2nd Sitting (01:30 PM to 02:15 PM)')
        },
        '2nd_year': {
            'Science': ('MIL (Odia / Hindi / Alt Eng)', '1st Sitting (10:30 AM to 11:15 AM)'),
            'Commerce': ('MIL (Odia)', '1st Sitting (10:30 AM to 11:15 AM)'),
            'Arts': ('English', '2nd Sitting (11:30 AM to 12:15 PM)')
        }
    },
    '2026-10-31': {
        'label': 'Day 3 (31-10-2026 - Saturday)',
        '1st_year': {
            'Science': ('Physics', '1st Sitting (12:30 PM to 01:15 PM)'),
            'Commerce': ('Accountancy (ACT)', '1st Sitting (12:30 PM to 01:15 PM)'),
            'Arts': ('Political Science', '2nd Sitting (01:30 PM to 02:15 PM)')
        },
        '2nd_year': {
            'Science': ('Physics', '1st Sitting (10:30 AM to 11:15 AM)'),
            'Commerce': ('Accountancy (ACT)', '1st Sitting (10:30 AM to 11:15 AM)'),
            'Arts': ('Political Science', '2nd Sitting (11:30 AM to 12:15 PM)')
        }
    },
    '2026-11-02': {
        'label': 'Day 4 (02-11-2026 - Monday)',
        '1st_year': {
            'Science': ('Chemistry', '1st Sitting (12:30 PM to 01:15 PM)'),
            'Commerce': ('Business Studies & Management (BSM)', '1st Sitting (12:30 PM to 01:15 PM)'),
            'Arts': ('History', '2nd Sitting (01:30 PM to 02:15 PM)')
        },
        '2nd_year': {
            'Science': ('Chemistry', '1st Sitting (10:30 AM to 11:15 AM)'),
            'Commerce': ('Business Studies & Management (BSM)', '1st Sitting (10:30 AM to 11:15 AM)'),
            'Arts': ('History', '2nd Sitting (11:30 AM to 12:15 PM)')
        }
    },
    '2026-11-03': {
        'label': 'Day 5 (03-11-2026 - Tuesday)',
        '1st_year': {
            'Science': ('Mathematics', '1st Sitting (12:30 PM to 01:15 PM)'),
            'Commerce': ('Business Mathematics & Statistics (BMS)', '1st Sitting (12:30 PM to 01:15 PM)'),
            'Arts': ('Economics / Logic', 'Check Sitting: Logic (1st) / Economics (2nd)')
        },
        '2nd_year': {
            'Science': ('Mathematics', '1st Sitting (10:30 AM to 11:15 AM)'),
            'Commerce': ('Business Mathematics & Statistics (BMS)', '1st Sitting (10:30 AM to 11:15 AM)'),
            'Arts': ('Economics / Logic', 'Check Sitting: Logic (1st) / Economics (2nd)')
        }
    },
    '2026-11-04': {
        'label': 'Day 6 (04-11-2026 - Wednesday)',
        '1st_year': {
            'Science': ('Biology', '1st Sitting (12:30 PM to 01:15 PM)'),
            'Commerce': ('Cost Accounting & Banking (CAC)', '1st Sitting (12:30 PM to 01:15 PM)'),
            'Arts': ('EDN / PSY / Opt Odia / Opt Sanskrit', '1st: EDN/PSY | 2nd: Opt Odia/Sanskrit')
        },
        '2nd_year': {
            'Science': ('Botany / Zoology', '1st Sitting (10:30 AM to 11:15 AM)'),
            'Commerce': ('Cost Accounting & Banking (CAC)', '1st Sitting (10:30 AM to 11:15 AM)'),
            'Arts': ('EDN / PSY / Opt Odia / Opt Sanskrit', '1st: EDN/PSY | 2nd: Opt Odia/Sanskrit')
        }
    }
}


def send_telegram_admin_alert(sender_phone, student_name, roll_no, stream_class, room, user_msg):
    """Sends immediate Telegram alert to Admin in a non-blocking background thread."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_ADMIN_CHAT_ID:
        return

    def _send():
        now_str = datetime.now().strftime("%d-%b-%Y %I:%M:%S %p")
        text = f"""🔔 *NEW EXAM BOT QUERY ALERT*
━━━━━━━━━━━━━━━━━━━━━━━━━
📱 *Student Phone:* `{sender_phone}`
👤 *Student Name:* {student_name}
🆔 *Roll Number:* `{roll_no}`
🏛 *Class & Stream:* {stream_class}
📍 *Exam Hall Allotted:* {room}
💬 *Raw Message Sent:* "{user_msg}"
🕒 *Time:* {now_str}
━━━━━━━━━━━━━━━━━━━━━━━━━"""

        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
            payload = {
                "chat_id": TELEGRAM_ADMIN_CHAT_ID,
                "text": text,
                "parse_mode": "Markdown"
            }
            requests.post(url, json=payload, timeout=5)
        except Exception as e:
            print(f"Telegram Alert Error: {e}")

    # Launch in background thread so HTTP response returns instantly
    threading.Thread(target=_send, daemon=True).start()


def process_bot_query(raw_text, sender_phone="Unknown"):
    text = raw_text.strip().upper()
    
    # Smart Regex Matcher: catches IA/IS/IC + 25/26 + 1 to 3 digits
    match = re.search(r'\b(I[ASC])\s*[-]?\s*(2[56])\s*[-]?\s*(\d{1,3})\b', text, re.IGNORECASE)
    
    if not match:
        # Welcome / Help guidance message
        return """🙏 *Namaskar! Radhaballav Higher Secondary School Exam Bot me aapka swagat hai.*

Apne *Aaj ke Exam ka Subject aur Hall No.* dekhne ke liye bus apna *Roll Number* type karke bhejein:

👉 *Examples:*
• *2nd Year Science:* IS25-001 ya is25001
• *2nd Year Arts:* IA25-015 ya ia25015
• *2nd Year Commerce:* IC25-005 ya ic25005
• *1st Year Science:* IS26-001 ya is26001
• *1st Year Arts:* IA26-015 ya ia26015
• *1st Year Commerce:* IC26-005 ya ic26005"""

    stream = match.group(1).upper()
    yr = match.group(2)
    num = match.group(3).zfill(3)
    lookup_key = f"{stream}{yr}-{num}"
    
    if lookup_key not in STUDENT_DB:
        # Send alert to admin about unknown roll
        send_telegram_admin_alert(sender_phone, "UNKNOWN STUDENT", lookup_key, "Unknown", "None", raw_text)
        return f"❌ *Record Not Found!* Roll No *{lookup_key}* hamare college record me nahi mila.\n\nKripya apna Roll No check karke dobara bhejein."

    st = STUDENT_DB[lookup_key]
    
    # Check if student took TC
    if st.get('is_tc'):
        send_telegram_admin_alert(sender_phone, "[TC ISSUED STUDENT]", lookup_key, st['class_year'], "N/A", raw_text)
        return f"""⚠️ *NOTICE: COLLEGE LEAVED / TC ISSUED*
-------------------------------------------------
🆔 *Roll No:* {st['roll_no']}
🏛 *Class:* {st['class_year']} ({st['stream']})

Aapka College Leaving Certificate (TC) issue ho chuka hai. 
Kisi bhi query ke liye college administrative office se sampark karein."""

    # Normal Active Student
    today_str = datetime.now().strftime("%Y-%m-%d")
    # For testing during exam period, default to 2026-10-29 if today is outside
    if today_str not in SCHEDULE:
        today_str = '2026-10-29' # Default to Day 1 for demonstration
        
    day_info = SCHEDULE[today_str]
    batch_key = '1st_year' if '1st' in st['class_year'] else '2nd_year'
    exam_details = day_info[batch_key].get(st['stream'], ('Unknown Subject', 'Check Notice'))
    subject_today, sitting_time = exam_details
    hall_no = st['hall_no']

    # Send Real-Time Alert to Admin's Telegram!
    send_telegram_admin_alert(
        sender_phone=sender_phone,
        student_name=st['name'],
        roll_no=st['roll_no'],
        stream_class=f"{st['class_year']} ({st['stream']})",
        room=hall_no,
        user_msg=raw_text
    )

    reply = f"""🎓 *RADHABALLAV HIGHER SECONDARY SCHOOL*
-------------------------------------------------
👤 *Name:* {st['name']}
🆔 *Roll No:* {st['roll_no']}  |  {st['class_year']} ({st['stream']})

📌 *AAJ KA EXAM ({day_info['label']}):*
📖 *Subject:* {subject_today}
⏰ *Time:* {sitting_time}
📍 *Allotted Hall:* {hall_no}

📚 *Aapke Registered Subjects:*
{st['subjects_formatted']}
-------------------------------------------------
⚠️ *Notice:* Exam shuru hone se 15 minute pehle hall me pahuchein! 👍"""

    return reply


# -------------------------------------------------------------
# HTTP ENDPOINTS
# -------------------------------------------------------------
@app.route('/', methods=['GET'])
def health():
    return jsonify({
        "status": "online",
        "service": "RBHS WhatsApp Student Exam Bot",
        "total_records": len(STUDENT_DB),
        "telegram_notifications": bool(TELEGRAM_BOT_TOKEN and TELEGRAM_ADMIN_CHAT_ID)
    })

@app.route('/webhook', methods=['POST', 'GET'])
def webhook():
    # Handle Meta Webhook Verification Challenge
    if request.method == 'GET':
        mode = request.args.get('hub.mode')
        token = request.args.get('hub.verify_token')
        challenge = request.args.get('hub.challenge')
        if mode == 'subscribe' and token == os.environ.get('WEBHOOK_VERIFY_TOKEN', 'rbhs_secret_123'):
            return challenge, 200
        return 'Forbidden', 403

    # Handle Incoming POST Message
    data = request.json or {}
    raw_text = ''
    sender_phone = 'Unknown'

    # 1. Evolution API format
    if 'data' in data and 'message' in data['data']:
        msg_obj = data['data']['message']
        raw_text = msg_obj.get('conversation') or msg_obj.get('extendedTextMessage', {}).get('text') or ''
        sender_phone = data['data'].get('key', {}).get('remoteJid', 'Unknown').split('@')[0]
    # 2. Meta Cloud API format
    elif 'entry' in data:
        try:
            val = data['entry'][0]['changes'][0]['value']
            msg = val['messages'][0]
            raw_text = msg.get('text', {}).get('body', '')
            sender_phone = msg.get('from', 'Unknown')
        except:
            pass
    # 3. Simple JSON / Generic test format: { "message": "ia26015", "phone": "9437XXXXXX" }
    else:
        raw_text = data.get('message', request.args.get('message', ''))
        sender_phone = data.get('phone', request.args.get('phone', 'Unknown'))

    reply_text = process_bot_query(raw_text, sender_phone)

    return jsonify({
        "reply": reply_text,
        "recipient": sender_phone
    })


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
