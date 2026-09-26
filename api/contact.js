// api/contact.js
// Receives the contact form, stores it privately in Vercel Blob,
// then sends you a notification (Telegram and/or email).

import { put } from '@vercel/blob';
import { randomUUID } from 'node:crypto';

const LIMITS = { name: 100, email: 200, service: 100, message: 5000 };
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

const json = (status, body) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' },
  });

export default async function handler(request) {
  if (request.method !== 'POST') return json(405, { error: 'Method not allowed' });

  let body;
  try {
    body = await request.json();
  } catch {
    return json(400, { error: 'Invalid request' });
  }

  // Honeypot: real visitors never fill this hidden field, bots usually do.
  if (body.website) return json(200, { ok: true });

  const clean = (v, max) => String(v ?? '').trim().slice(0, max);
  const entry = {
    name: clean(body.name, LIMITS.name),
    email: clean(body.email, LIMITS.email),
    service: clean(body.service, LIMITS.service),
    message: clean(body.message, LIMITS.message),
  };

  if (!entry.name || !entry.service || !EMAIL_RE.test(entry.email)) {
    return json(400, { error: 'Please fill in your name, a valid email, and a service.' });
  }

  const now = new Date();
  const id = `${now.toISOString().replace(/[:.]/g, '-')}-${randomUUID().slice(0, 8)}`;
  const record = { id, receivedAt: now.toISOString(), ...entry };

  try {
    await put(`submissions/${id}.json`, JSON.stringify(record, null, 2), {
      access: 'private',
      contentType: 'application/json',
    });
  } catch (err) {
    console.error('Blob save failed:', err);
    return json(500, { error: 'Could not save your message. Please try again.' });
  }

  // Notifications never block or break the submission.
  await Promise.allSettled([notifyTelegram(record, request), notifyEmail(record, request)]);

  return json(200, { ok: true });
}

function adminUrl(request) {
  return `${new URL(request.url).origin}/api/admin`;
}

async function notifyTelegram(r, request) {
  const token = process.env.TELEGRAM_BOT_TOKEN;
  const chatId = process.env.TELEGRAM_CHAT_ID;
  if (!token || !chatId) return;

  const text =
    `New inquiry: ${r.service}\n\n` +
    `Name: ${r.name}\nEmail: ${r.email}\n\n` +
    `${r.message ? r.message.slice(0, 1500) : '(no message)'}\n\n` +
    `All inquiries: ${adminUrl(request)}`;

  const res = await fetch(`https://api.telegram.org/bot${token}/sendMessage`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ chat_id: chatId, text, disable_web_page_preview: true }),
    signal: AbortSignal.timeout(5000),
  });
  if (!res.ok) console.error('Telegram failed:', res.status, await res.text());
}

async function notifyEmail(r, request) {
  const key = process.env.RESEND_API_KEY;
  const to = process.env.NOTIFY_EMAIL;
  if (!key || !to) return;

  const esc = s => String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  const res = await fetch('https://api.resend.com/emails', {
    method: 'POST',
    headers: { Authorization: `Bearer ${key}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({
      from: process.env.NOTIFY_FROM || 'Website <onboarding@resend.dev>',
      to: [to],
      reply_to: r.email,
      subject: `New inquiry: ${r.service} from ${r.name}`,
      html:
        `<p><b>Name:</b> ${esc(r.name)}<br><b>Email:</b> ${esc(r.email)}<br><b>Service:</b> ${esc(r.service)}</p>` +
        `<p style="white-space:pre-wrap">${esc(r.message || '(no message)')}</p>` +
        `<p><a href="${adminUrl(request)}">See all inquiries</a></p>`,
    }),
    signal: AbortSignal.timeout(5000),
  });
  if (!res.ok) console.error('Email failed:', res.status, await res.text());
}
