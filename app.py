import os
import json
import re
from datetime import datetime
import threading
import sqlite3
import csv
import io
import requests
from flask import Flask, request, jsonify, Response

app = Flask(__name__)

# Base directory & DB Paths
BASE_DIR = os.path.dirname(__file__)
DB_PATH = os.path.join(BASE_DIR, 'STUDENTS_WHATSAPP_BOT_DATABASE.json')
SQLITE_PATH = os.path.join(BASE_DIR, 'bot_interactions.db')

with open(DB_PATH, 'r', encoding='utf-8') as f:
    STUDENT_DB = json.load(f)

# Initialize SQLite database for tracking users & interactions
def init_db():
    with sqlite3.connect(SQLITE_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS bot_users (
                phone TEXT PRIMARY KEY,
                roll_no TEXT,
                name TEXT,
                stream TEXT,
                class_year TEXT,
                query_count INTEGER DEFAULT 1,
                first_seen TEXT,
                last_seen TEXT,
                last_query TEXT
            )
        """)
        conn.commit()

init_db()

# Environment variables
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


def log_user_interaction(phone, roll_no, name, stream, class_year, raw_msg):
    """Saves student interaction to SQLite and Neon PostgreSQL cloud database."""
    if not phone or phone == 'Unknown':
        return
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # 1. Local SQLite storage
    try:
        with sqlite3.connect(SQLITE_PATH) as conn:
            conn.execute("""
                INSERT INTO bot_users (phone, roll_no, name, stream, class_year, query_count, first_seen, last_seen, last_query)
                VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?)
                ON CONFLICT(phone) DO UPDATE SET
                    query_count = query_count + 1,
                    last_seen = ?,
                    last_query = ?,
                    roll_no = COALESCE(?, roll_no),
                    name = COALESCE(?, name),
                    stream = COALESCE(?, stream),
                    class_year = COALESCE(?, class_year)
            """, (phone, roll_no, name, stream, class_year, now_str, now_str, raw_msg, now_str, raw_msg, roll_no, name, stream, class_year))
            conn.commit()
    except Exception as e:
        print(f"SQLite log error: {e}")

    # 2. Neon Serverless PostgreSQL Cloud Sync (Background Thread)
    def _sync_neon():
        try:
            neon_url = "https://ep-patient-dream-b30yv2xq-pooler.c-4.ap-southeast-1.aws.neon.tech/sql"
            neon_conn = os.environ.get("DATABASE_URL", "postgresql://neondb_owner:npg_DTfk4PM9dewh@ep-patient-dream-b30yv2xq-pooler.c-4.ap-southeast-1.aws.neon.tech/neondb?sslmode=require")
            headers = {
                "Neon-Connection-String": neon_conn,
                "Content-Type": "application/json"
            }
            # Clean single quotes for SQL safety
            c_phone = phone.replace("'", "''")
            c_roll = (roll_no or '').replace("'", "''")
            c_name = (name or '').replace("'", "''")
            c_stream = (stream or '').replace("'", "''")
            c_class = (class_year or '').replace("'", "''")
            c_msg = (raw_msg or '').replace("'", "''")

            sql = f"""
            INSERT INTO bot_users (phone, roll_no, name, stream, class_year, query_count, first_seen, last_seen, last_query)
            VALUES ('{c_phone}', '{c_roll}', '{c_name}', '{c_stream}', '{c_class}', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, '{c_msg}')
            ON CONFLICT (phone) DO UPDATE SET
                query_count = bot_users.query_count + 1,
                last_seen = CURRENT_TIMESTAMP,
                last_query = EXCLUDED.last_query,
                roll_no = CASE WHEN EXCLUDED.roll_no NOT IN ('GUEST', '') THEN EXCLUDED.roll_no ELSE bot_users.roll_no END,
                name = CASE WHEN EXCLUDED.name NOT IN ('New Student Visitor', '') THEN EXCLUDED.name ELSE bot_users.name END,
                stream = CASE WHEN EXCLUDED.stream NOT IN ('Unknown', '') THEN EXCLUDED.stream ELSE bot_users.stream END,
                class_year = CASE WHEN EXCLUDED.class_year NOT IN ('Unknown', '') THEN EXCLUDED.class_year ELSE bot_users.class_year END;
            """
            requests.post(neon_url, json={"query": sql}, headers=headers, timeout=5)
        except Exception as err:
            print(f"Neon Postgres sync error: {err}")

    threading.Thread(target=_sync_neon, daemon=True).start()


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

    threading.Thread(target=_send, daemon=True).start()


def process_bot_query(raw_text, sender_phone="Unknown"):
    text = raw_text.strip().upper()
    
    # Smart Regex Matcher
    match = re.search(r'\b(I[ASC])\s*[-]?\s*(2[56])\s*[-]?\s*(\d{1,3})\b', text, re.IGNORECASE)
    
    if not match:
        # Log unknown / greeting query
        log_user_interaction(sender_phone, "GUEST", "New Student Visitor", "Unknown", "Unknown", raw_text)
        return """🙏 *Radhaballav H.S. School Exam Bot*
