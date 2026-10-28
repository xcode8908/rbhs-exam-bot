const { default: makeWASocket, useMultiFileAuthState, DisconnectReason, fetchLatestBaileysVersion } = require('@whiskeysockets/baileys');
const express = require('express');
const QRCode = require('qrcode');
const axios = require('axios');
const path = require('path');
const fs = require('fs');

const app = express();
const INTERNAL_PORT = 5050;

const NEON_URL = process.env.NEON_URL || "https://ep-patient-dream-b30yv2xq-pooler.c-4.ap-southeast-1.aws.neon.tech/sql";
const NEON_CONN = process.env.DATABASE_URL || "postgresql://neondb_owner:npg_DTfk4PM9dewh@ep-patient-dream-b30yv2xq-pooler.c-4.ap-southeast-1.aws.neon.tech/neondb?sslmode=require";

let currentQR = null;
let isConnected = false;
let connectedUser = null;
let qrDataUrl = null;
let saveDebounceTimer = null;

const authDir = path.join(__dirname, 'auth_session');
if (!fs.existsSync(authDir)) fs.mkdirSync(authDir, { recursive: true });

// Function: Restore Auth Session from Neon Cloud Database
async function restoreSessionFromNeon() {
    try {
        console.log('[NEON SYNC] Checking Neon database for saved WhatsApp session...');
        const res = await axios.post(NEON_URL, {
            query: "SELECT data FROM whatsapp_session WHERE id = 'auth_bundle' LIMIT 1;"
        }, {
            headers: { 'Neon-Connection-String': NEON_CONN, 'Content-Type': 'application/json' },
            timeout: 15000
        });

        const row = res.data?.rows?.[0];
        const bundleStr = Array.isArray(row) ? row[0] : row?.data;
        if (bundleStr) {
            const bundle = JSON.parse(bundleStr);
            const keys = Object.keys(bundle);
            for (const f of keys) {
                fs.writeFileSync(path.join(authDir, f), bundle[f], 'utf-8');
            }
            console.log(`[NEON SYNC] Successfully restored ${keys.length} session files from Neon cloud!`);
        } else {
            console.log('[NEON SYNC] No session bundle in Neon, using local session files.');
        }
    } catch (err) {
        console.warn('[NEON SYNC] Warning: Could not restore from Neon (using local files):', err.message);
    }
}

