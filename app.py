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

# Neon Cloud Serverless Database Connection
NEON_URL = "https://ep-patient-dream-b30yv2xq-pooler.c-4.ap-southeast-1.aws.neon.tech/sql"
NEON_CONN = os.environ.get("DATABASE_URL", "postgresql://neondb_owner:npg_DTfk4PM9dewh@ep-patient-dream-b30yv2xq-pooler.c-4.ap-southeast-1.aws.neon.tech/neondb?sslmode=require")

def neon_query(sql, return_rows=False):
    """Executes SQL against Neon Serverless PostgreSQL over HTTP."""
    headers = {
        "Neon-Connection-String": NEON_CONN,
        "Content-Type": "application/json"
    }
    try:
        res = requests.post(NEON_URL, json={"query": sql}, headers=headers, timeout=8)
        if res.status_code == 200:
            if return_rows:
                return res.json().get("rows", [])
            return True
        return [] if return_rows else False
    except Exception as err:
        print(f"Neon query error: {err}")
        return [] if return_rows else False

def load_students_from_neon():
    """Loads all student master records directly from Neon Cloud PostgreSQL."""
    try:
        sql = "SELECT roll_no, name, stream, class_year, batch, is_tc, status, hall_no, exam_timing, subjects FROM students;"
        rows = neon_query(sql, return_rows=True)
        if rows and len(rows) > 0:
            db = {}
            for r in rows:
                roll = r['roll_no']
                clean = roll.upper()
                subjs = [s.strip() for s in (r.get('subjects') or '').split(',') if s.strip()]
                st_data = {
                    'roll_no': roll,
                    'name': r['name'],
                    'stream': r['stream'],
                    'class_year': r['class_year'],
                    'batch': r.get('batch', ''),
                    'is_tc': bool(r.get('is_tc')),
                    'status': r.get('status', 'ACTIVE'),
                    'subjects': subjs,
                    'subjects_formatted': "\n".join([f"  • {s}" for s in subjs]),
                    'hall_no': r.get('hall_no', 'Not Assigned'),
                    'exam_timing': r.get('exam_timing', 'Check Notice')
                }
                db[clean] = st_data
                db[clean.replace('-', '')] = st_data
            print(f"✅ Loaded {len(rows)} student records directly from Neon Cloud PostgreSQL!")
            return db
    except Exception as e:
        print(f"Neon initial load error: {e}")
    return None