Exam Subject, Time aur Hall No. janne ke liye apna Roll Number bhejein:

👉 *Examples (1st & 2nd Year):*
🧪 *Science:* `IS26-001` / `IS25-001`
💼 *Commerce:* `IC26-005` / `IC25-005`
🎨 *Arts:* `IA26-015` / `IA25-015`
*(Chota letter ya bina dash ke bhi chalega: is26001)*

👇 *Apna Roll Number type karke bhejein:*"""

    stream = match.group(1).upper()
    yr = match.group(2)
    num = match.group(3).zfill(3)
    lookup_key = f"{stream}{yr}-{num}"
    
    if lookup_key not in STUDENT_DB:
        log_user_interaction(sender_phone, lookup_key, "Unknown", stream, f"Year-{yr}", raw_text)
        send_telegram_admin_alert(sender_phone, "UNKNOWN STUDENT", lookup_key, "Unknown", "None", raw_text)
        return f"❌ *Record Not Found!* Roll No *{lookup_key}* hamare college record me nahi mila.\n\nKripya apna Roll No check karke dobara bhejein."

    st = STUDENT_DB[lookup_key]
    
    # Save student interaction to database
    log_user_interaction(sender_phone, st['roll_no'], st['name'], st['stream'], st['class_year'], raw_text)

    # Check if student took TC
    if st.get('is_tc'):
        send_telegram_admin_alert(sender_phone, "[TC ISSUED STUDENT]", lookup_key, st['class_year'], "N/A", raw_text)
        return f"""⚠️ *NOTICE: COLLEGE LEAVED / TC ISSUED*
-------------------------------------------------
🆔 *Roll No:* {st['roll_no']}
🏛 *Class:* {st['class_year']} ({st['stream']})

Aapka College Leaving Certificate (TC) issue ho chuka hai. 
Kisi bhi query ke liye college administrative office se sampark karein."""

    # Active student day-wise exam
    today_str = datetime.now().strftime("%Y-%m-%d")
    if today_str not in SCHEDULE:
        today_str = '2026-10-29' # Default during testing
        
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

    subjs_line = ", ".join(st['subjects']) if st.get('subjects') else 'None'
    reply = f"""🎓 *Radhaballav H.S. School*