// Function: Backup Auth Session to Neon Cloud Database
async function backupSessionToNeon() {
    try {
        if (!fs.existsSync(authDir)) return;
        const files = fs.readdirSync(authDir);
        if (!files.includes('creds.json')) return;

        const bundle = {};
        for (const fname of files) {
            const fpath = path.join(authDir, fname);
            if (fs.statSync(fpath).isFile()) {
                bundle[fname] = fs.readFileSync(fpath, 'utf-8');
            }
        }

        const bundleJson = JSON.stringify(bundle);
        const escaped = bundleJson.replace(/'/g, "''");
        const sql = `
            INSERT INTO whatsapp_session (id, data, updated_at) 
            VALUES ('auth_bundle', '${escaped}', CURRENT_TIMESTAMP)
            ON CONFLICT(id) DO UPDATE SET data = EXCLUDED.data, updated_at = CURRENT_TIMESTAMP;
        `;

        await axios.post(NEON_URL, { query: sql }, {
            headers: { 'Neon-Connection-String': NEON_CONN, 'Content-Type': 'application/json' },
            timeout: 25000
        });
        console.log(`[NEON SYNC] Successfully backed up ${files.length} session files to Neon cloud!`);
    } catch (err) {
        console.warn('[NEON SYNC] Backup to Neon error:', err.message);
    }
}

function triggerNeonBackup() {
    if (saveDebounceTimer) clearTimeout(saveDebounceTimer);
    saveDebounceTimer = setTimeout(backupSessionToNeon, 15000);
}

// Internal status and QR endpoints
app.use(express.json());

app.get('/status', (req, res) => {
    res.json({
        isConnected,
        connectedUser,
        hasQR: Boolean(currentQR)
    });
});

app.get('/qr', (req, res) => {
    res.json({
        qr: currentQR,
        qrDataUrl
    });
});

async function startWhatsAppBot() {
    const credsPath = path.join(authDir, 'creds.json');
    if (!fs.existsSync(credsPath)) {
        await restoreSessionFromNeon();
    }

    const { state, saveCreds } = await useMultiFileAuthState(authDir);
    const { version } = await fetchLatestBaileysVersion();

    console.log(`Starting Baileys WhatsApp client (v${version.join('.')})...`);

    const sock = makeWASocket({
        version,
        auth: state,
        printQRInTerminal: false,
        browser: ['RBHS Exam Bot (Render Cloud)', 'Chrome', '1.0.0']
    });

    sock.ev.on('creds.update', async () => {
        await saveCreds();
        triggerNeonBackup();
    });

    sock.ev.on('connection.update', async (update) => {
        const { connection, lastDisconnect, qr } = update;

        if (qr) {
            currentQR = qr;
            qrDataUrl = await QRCode.toDataURL(qr);
            console.log('[QR GENERATED] New QR code generated.');
        }

        if (connection === 'close') {
            const statusCode = lastDisconnect?.error?.output?.statusCode;
            const shouldReconnect = statusCode !== DisconnectReason.loggedOut;
            console.log(`[WA CLOSED] Status code: ${statusCode}, Reconnecting: ${shouldReconnect}`);
            isConnected = false;
            if (shouldReconnect) {
                setTimeout(startWhatsAppBot, 5000);
            }
        } else if (connection === 'open') {
            console.log('=======================================================');
            console.log('✅ WhatsApp successfully connected on Render Cloud!');
            console.log(`📱 User: ${sock.user?.id?.split(':')[0] || 'Active'}`);
            console.log('=======================================================');
            isConnected = true;
            connectedUser = sock.user?.id?.split(':')[0] || 'Connected';
            currentQR = null;
            qrDataUrl = null;
            triggerNeonBackup();
        }
    });

    // Helper to get local or remote webhook URL
    function getWebhookUrl() {
        if (process.env.RENDER_WEBHOOK_URL) return process.env.RENDER_WEBHOOK_URL;
        const mainPort = process.env.PORT;
        if (mainPort) return `http://127.0.0.1:${mainPort}/webhook`;
        return 'https://rbhs-exam-bot.onrender.com/webhook';
    }

    function getApiBase() {
        const wh = getWebhookUrl();
        return wh.replace('/webhook', '');
    }

    // Handle Incoming Messages
    sock.ev.on('messages.upsert', async (m) => {
        const msg = m.messages[0];
        if (!msg || !msg.message || msg.key.fromMe) return;

        const senderJid = msg.key.remoteJid;
        if (senderJid.endsWith('@g.us')) return; // Ignore group chats

        let senderPhone = senderJid.split('@')[0];
        if (!senderPhone.startsWith('+')) senderPhone = '+' + senderPhone;

        const text = msg.message.conversation || msg.message.extendedTextMessage?.text || '';
        console.log(`[INCOMING] From: ${senderPhone} | Message: "${text}"`);

        try {
            const webhookUrl = getWebhookUrl();
            const response = await axios.post(webhookUrl, {
                message: text,
                phone: senderPhone
            }, { timeout: 12000 });

            if (response.data && response.data.reply) {
                const replyText = response.data.reply;
                await sock.sendMessage(senderJid, { text: replyText });
                console.log(`[REPLIED] Sent reply to ${senderPhone}`);
            }
        } catch (err) {
            console.error('[WEBHOOK ERROR] Could not forward message:', err.message);
        }
    });

    // Background Broadcast Queue Worker
    let isBroadcasting = false;
    setInterval(async () => {
        if (!isConnected || isBroadcasting) return;

        try {
            const apiBase = getApiBase();
            const res = await axios.get(`${apiBase}/api/pending-broadcasts`, { timeout: 8000 });
            const pending = res.data?.messages || [];

            if (pending.length > 0) {
                isBroadcasting = true;
                for (const item of pending) {
                    let rawPhone = String(item.phone || '').trim();
                    let jid = rawPhone.includes('@') ? rawPhone : `${rawPhone.replace(/[^0-9]/g, '')}@s.whatsapp.net`;

                    console.log(`[BROADCAST QUEUE] Sending to: ${rawPhone}...`);
                    try {
                        await sock.sendMessage(jid, { text: item.message });
                        console.log(`✅ [BROADCAST SENT] Delivered to: ${rawPhone}`);
                        await axios.post(`${apiBase}/api/mark-broadcast-sent`, { id: item.id, status: 'SENT' }, { timeout: 8000 });
                    } catch (sendErr) {
                        console.error(`❌ [BROADCAST FAILED] Error for ${rawPhone}:`, sendErr.message);
                        await axios.post(`${apiBase}/api/mark-broadcast-sent`, { id: item.id, status: 'FAILED' }, { timeout: 8000 });
                    }
                    await new Promise(r => setTimeout(r, 2500));
                }
                isBroadcasting = false;
            }
        } catch (pollErr) {
            isBroadcasting = false;
        }
    }, 4000);
}

app.listen(INTERNAL_PORT, () => {
    console.log(`WhatsApp Internal Health Server running on port ${INTERNAL_PORT}`);
    startWhatsAppBot();
});