STUDENT_DB = load_students_from_neon()
if not STUDENT_DB:
    with open(DB_PATH, 'r', encoding='utf-8') as f:
        STUDENT_DB = json.load(f)
    print(f"Loaded {len(STUDENT_DB)} records from local JSON fallback.")

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
        conn.execute("""
            CREATE TABLE IF NOT EXISTS broadcast_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phone TEXT NOT NULL,
                name TEXT,
                message TEXT NOT NULL,
                status TEXT DEFAULT 'PENDING',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                sent_at TIMESTAMP
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
            'Science': ('MIL (Odia / Alt English)', '1st Sitting (12:30 PM to 01:15 PM)'),
            'Commerce': ('MIL (Odia)', '1st Sitting (12:30 PM to 01:15 PM)'),
            'Arts': ('MIL (Odia)', '2nd Sitting (01:30 PM to 02:15 PM)')
        },
        '2nd_year': {
            'Science': ('MIL (Odia / Hindi / Alt Eng)', '1st Sitting (10:30 AM to 11:15 AM)'),
            'Commerce': ('MIL (Odia)', '1st Sitting (10:30 AM to 11:15 AM)'),
            'Arts': ('MIL (Odia)', '2nd Sitting (11:30 AM to 12:15 PM)')
        }
    },
    '2026-10-30': {
        'label': 'Day 2 (30-10-2026 - Friday)',
        '1st_year': {
            'Science': ('English', '1st Sitting (12:30 PM to 01:15 PM)'),
            'Commerce': ('English', '1st Sitting (12:30 PM to 01:15 PM)'),
            'Arts': ('English', '2nd Sitting (01:30 PM to 02:15 PM)')
        },
        '2nd_year': {
            'Science': ('English', '1st Sitting (10:30 AM to 11:15 AM)'),
            'Commerce': ('English', '1st Sitting (10:30 AM to 11:15 AM)'),
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


# Common greetings and non-name commands
GREETINGS_OR_COMMANDS = {
    'HI', 'HII', 'HIII', 'HELLO', 'HELO', 'HEY', 'HEYY', 'HELP',
    'MENU', 'START', 'INFO', 'NAMASTE', 'NAMASKAR', 'PRANAM',
    'EXAM', 'ROUTINE', 'SCHEDULE', 'TIMETABLE', 'TIME TABLE', 'TIME',
    'BOT', 'OK', 'OKAY', 'THANKS', 'THANK YOU', 'DHANYAWAD', 'TEST',
    'YES', 'NO', 'BYE', 'GOOD MORNING', 'GOOD AFTERNOON', 'GOOD EVENING'
}

def find_students_by_name(query_str):
    """
    Searches for students by name across local cache and Neon Cloud PostgreSQL.
    Supports uppercase, lowercase, mixed case, partial names, first/last names.
    Returns a deduplicated list of matching student dictionaries.
    """
    if not query_str:
        return []
        
    # Clean query: strip conversational filler words (Hindi/English)
    cleaned = re.sub(r'(?i)\b(mera naam|my name is|student name|student|naam|name|search|roll no of|roll number of|roll no|roll number|kya hai|batao|bataiye|dekhna hai|hai|ka|ki)\b', ' ', query_str)
    cleaned = re.sub(r'[^a-zA-Z\s]', ' ', cleaned).strip()
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    
    if len(cleaned) < 2:
        return []
        
    query_upper = cleaned.upper()
    query_words = [w for w in query_upper.split() if len(w) >= 2]
    
    unique_students = {}
    if STUDENT_DB:
        for k, st in STUDENT_DB.items():
            r = st.get('roll_no')
            if r and r not in unique_students:
                unique_students[r] = st

    matches = []
    for r, st in unique_students.items():
        name = (st.get('name') or '').upper().strip()
        if not name:
            continue
            
        # Priority 1: Exact full name match
        if name == query_upper:
            matches.append((st, 1))
            continue
            
        # Priority 2: All query words present with word boundaries
        if query_words:
            all_words_found = True
            for w in query_words:
                if not re.search(r'\b' + re.escape(w) + r'\b', name):
                    all_words_found = False
                    break
            if all_words_found:
                matches.append((st, 2))
                continue

    # Priority 3: Fallback substring match if no whole-word match
    if not matches and len(query_upper) >= 3:
        for r, st in unique_students.items():
            name = (st.get('name') or '').upper().strip()
            if query_upper in name:
                matches.append((st, 3))

    # Priority 4: Query Neon PostgreSQL directly if local search found 0 results
    if not matches:
        try:
            sql_escaped = query_upper.replace("'", "''")
            sql = f"SELECT roll_no, name, stream, class_year, batch, is_tc, status, hall_no, exam_timing, subjects FROM students WHERE UPPER(name) LIKE '%{sql_escaped}%' LIMIT 10;"
            rows = neon_query(sql, return_rows=True)
            if rows:
                for r in rows:
                    subjs = [s.strip() for s in (r.get('subjects') or '').split(',') if s.strip()]
                    st_obj = {
                        'roll_no': r['roll_no'],
                        'name': r['name'],
                        'stream': r['stream'],
                        'class_year': r['class_year'],
                        'batch': r.get('batch', ''),
                        'is_tc': bool(r.get('is_tc')),
                        'status': r.get('status', 'ACTIVE'),
                        'subjects': subjs,
                        'subjects_formatted': "\n".join([f"  • {s}" for s in subjs]),
                        'hall_no': r.get('hall_no', 'Not Assigned'),
                        'exam_timing': r.get('exam_timing', 'Check Notice')
                    }
                    matches.append((st_obj, 3))
        except Exception as e:
            print(f"Neon live name search error: {e}")

    matches.sort(key=lambda x: x[1])
    seen_rolls = set()
    deduped = []
    for m in matches:
        st = m[0]
        roll = st.get('roll_no')
        if roll not in seen_rolls:
            seen_rolls.add(roll)
            deduped.append(st)
    return deduped


def format_short_class(class_year_str):
    """Formats verbose class names into compact, elegant labels."""
    if not class_year_str:
        return ""
    if '1st' in class_year_str:
        return "+2 1st Yr"
    elif '2nd' in class_year_str:
        return "+2 2nd Yr"
    return class_year_str.split('(')[0].strip()


def process_bot_query(raw_text, sender_phone="Unknown"):
    text = raw_text.strip().upper()
    
    # 1. Smart Regex Matcher: catches IA/IS/IC (or A/S/C) + 25/26 + 1 to 4 digits
    match = re.search(r'\b(I?[ASC])\s*[-]?\s*(2[56])\s*[-]?\s*(\d{1,4})\b', text, re.IGNORECASE)
    
    if not match:
        clean_text = re.sub(r'[^a-zA-Z\s]', ' ', raw_text).strip()
        is_greeting = clean_text.upper() in GREETINGS_OR_COMMANDS or len(clean_text) < 2
        
        # If user sent a greeting or menu request
        if is_greeting:
            log_user_interaction(sender_phone, "GUEST", "New Student Visitor", "Unknown", "Unknown", raw_text)
            return """🏛️ *RBHS EXAM DESK*
───────────────
Check Today's Paper, Hall & Timing:

• *Roll No:* `IS26-001` ya `is26001`
• *Naam:* `Rahul Das` ya `Smaranika`
───────────────
👇 *Apna Roll No ya Naam likh kar bhejein:*"""

        # Otherwise, attempt to find student by Name (case-insensitive)
        name_matches = find_students_by_name(raw_text)
        
        if not name_matches:
            log_user_interaction(sender_phone, "GUEST", f"Not Found: {raw_text[:25]}", "Unknown", "Unknown", raw_text)
            return f"""❌ *Record Not Found*
───────────────
*"{raw_text.strip()}"* college record me nahi mila.

💡 *Tips:*
• Naam ki spelling check karein (*Rahul Sahoo*)
• Ya Roll No bhejein (`IS26-001` / `is26001`)"""

        # If exactly 1 student found
        if len(name_matches) == 1:
            st = name_matches[0]
            log_user_interaction(sender_phone, st['roll_no'], st['name'], st['stream'], st['class_year'], raw_text)
            send_telegram_admin_alert(
                sender_phone=sender_phone,
                student_name=st['name'],
                roll_no=st['roll_no'],
                stream_class=f"{st['class_year']} ({st['stream']})",
                room=st.get('hall_no', 'N/A'),
                user_msg=f"[Name Search] {raw_text}"
            )
            short_cls = format_short_class(st.get('class_year', ''))
            cls_stream = f"{short_cls} • {st['stream']}" if short_cls else st.get('stream', '')
            hall = st.get('hall_no', 'Notice Board')

            return f"""🔍 *STUDENT FOUND*
───────────────
👤 *{st['name']}*
🆔 Roll No: `{st['roll_no']}`
🎓 {cls_stream}
📍 Hall: *{hall}*
───────────────
👉 Aaj ke paper ke liye bhejein: `{st['roll_no']}`"""

        # If multiple students found with the same name
        log_user_interaction(sender_phone, "MULTI_MATCH", f"Matches: {len(name_matches)}", "Unknown", "Unknown", raw_text)
        num_emojis = ['1️⃣', '2️⃣', '3️⃣', '4️⃣', '5️⃣']
        list_text = []
        for idx, st in enumerate(name_matches[:5]):
            emoji = num_emojis[idx] if idx < len(num_emojis) else f"{idx+1}."
            short_cls = format_short_class(st.get('class_year', ''))
            cls_str = f"{short_cls} {st.get('stream', '')}".strip()
            hall_str = st.get('hall_no', 'N/A')
            list_text.append(
                f"{emoji} *{st['name']}* • `{st['roll_no']}`\n"
                f"   ↳ {cls_str} | Hall: *{hall_str}*"
            )

        results_formatted = "\n\n".join(list_text)
        extra_note = ""
        if len(name_matches) > 5:
            extra_note = f"\n   ↳ *+{len(name_matches)-5} more students...* Pura naam likhein."

        return f"""🔍 *{len(name_matches)} Students found for "{raw_text.strip()}":*
───────────────
{results_formatted}{extra_note}
───────────────
👉 Routine dekhne ke liye apna *Roll No* bhejein."""

    # 2. Roll Number matched
    stream = match.group(1).upper()
    if not stream.startswith('I'):
        stream = 'I' + stream
    yr = match.group(2)
    num = str(int(match.group(3))).zfill(3)
    lookup_key = f"{stream}{yr}-{num}"
    
    if lookup_key not in STUDENT_DB:
        # Live Query Neon Cloud Database in real-time
        try:
            clean_search = lookup_key.replace('-', '')
            sql = f"SELECT roll_no, name, stream, class_year, batch, is_tc, status, hall_no, exam_timing, subjects FROM students WHERE UPPER(roll_no) = '{lookup_key}' OR REPLACE(UPPER(roll_no), '-', '') = '{clean_search}' LIMIT 1;"
            rows = neon_query(sql, return_rows=True)
            if rows and len(rows) > 0:
                r = rows[0]
                subjs = [s.strip() for s in (r.get('subjects') or '').split(',') if s.strip()]
                STUDENT_DB[lookup_key] = {
                    'roll_no': r['roll_no'],
                    'name': r['name'],
                    'stream': r['stream'],
                    'class_year': r['class_year'],
                    'batch': r.get('batch', ''),
                    'is_tc': bool(r.get('is_tc')),
                    'status': r.get('status', 'ACTIVE'),
                    'subjects': subjs,
                    'subjects_formatted': "\n".join([f"  • {s}" for s in subjs]),
                    'hall_no': r.get('hall_no', 'Not Assigned'),
                    'exam_timing': r.get('exam_timing', 'Check Notice')
                }
        except Exception as e:
            print(f"Neon live lookup error: {e}")

    if lookup_key not in STUDENT_DB:
        log_user_interaction(sender_phone, lookup_key, "Unknown", stream, f"Year-{yr}", raw_text)
        send_telegram_admin_alert(sender_phone, "UNKNOWN STUDENT", lookup_key, "Unknown", "None", raw_text)
        return f"""❌ *Record Not Found*
───────────────
Roll No *{lookup_key}* college record me nahi mila.
Kripya Roll No check karke dobara bhejein."""

    st = STUDENT_DB[lookup_key]
    
    # Save student interaction to database
    log_user_interaction(sender_phone, st['roll_no'], st['name'], st['stream'], st['class_year'], raw_text)

    # Check if student took TC
    if st.get('is_tc'):
        send_telegram_admin_alert(sender_phone, "[TC ISSUED STUDENT]", lookup_key, st['class_year'], "N/A", raw_text)
        short_cls = format_short_class(st['class_year'])
        return f"""⚠️ *COLLEGE LEAVING / TC ISSUED*
───────────────
🆔 *Roll No:* `{st['roll_no']}`
🎓 {short_cls} ({st['stream']})
───────────────
Aapka TC issue ho chuka hai. 
Administrative office se sampark karein."""

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

    short_cls = format_short_class(st.get('class_year', ''))
    cls_stream = f"{short_cls} • {st['stream']}" if short_cls else st.get('stream', '')

    reply = f"""🏛️ *RBHS EXAM DESK*
───────────────
👤 *{st['name']}* | `{st['roll_no']}`
🎓 {cls_stream}
───────────────
📖 *Today:* *{subject_today}*
📍 *Hall:* *{hall_no}*
⏰ *Time:* {sitting_time}
───────────────
⚠️ *15 min pehle pahuchein. All the best!* 👍"""

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
        "primary_database": "Neon Serverless PostgreSQL Cloud Database",
        "total_enrolled_records": len(STUDENT_DB),
        "total_students_used_bot": users_count,
        "telegram_notifications": bool(TELEGRAM_BOT_TOKEN and TELEGRAM_ADMIN_CHAT_ID)
    })

@app.route('/admin/whatsapp-status', methods=['GET'])
def admin_whatsapp_status():
    """Checks the internal Node.js WhatsApp Gateway health."""
    try:
        r = requests.get('http://127.0.0.1:5050/status', timeout=2)
        if r.status_code == 200:
            return jsonify(r.json())
    except:
        pass
    return jsonify({"isConnected": False, "connectedUser": None, "hasQR": False})

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
    rows = neon_query("SELECT phone, roll_no, name, stream, class_year, query_count, last_seen FROM bot_users ORDER BY roll_no;", return_rows=True)
    if not rows:
        with sqlite3.connect(SQLITE_PATH) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT phone, roll_no, name, stream, class_year, query_count, last_seen FROM bot_users ORDER BY roll_no").fetchall()
            rows = [dict(r) for r in rows]
        
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["WhatsApp Mobile Number", "Roll No", "Student Name", "Stream", "Class / Batch", "Total Queries", "Last Active"])
    for r in rows:
        writer.writerow([r.get("phone"), r.get("roll_no"), r.get("name"), r.get("stream"), r.get("class_year"), r.get("query_count"), r.get("last_seen")])
        
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment;filename=rbhs_students_whatsapp_list.csv"}
    )


@app.route('/admin/send-broadcast', methods=['POST'])
def send_broadcast():
    """Queue broadcast messages to students via Neon & SQLite queue."""
    data = request.json or {}
    target = data.get('target', 'All')
    message_text = (data.get('message') or '').strip()
    test_phone = (data.get('test_phone') or '').strip()

    if not message_text:
        return jsonify({"success": False, "error": "Message content cannot be empty!"}), 400

    recipients = []
    if test_phone:
        clean_p = test_phone if test_phone.startswith('+') else '+' + test_phone
        recipients.append({"phone": clean_p, "name": "Admin Test"})
    else:
        where_sql = ""
        if target in ['Science', 'Commerce', 'Arts']:
            where_sql = f"WHERE stream = '{target}'"
        
        neon_recipients = neon_query(f"SELECT DISTINCT phone, name FROM bot_users {where_sql};", return_rows=True)
        if neon_recipients:
            recipients = [u for u in neon_recipients if u.get('phone') and u.get('phone') != 'Unknown']
        else:
            with sqlite3.connect(SQLITE_PATH) as conn:
                conn.row_factory = sqlite3.Row
                q = "SELECT DISTINCT phone, name FROM bot_users"
                if target in ['Science', 'Commerce', 'Arts']:
                    q += f" WHERE stream = '{target}'"
                rows = conn.execute(q).fetchall()
                recipients = [dict(r) for r in rows if r['phone'] and r['phone'] != 'Unknown']

    if not recipients:
        return jsonify({"success": False, "error": f"Koi student nahi mila stream: {target}. Pehle student bot me query karega tabhi uska number add hoga."}), 400

    # Insert into Broadcast Queue
    clean_msg = message_text.replace("'", "''")
    queued_count = 0

    for r in recipients:
        c_phone = str(r.get('phone', '')).replace("'", "''")
        c_name = str(r.get('name', 'Student')).replace("'", "''")
        if not c_phone:
            continue

        sql = f"""
        INSERT INTO broadcast_queue (phone, name, message, status, created_at)
        VALUES ('{c_phone}', '{c_name}', '{clean_msg}', 'PENDING', CURRENT_TIMESTAMP);
        """
        neon_query(sql)
        try:
            with sqlite3.connect(SQLITE_PATH) as conn:
                conn.execute("INSERT INTO broadcast_queue (phone, name, message, status) VALUES (?, ?, ?, 'PENDING')",
                             (c_phone, c_name, message_text))
                conn.commit()
        except:
            pass
        queued_count += 1

    return jsonify({
        "success": True,
        "count": queued_count,
        "message": f"✅ {queued_count} messages queue me add ho gaye! WhatsApp gateway inhe 2-3 second delay ke sath safe delivery karega."
    })


@app.route('/api/pending-broadcasts', methods=['GET'])
def get_pending_broadcasts():
    """WhatsApp Gateway Baileys background poller fetches pending messages."""
    rows = neon_query("SELECT id, phone, name, message FROM broadcast_queue WHERE status = 'PENDING' ORDER BY id ASC LIMIT 5;", return_rows=True)
    if not rows:
        try:
            with sqlite3.connect(SQLITE_PATH) as conn:
                conn.row_factory = sqlite3.Row
                r = conn.execute("SELECT id, phone, name, message FROM broadcast_queue WHERE status = 'PENDING' ORDER BY id ASC LIMIT 5").fetchall()
                rows = [dict(x) for x in r]
        except:
            rows = []
    return jsonify({"messages": rows})


@app.route('/api/mark-broadcast-sent', methods=['POST'])
def mark_broadcast_sent():
    """WhatsApp Gateway marks delivered or failed broadcast messages."""
    data = request.json or {}
    msg_id = data.get('id')
    status = data.get('status', 'SENT')

    if not msg_id:
        return jsonify({"success": False, "error": "Missing id"}), 400

    neon_query(f"UPDATE broadcast_queue SET status = '{status}', sent_at = CURRENT_TIMESTAMP WHERE id = {msg_id};")
    try:
        with sqlite3.connect(SQLITE_PATH) as conn:
            conn.execute("UPDATE broadcast_queue SET status = ?, sent_at = CURRENT_TIMESTAMP WHERE id = ?", (status, msg_id))
            conn.commit()
    except:
        pass

    return jsonify({"success": True})


@app.route('/admin/broadcast-status', methods=['GET'])
def broadcast_status():
    """Provides live metrics and recent items for the Admin UI."""
    counts = neon_query("""
        SELECT 
            COUNT(*) as total,
            COUNT(*) FILTER (WHERE status = 'PENDING') as pending,
            COUNT(*) FILTER (WHERE status = 'SENT') as sent,
            COUNT(*) FILTER (WHERE status = 'FAILED') as failed
        FROM broadcast_queue;
    """, return_rows=True)

    recent = neon_query("SELECT id, phone, name, status, sent_at, created_at FROM broadcast_queue ORDER BY id DESC LIMIT 10;", return_rows=True)

    total, pending, sent, failed = 0, 0, 0, 0
    if counts:
        c = counts[0]
        total = int(c.get('total') or 0)
        pending = int(c.get('pending') or 0)
        sent = int(c.get('sent') or 0)
        failed = int(c.get('failed') or 0)

    return jsonify({
        "total": total,
        "pending": pending,
        "sent": sent,
        "failed": failed,
        "recent": recent or []
    })


@app.route('/admin', methods=['GET'])
def admin_dashboard():
    """Visual Admin Web Dashboard for monitoring and broadcasting."""
    # 1. Fetch Students Stats from Neon
    counts = neon_query("""
        SELECT 
            COUNT(*) as total,
            COUNT(*) FILTER (WHERE stream = 'Science') as sci,
            COUNT(*) FILTER (WHERE stream = 'Commerce') as com,
            COUNT(*) FILTER (WHERE stream = 'Arts') as arts
        FROM bot_users;
    """, return_rows=True)

    users = neon_query("SELECT * FROM bot_users ORDER BY last_seen DESC LIMIT 50;", return_rows=True)

    if counts and counts[0].get('total') is not None:
        c = counts[0]
        total_users = int(c.get('total') or 0)
        sci_users = int(c.get('sci') or 0)
        com_users = int(c.get('com') or 0)
        arts_users = int(c.get('arts') or 0)
    else:
        with sqlite3.connect(SQLITE_PATH) as conn:
            conn.row_factory = sqlite3.Row
            users = conn.execute("SELECT * FROM bot_users ORDER BY last_seen DESC LIMIT 50").fetchall()
            users = [dict(u) for u in users]
            total_users = conn.execute("SELECT COUNT(*) FROM bot_users").fetchone()[0]
            sci_users = conn.execute("SELECT COUNT(*) FROM bot_users WHERE stream = 'Science'").fetchone()[0]
            com_users = conn.execute("SELECT COUNT(*) FROM bot_users WHERE stream = 'Commerce'").fetchone()[0]
            arts_users = conn.execute("SELECT COUNT(*) FROM bot_users WHERE stream = 'Arts'").fetchone()[0]

    # 2. Fetch Broadcast Stats
    b_counts = neon_query("""
        SELECT 
            COUNT(*) as total,
            COUNT(*) FILTER (WHERE status = 'PENDING') as pending,
            COUNT(*) FILTER (WHERE status = 'SENT') as sent
        FROM broadcast_queue;
    """, return_rows=True)

    b_total, b_pending, b_sent = 0, 0, 0
    if b_counts and b_counts[0].get('total') is not None:
        bc = b_counts[0]
        b_total = int(bc.get('total') or 0)
        b_pending = int(bc.get('pending') or 0)
        b_sent = int(bc.get('sent') or 0)

    rows_html = ""
    for u in (users or []):
        phone_val = u.get('phone', '')
        roll_val = u.get('roll_no', '')
        name_val = u.get('name', '')
        stream_val = u.get('stream', '')
        q_cnt = u.get('query_count', 1)
        last_s = str(u.get('last_seen', ''))[:19]
        rows_html += f"""
        <tr>
            <td style="padding:10px; border-bottom:1px solid #e2e8f0; font-family:monospace; font-weight:bold; color:#1e40af;">{phone_val}</td>
            <td style="padding:10px; border-bottom:1px solid #e2e8f0; font-weight:bold;">{roll_val}</td>
            <td style="padding:10px; border-bottom:1px solid #e2e8f0;">{name_val}</td>
            <td style="padding:10px; border-bottom:1px solid #e2e8f0;"><span style="background:#e0f2fe; color:#0369a1; padding:3px 8px; border-radius:12px; font-size:12px;">{stream_val}</span></td>
            <td style="padding:10px; border-bottom:1px solid #e2e8f0; text-align:center;">{q_cnt}</td>
            <td style="padding:10px; border-bottom:1px solid #e2e8f0; color:#64748b; font-size:13px;">{last_s}</td>
        </tr>
        """

    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>RBHS Exam Bot - Admin Control Panel</title>
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
        <style>
            body {{ font-family: 'Inter', sans-serif; background: #f8fafc; margin: 0; padding: 20px; color: #1e293b; }}
            .container {{ max-width: 1100px; margin: auto; }}
            .header {{ background: white; padding: 24px; border-radius: 12px; box-shadow: 0 1px 3px rgba(0,0,0,0.05); margin-bottom: 24px; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px; }}
            .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin-bottom: 24px; }}
            .card {{ background: white; padding: 20px; border-radius: 12px; box-shadow: 0 1px 3px rgba(0,0,0,0.05); }}
            .card h3 {{ margin: 0 0 8px 0; font-size: 13px; color: #64748b; text-transform: uppercase; letter-spacing: 0.5px; }}
            .card .val {{ font-size: 28px; font-weight: 700; color: #0f172a; }}
            .btn {{ background: #1e40af; color: white; padding: 10px 18px; border-radius: 8px; text-decoration: none; font-weight: 600; display: inline-flex; align-items: center; gap: 8px; border: none; cursor: pointer; font-size: 14px; transition: 0.2s; }}
            .btn:hover {{ background: #1d4ed8; transform: translateY(-1px); }}
            .btn-outline {{ background: white; color: #1e40af; border: 1.5px solid #bfdbfe; }}
            .btn-outline:hover {{ background: #eff6ff; }}
            .table-box {{ background: white; padding: 24px; border-radius: 12px; box-shadow: 0 1px 3px rgba(0,0,0,0.05); margin-bottom: 24px; overflow-x: auto; }}
            table {{ width: 100%; border-collapse: collapse; text-align: left; }}
            th {{ background: #f1f5f9; padding: 12px; font-size: 13px; color: #475569; }}
            .broadcast-box {{ background: #eff6ff; border: 1.5px solid #bfdbfe; padding: 24px; border-radius: 12px; margin-bottom: 24px; }}
            textarea, select, input[type="text"] {{ width: 100%; padding: 11px; border-radius: 8px; border: 1px solid #cbd5e1; margin-top: 6px; margin-bottom: 14px; box-sizing: border-box; font-family: inherit; font-size: 14px; }}
            .pill-btn {{ background: white; border: 1px solid #cbd5e1; padding: 6px 12px; border-radius: 20px; font-size: 12px; cursor: pointer; margin-right: 6px; margin-bottom: 8px; font-weight: 500; }}
            .pill-btn:hover {{ background: #dbeafe; border-color: #93c5fd; color: #1e40af; }}
            .status-badge {{ padding: 3px 8px; border-radius: 12px; font-size: 11px; font-weight: 600; text-transform: uppercase; }}
            .status-pending {{ background: #fef3c7; color: #b45309; }}
            .status-sent {{ background: #dcfce7; color: #15803d; }}
            .status-failed {{ background: #fee2e2; color: #b91c1c; }}
            .progress-bar-bg {{ background: #e2e8f0; border-radius: 8px; height: 10px; width: 100%; overflow: hidden; margin-top: 10px; }}
            .progress-bar-fill {{ background: #22c55e; height: 100%; width: 0%; transition: width 0.4s ease; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <div>
                    <h1 style="margin:0 0 4px 0; font-size:22px;">🎓 Radhaballav Higher Secondary School</h1>
                    <p style="margin:0; color:#64748b; font-size:14px;">WhatsApp Exam Bot Admin & Student Engagement Control Center</p>
                </div>
                <div style="display:flex; align-items:center; gap:10px;">
                    <div id="wa-status-pill" style="background:#f1f5f9; color:#475569; border:1px solid #cbd5e1; padding:8px 14px; border-radius:20px; font-size:13px; font-weight:600; display:flex; align-items:center; gap:8px;">
                        <span id="wa-dot" style="height:9px; width:9px; background:#94a3b8; border-radius:50%; display:inline-block;"></span>
                        <span id="wa-status-text">Cloud WhatsApp: Checking...</span>
                    </div>
                    <a href="/admin/export-users" class="btn">📥 Export Student Numbers (.csv)</a>
                </div>
            </div>

            <!-- Student Metrics Cards -->
            <div class="grid">
                <div class="card">
                    <h3>Verified WhatsApp Users</h3>
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

            <!-- Broadcast Section -->
            <div class="broadcast-box">
                <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; margin-bottom:12px;">
                    <div>
                        <h2 style="margin:0; font-size:19px; color:#1e40af;">📢 Send WhatsApp Broadcast to Students</h2>
                        <p style="color:#475569; font-size:13px; margin:4px 0 0 0;">Yahan se verified students ko new WhatsApp Group link, exam notices ya marksheet alerts bhein.</p>
                    </div>
                    <div id="liveQueueBadge" style="background:white; border:1px solid #bfdbfe; padding:8px 14px; border-radius:8px; font-size:13px; font-weight:600;">
                        ⏳ Pending in Queue: <span id="queuePendingCount" style="color:#d97706;">{b_pending}</span> | ✅ Sent: <span id="queueSentCount" style="color:#15803d;">{b_sent}</span>
                    </div>
                </div>

                <div class="progress-bar-bg">
                    <div id="broadcastProgress" class="progress-bar-fill"></div>
                </div>

                <div style="margin-top:16px;">
                    <span style="font-size:13px; font-weight:600; color:#475569;">Quick Template chunein:</span><br>
                    <button type="button" class="pill-btn" onclick="applyTemplate('group')">📋 WhatsApp Group Invite</button>
                    <button type="button" class="pill-btn" onclick="applyTemplate('exam')">🗓️ Next Exam Notice</button>
                    <button type="button" class="pill-btn" onclick="applyTemplate('result')">📊 Practical / Results Alert</button>
                </div>

                <div style="display:grid; grid-template-columns: 1fr 1fr; gap:14px; margin-top:10px;">
                    <div>
                        <label><b>Target Students Stream:</b></label>
                        <select id="targetStream">
                            <option value="All">All Verified Students ({total_users})</option>
                            <option value="Science">Science Only ({sci_users})</option>
                            <option value="Commerce">Commerce Only ({com_users})</option>
                            <option value="Arts">Arts Only ({arts_users})</option>
                        </select>
                    </div>
                    <div>
                        <label><b>Test on Single Phone Number (Optional):</b></label>
                        <input type="text" id="testPhone" placeholder="Jaise: +919437280970 (Testing ke liye)" />
                    </div>
                </div>

                <label><b>WhatsApp Message Body:</b></label>
                <textarea id="msgBody" rows="5">🎓 *RADHABALLAV HIGHER SECONDARY SCHOOL*
Namaskar students! Aapke Half Yearly Exams safal rahe.
College ke official class notes aur practical routines ke liye hamara naya WhatsApp Group join karein:
👉 Link: https://chat.whatsapp.com/YourGroupLinkHere</textarea>

                <div style="display:flex; gap:12px; align-items:center; flex-wrap:wrap;">
                    <button type="button" id="sendBtn" class="btn" onclick="triggerBroadcast(false)">
                        🚀 Send Broadcast to Students
                    </button>
                    <button type="button" id="testBtn" class="btn btn-outline" onclick="triggerBroadcast(true)">
                        🧪 Test Send on My Number
                    </button>
                    <span id="broadcastStatusMsg" style="font-size:14px; font-weight:600;"></span>
                </div>

                <!-- Recent Broadcast Queue Items -->
                <div style="margin-top:20px; background:white; border-radius:8px; padding:14px; border:1px solid #e2e8f0;">
                    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
                        <h4 style="margin:0; font-size:14px; color:#334155;">📬 Recent Queue Activity</h4>
                        <button type="button" onclick="refreshQueueStatus()" style="background:none; border:none; color:#2563eb; cursor:pointer; font-size:12px; font-weight:600;">🔄 Refresh Status</button>
                    </div>
                    <div id="queueTableContainer" style="font-size:13px; color:#64748b;">
                        Queue status load ho raha hai...
                    </div>
                </div>
            </div>

            <!-- Verified Students Table -->
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

        <script>
            function applyTemplate(type) {{
                const msgBox = document.getElementById('msgBody');
                if (type === 'group') {{
                    msgBox.value = "🎓 *RADHABALLAV HIGHER SECONDARY SCHOOL*\nNamaskar students! Aapke Half Yearly Exams safal rahe.\nCollege ke official class notes aur practical routines ke liye hamara naya WhatsApp Group join karein:\n👉 Group Link: https://chat.whatsapp.com/YourGroupLinkHere";
                }} else if (type === 'exam') {{
                    msgBox.value = "📢 *RBHS COLLEGE IMPORTANT NOTICE*\nKal ke exam ke liye sabhi students samay par pahuchein.\nSitting Time aur Allotted Hall dekhne ke liye bot par apna Roll Number type karke bhejein.\nAll the best! 👍";
                }} else if (type === 'result') {{
                    msgBox.value = "📊 *RBHS EXAM UPDATE*\nHalf Yearly Exam ke marks aur practical routine college notice board par display ho gaye hain.\nKisi bhi sahayata ke liye administrative office se sampark karein.";
                }}
            }}

            async function triggerBroadcast(isTest) {{
                const msg = document.getElementById('msgBody').value.trim();
                const target = document.getElementById('targetStream').value;
                const testPhone = document.getElementById('testPhone').value.trim();
                const statusSpan = document.getElementById('broadcastStatusMsg');
                const sendBtn = document.getElementById('sendBtn');
                const testBtn = document.getElementById('testBtn');

                if (!msg) {{
                    alert('Message body khali nahi ho sakta!');
                    return;
                }}

                if (isTest && !testPhone) {{
                    alert('Kripya "Test on Single Phone Number" box me apna mobile number dalein (+91...)!');
                    return;
                }}

                if (!isTest) {{
                    const confirmSend = confirm(`Kya aap sach me stream "${{target}}" ke sabhi students ko yeh WhatsApp message bhejna chahte hain?`);
                    if (!confirmSend) return;
                }}

                sendBtn.disabled = true;
                testBtn.disabled = true;
                statusSpan.style.color = '#2563eb';
                statusSpan.innerText = '⏳ Queueing messages...';

                try {{
                    const payload = {{
                        target: target,
                        message: msg,
                        test_phone: isTest ? testPhone : ''
                    }};

                    const res = await fetch('/admin/send-broadcast', {{
                        method: 'POST',
                        headers: {{ 'Content-Type': 'application/json' }},
                        body: JSON.stringify(payload)
                    }});

                    const data = await res.json();
                    if (data.success) {{
                        statusSpan.style.color = '#16a34a';
                        statusSpan.innerText = data.message;
                        refreshQueueStatus();
                    }} else {{
                        statusSpan.style.color = '#dc2626';
                        statusSpan.innerText = '❌ Error: ' + (data.error || 'Failed to queue');
                    }}
                }} catch (err) {{
                    statusSpan.style.color = '#dc2626';
                    statusSpan.innerText = '❌ Server connection failed: ' + err.message;
                }} finally {{
                    sendBtn.disabled = false;
                    testBtn.disabled = false;
                }}
            }}

            async function refreshQueueStatus() {{
                try {{
                    const res = await fetch('/admin/broadcast-status');
                    const data = await res.json();

                    document.getElementById('queuePendingCount').innerText = data.pending;
                    document.getElementById('queueSentCount').innerText = data.sent;

                    const total = data.total || 0;
                    const sent = data.sent || 0;
                    const pct = total > 0 ? Math.round((sent / total) * 100) : 0;
                    document.getElementById('broadcastProgress').style.width = pct + '%';

                    const container = document.getElementById('queueTableContainer');
                    if (!data.recent || data.recent.length === 0) {{
                        container.innerHTML = '<i>Abhi koi broadcast queue me nahi hai.</i>';
                        return;
                    }}

                    let tHtml = '<table style="width:100%; border-collapse:collapse;"><thead><tr style="text-align:left; border-bottom:1px solid #e2e8f0;"><th style="padding:6px;">Mobile</th><th style="padding:6px;">Name</th><th style="padding:6px;">Status</th><th style="padding:6px;">Sent Time</th></tr></thead><tbody>';
                    for (const item of data.recent) {{
                        const badgeClass = item.status === 'SENT' ? 'status-sent' : (item.status === 'FAILED' ? 'status-failed' : 'status-pending');
                        const sTime = item.sent_at ? String(item.sent_at).slice(0, 19) : (item.created_at ? String(item.created_at).slice(0, 19) : 'Pending');
                        tHtml += `
                        <tr style="border-bottom:1px solid #f1f5f9;">
                            <td style="padding:6px; font-family:monospace; font-weight:bold;">${{item.phone}}</td>
                            <td style="padding:6px;">${{item.name || 'Student'}}</td>
                            <td style="padding:6px;"><span class="status-badge ${{badgeClass}}">${{item.status}}</span></td>
                            <td style="padding:6px; color:#64748b; font-size:12px;">${{sTime}}</td>
                        </tr>
                        `;
                    }}
                    tHtml += '</tbody></table>';
                    container.innerHTML = tHtml;
                }} catch (e) {{
                    console.error('Queue poll error:', e);
                }}
            }}

            // Poll queue status every 4 seconds
            refreshQueueStatus();
            setInterval(refreshQueueStatus, 4000);

            // Poll Cloud WhatsApp status every 5 seconds
            async function checkWaStatus() {{
                try {{
                    const r = await fetch('/admin/whatsapp-status');
                    const d = await r.json();
                    const pill = document.getElementById('wa-status-pill');
                    const dot = document.getElementById('wa-dot');
                    const text = document.getElementById('wa-status-text');
                    if (d.isConnected) {{
                        pill.style.background = '#dcfce7';
                        pill.style.color = '#15803d';
                        pill.style.borderColor = '#86efac';
                        dot.style.background = '#22c55e';
                        dot.style.boxShadow = '0 0 6px #22c55e';
                        text.innerText = '🟢 Cloud WhatsApp: Connected (' + (d.connectedUser || 'Active') + ')';
                    }} else if (d.hasQR) {{
                        pill.style.background = '#fef3c7';
                        pill.style.color = '#b45309';
                        pill.style.borderColor = '#fcd34d';
                        dot.style.background = '#f59e0b';
                        dot.style.boxShadow = 'none';
                        text.innerText = '🟡 WhatsApp: QR Scan Needed';
                    }} else {{
                        pill.style.background = '#fee2e2';
                        pill.style.color = '#b91c1c';
                        pill.style.borderColor = '#fca5a5';
                        dot.style.background = '#ef4444';
                        dot.style.boxShadow = 'none';
                        text.innerText = '🔴 WhatsApp Cloud Bridge: Connecting...';
                    }}
                }} catch (e) {{}}
            }}
            checkWaStatus();
            setInterval(checkWaStatus, 5000);
        </script>
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