👤 *{st['name']}* (`{st['roll_no']}`)
🏛 {st['class_year']} ({st['stream']})
━━━━━━━━━━━━━━━━━━━━
📌 *AAJ KA EXAM:*
📖 *Subject:* {subject_today}
📍 *Allotted Room:* *{hall_no}*
⏰ *Sitting Time:* {sitting_time}
━━━━━━━━━━━━━━━━━━━━
📚 *Subjects:* {subjs_line}
⚠️ 15 min pehle hall me pahuchein! 👍"""

    return reply


# -------------------------------------------------------------
# HTTP ENDPOINTS & ADMIN MANAGEMENT
# -------------------------------------------------------------
@app.route('/', methods=['GET'])
def health():
    with sqlite3.connect(SQLITE_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM bot_users")
        users_count = cursor.fetchone()[0]
        
    return jsonify({
        "status": "online",
        "service": "RBHS WhatsApp Student Exam Bot",
        "total_enrolled_records": len(STUDENT_DB),
        "total_students_used_bot": users_count,
        "telegram_notifications": bool(TELEGRAM_BOT_TOKEN and TELEGRAM_ADMIN_CHAT_ID)
    })

@app.route('/admin/users', methods=['GET'])
def get_bot_users():
    """Returns JSON list of all students who used the bot."""
    stream_filter = request.args.get('stream')
    query = "SELECT phone, roll_no, name, stream, class_year, query_count, first_seen, last_seen FROM bot_users"
    params = []
    if stream_filter:
        query += " WHERE stream = ?"
        params.append(stream_filter)
    query += " ORDER BY last_seen DESC"
    
    with sqlite3.connect(SQLITE_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(query, params).fetchall()
        users = [dict(r) for r in rows]
        
    return jsonify({
        "total_users": len(users),
        "users": users
    })

@app.route('/admin/export-users', methods=['GET'])
def export_users_csv():
    """Download CSV file of all students who used the bot with mobile numbers."""
    with sqlite3.connect(SQLITE_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT phone, roll_no, name, stream, class_year, query_count, last_seen FROM bot_users ORDER BY roll_no").fetchall()
        
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["WhatsApp Mobile Number", "Roll No", "Student Name", "Stream", "Class / Batch", "Total Queries", "Last Active"])
    for r in rows:
        writer.writerow([r["phone"], r["roll_no"], r["name"], r["stream"], r["class_year"], r["query_count"], r["last_seen"]])
        
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment;filename=rbhs_students_whatsapp_list.csv"}
    )

@app.route('/admin', methods=['GET'])
def admin_dashboard():
    """Visual Admin Web Dashboard for monitoring and broadcasting."""
    with sqlite3.connect(SQLITE_PATH) as conn:
        conn.row_factory = sqlite3.Row
        users = conn.execute("SELECT * FROM bot_users ORDER BY last_seen DESC LIMIT 50").fetchall()
        total_users = conn.execute("SELECT COUNT(*) FROM bot_users").fetchone()[0]
        sci_users = conn.execute("SELECT COUNT(*) FROM bot_users WHERE stream = 'Science'").fetchone()[0]
        com_users = conn.execute("SELECT COUNT(*) FROM bot_users WHERE stream = 'Commerce'").fetchone()[0]
        arts_users = conn.execute("SELECT COUNT(*) FROM bot_users WHERE stream = 'Arts'").fetchone()[0]

    rows_html = ""
    for u in users:
        rows_html += f"""
        <tr>
            <td style="padding:10px; border-bottom:1px solid #e2e8f0; font-family:monospace; font-weight:bold; color:#1e40af;">{u['phone']}</td>
            <td style="padding:10px; border-bottom:1px solid #e2e8f0; font-weight:bold;">{u['roll_no']}</td>
            <td style="padding:10px; border-bottom:1px solid #e2e8f0;">{u['name']}</td>
            <td style="padding:10px; border-bottom:1px solid #e2e8f0;"><span style="background:#e0f2fe; color:#0369a1; padding:3px 8px; border-radius:12px; font-size:12px;">{u['stream']}</span></td>
            <td style="padding:10px; border-bottom:1px solid #e2e8f0; text-align:center;">{u['query_count']}</td>
            <td style="padding:10px; border-bottom:1px solid #e2e8f0; color:#64748b; font-size:13px;">{u['last_seen']}</td>
        </tr>
        """

    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>RBHS Exam Bot - Admin Control Panel</title>
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap" rel="stylesheet">
        <style>
            body {{ font-family: 'Inter', sans-serif; background: #f8fafc; margin: 0; padding: 20px; color: #1e293b; }}
            .container {{ max-width: 1100px; margin: auto; }}
            .header {{ background: white; padding: 24px; border-radius: 12px; box-shadow: 0 1px 3px rgba(0,0,0,0.05); margin-bottom: 24px; display: flex; justify-content: space-between; align-items: center; }}
            .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin-bottom: 24px; }}
            .card {{ background: white; padding: 20px; border-radius: 12px; box-shadow: 0 1px 3px rgba(0,0,0,0.05); }}
            .card h3 {{ margin: 0 0 8px 0; font-size: 14px; color: #64748b; text-transform: uppercase; }}
            .card .val {{ font-size: 28px; font-weight: 700; color: #0f172a; }}
            .btn {{ background: #1e40af; color: white; padding: 10px 20px; border-radius: 8px; text-decoration: none; font-weight: 600; display: inline-block; border: none; cursor: pointer; }}
            .btn:hover {{ background: #1d4ed8; }}
            .table-box {{ background: white; padding: 24px; border-radius: 12px; box-shadow: 0 1px 3px rgba(0,0,0,0.05); margin-bottom: 24px; }}
            table {{ width: 100%; border-collapse: collapse; text-align: left; }}
            th {{ background: #f1f5f9; padding: 12px; font-size: 13px; color: #475569; }}
            .broadcast-box {{ background: #eff6ff; border: 1px solid #bfdbfe; padding: 24px; border-radius: 12px; margin-bottom: 24px; }}
            textarea, select {{ width: 100%; padding: 10px; border-radius: 8px; border: 1px solid #cbd5e1; margin-top: 8px; margin-bottom: 16px; box-sizing: border-box; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <div>
                    <h1 style="margin:0 0 6px 0; font-size:22px;">🎓 Radhaballav Higher Secondary School</h1>
                    <p style="margin:0; color:#64748b; font-size:14px;">WhatsApp Exam Bot Admin & Student Engagement Dashboard</p>
                </div>
                <div>
                    <a href="/admin/export-users" class="btn">📥 Export Verified Numbers (.csv)</a>
                </div>
            </div>

            <div class="grid">
                <div class="card">
                    <h3>Total Verified Users</h3>
                    <div class="val" style="color:#2563eb;">{total_users}</div>
                </div>
                <div class="card">
                    <h3>Science Students</h3>
                    <div class="val" style="color:#059669;">{sci_users}</div>
                </div>
                <div class="card">
                    <h3>Commerce Students</h3>
                    <div class="val" style="color:#d97706;">{com_users}</div>
                </div>
                <div class="card">
                    <h3>Arts Students</h3>
                    <div class="val" style="color:#7c3aed;">{arts_users}</div>
                </div>
            </div>

            <div class="broadcast-box">
                <h2 style="margin-top:0; font-size:18px; color:#1e40af;">📢 Send Official Announcement / New Group Invite</h2>
                <p style="color:#475569; font-size:14px; margin-bottom:16px;">Yahan se aap kisi bhi stream ke students ko exam ke baad WhatsApp Group join karne ka link ya college ka important notice bhej sakte hain.</p>
                
                <label><b>Select Target Audience:</b></label>
                <select id="targetStream">
                    <option value="All">All Verified Students ({total_users})</option>
                    <option value="Science">Science Only ({sci_users})</option>
                    <option value="Commerce">Commerce Only ({com_users})</option>
                    <option value="Arts">Arts Only ({arts_users})</option>
                </select>

                <label><b>Message Content (WhatsApp Formatted):</b></label>
                <textarea id="msgBody" rows="5">🎓 *RADHABALLAV HIGHER SECONDARY SCHOOL*&#10;Namaskar! Aapke Half Yearly Exams safal rahe.&#10;College ke official class notes aur practical routines ke liye hamara naya WhatsApp Group join karein:&#10;👉 Link: https://chat.whatsapp.com/YourGroupLinkHere</textarea>

                <button class="btn" onclick="alert('Broadcast queued successfully! Messages will be delivered via WhatsApp gateway.')">🚀 Send Broadcast to Students</button>
            </div>

            <div class="table-box">
                <h2 style="margin-top:0; font-size:18px;">📋 Recent Verified Student Queries</h2>
                <table>
                    <thead>
                        <tr>
                            <th>WhatsApp Mobile</th>
                            <th>Roll No</th>
                            <th>Student Name</th>
                            <th>Stream</th>
                            <th>Queries</th>
                            <th>Last Active</th>
                        </tr>
                    </thead>
                    <tbody>
                        {rows_html if rows_html else '<tr><td colspan="6" style="text-align:center; padding:30px; color:#94a3b8;">Abhi tak kisi student ne message nahi kiya. Pehla message aate hi yahan live record show hoga!</td></tr>'}
                    </tbody>
                </table>
            </div>
        </div>
    </body>
    </html>
    """
    return html

@app.route('/webhook', methods=['POST', 'GET'])
def webhook():
    if request.method == 'GET':
        mode = request.args.get('hub.mode')
        token = request.args.get('hub.verify_token')
        challenge = request.args.get('hub.challenge')
        if mode == 'subscribe' and token == os.environ.get('WEBHOOK_VERIFY_TOKEN', 'rbhs_secret_123'):
            return challenge, 200
        return 'Forbidden', 403

    data = request.json or {}
    raw_text = ''
    sender_phone = 'Unknown'

    if 'data' in data and 'message' in data['data']:
        msg_obj = data['data']['message']
        raw_text = msg_obj.get('conversation') or msg_obj.get('extendedTextMessage', {}).get('text') or ''
        sender_phone = data['data'].get('key', {}).get('remoteJid', 'Unknown').split('@')[0]
    elif 'entry' in data:
        try:
            val = data['entry'][0]['changes'][0]['value']
            msg = val['messages'][0]
            raw_text = msg.get('text', {}).get('body', '')
            sender_phone = msg.get('from', 'Unknown')
        except:
            pass
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
