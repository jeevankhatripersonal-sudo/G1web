// api/admin.js
// Password-protected page listing every form submission.
//   /api/admin             -> table view (newest first)
//   /api/admin?format=csv  -> download everything as a CSV (opens in Excel)
// Log in with any username and the ADMIN_PASSWORD you set in Vercel.

import { list, get } from '@vercel/blob';
import { timingSafeEqual, createHash } from 'node:crypto';

const NO_CACHE = { 'Cache-Control': 'private, no-store', 'X-Robots-Tag': 'noindex' };

function authorized(request) {
  const expected = process.env.ADMIN_PASSWORD;
  if (!expected) return false;
  const header = request.headers.get('authorization') || '';
  if (!header.startsWith('Basic ')) return false;
  const decoded = Buffer.from(header.slice(6), 'base64').toString();
  const password = decoded.slice(decoded.indexOf(':') + 1);
  const a = createHash('sha256').update(password).digest();
  const b = createHash('sha256').update(expected).digest();
  return timingSafeEqual(a, b);
}

async function loadAll() {
  const blobs = [];
  let cursor;
  do {
    const page = await list({ prefix: 'submissions/', cursor, limit: 1000 });
    blobs.push(...page.blobs);
    cursor = page.hasMore ? page.cursor : undefined;
  } while (cursor);

  const records = await Promise.all(
    blobs.map(async b => {
      try {
        const res = await get(b.pathname, { access: 'private' });
        if (res?.statusCode !== 200) return null;
        return await new Response(res.stream).json();
      } catch {
        return null;
      }
    })
  );
  return records.filter(Boolean).sort((x, y) => (x.receivedAt < y.receivedAt ? 1 : -1));
}

const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const csvCell = s => `"${String(s ?? '').replace(/"/g, '""')}"`;

export default async function handler(request) {
  if (!process.env.ADMIN_PASSWORD) {
    return new Response('Set ADMIN_PASSWORD in Vercel > Settings > Environment Variables, then redeploy.', { status: 500, headers: NO_CACHE });
  }
  if (!authorized(request)) {
    return new Response('Login required', {
      status: 401,
      headers: { ...NO_CACHE, 'WWW-Authenticate': 'Basic realm="Inquiries", charset="UTF-8"' },
    });
  }

  const records = await loadAll();
  const format = new URL(request.url).searchParams.get('format');

  if (format === 'csv') {
    const rows = [['Received', 'Name', 'Email', 'Service', 'Message']].concat(
      records.map(r => [r.receivedAt, r.name, r.email, r.service, r.message])
    );
    const csv = '\uFEFF' + rows.map(row => row.map(csvCell).join(',')).join('\r\n');
    return new Response(csv, {
      headers: {
        ...NO_CACHE,
        'Content-Type': 'text/csv; charset=utf-8',
        'Content-Disposition': `attachment; filename="inquiries-${new Date().toISOString().slice(0, 10)}.csv"`,
      },
    });
  }

  const fmt = iso => new Date(iso).toLocaleString('en-IN', { timeZone: 'Asia/Kolkata', dateStyle: 'medium', timeStyle: 'short' });
  const rows = records.map(r => `
    <tr>
      <td class="nowrap">${esc(fmt(r.receivedAt))}</td>
      <td>${esc(r.name)}</td>
      <td><a href="mailto:${esc(r.email)}?subject=${encodeURIComponent('Re: ' + r.service)}">${esc(r.email)}</a></td>
      <td>${esc(r.service)}</td>
      <td class="msg">${esc(r.message)}</td>
    </tr>`).join('');

  const page = `<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>Inquiries (${records.length})</title>
<style>
  body { margin:0; padding:24px; background:#0D0C0A; color:#E6DDD0; font:14px/1.5 system-ui, sans-serif; }
  h1 { margin:0 0 4px; font-size:22px; color:#F4EFE8; font-weight:500; }
  .bar { display:flex; gap:12px; align-items:center; flex-wrap:wrap; margin-bottom:20px; color:#8A8078; }
  a { color:#C2AA8A; }
  .btn { padding:8px 14px; border:1px solid #B6903E; border-radius:4px; text-decoration:none; color:#B6903E; }
  .wrap { overflow-x:auto; border:1px solid #252220; border-radius:8px; }
  table { border-collapse:collapse; width:100%; min-width:760px; }
  th, td { text-align:left; vertical-align:top; padding:10px 12px; border-bottom:1px solid #252220; }
  th { background:#161412; color:#B6903E; font-weight:500; font-size:12px; letter-spacing:.08em; text-transform:uppercase; position:sticky; top:0; }
  tr:hover td { background:#161412; }
  .nowrap { white-space:nowrap; color:#8A8078; }
  .msg { white-space:pre-wrap; max-width:480px; }
  .empty { padding:40px; text-align:center; color:#8A8078; }
</style></head><body>
  <h1>Inquiries</h1>
  <div class="bar"><span>${records.length} total, newest first</span>
    <a class="btn" href="?format=csv">Download CSV</a>
    <a class="btn" href="">Refresh</a></div>
  <div class="wrap">${records.length ? `<table>
    <thead><tr><th>Received</th><th>Name</th><th>Email</th><th>Service</th><th>Message</th></tr></thead>
    <tbody>${rows}</tbody></table>` : '<div class="empty">No inquiries yet.</div>'}</div>
</body></html>`;

  return new Response(page, { headers: { ...NO_CACHE, 'Content-Type': 'text/html; charset=utf-8' } });
}
