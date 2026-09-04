#!/usr/bin/env python3
# GENERATED FILE — do not edit. Built by build_single_file.py from render_digest.py
# + digest_template.html; edit those and rebuild, or your change will be overwritten.
"""
render_digest — turn the triage run's JSON payload into the digest email's HTML.

    python3 render_digest.py payload.json > digest.html
    python3 render_digest.py -                 # payload on stdin
    python3 render_digest.py payload.json --body-only

Standard library only, no install step, same shipping model as `email_extract`:
`dist/render_digest.py` is a generated single file with the template baked in, so the
routine can fetch one file and run it on stock CPython.

Why a renderer instead of letting the model author the markup: the design in
`digest_template.html` was reviewed and approved once, and every value substituted into
it comes from an email subject or sender name — i.e. from an attacker. A model
hand-writing HTML re-litigates the design every run and has no escaping guarantee. This
module gives both: the markup is fixed, and every interpolation goes through
`html.escape(..., quote=True)` with URLs additionally restricted to http/https.

Template syntax (a deliberately small Mustache-shaped subset, see `_parse`):

    {{ name }}              escaped text
    {{@ name }}             URL attribute value — http(s) only, otherwise "#"
    {{# name }} … {{/ name }}   list -> repeat per item; truthy -> once; falsy -> omit
    {{^ name }} … {{/ name }}   the inverse (render only when falsy/absent)
    {{ . }}                 the current item, for lists of plain strings

Inside a list section each item also gets `_first`, `_last`, `_index`, `_count`, which
is what drives the mockup's "last card has a bigger bottom margin" and "every row but
the last has a bottom border" details without putting markup in Python.

A section tag alone on a line consumes that whole line, so omitted sections leave no
blank lines or stray separators behind.
"""

from __future__ import annotations

import argparse
import html
import json
import pathlib
import re
import sys
import zlib

# Replaced by build_single_file.py when generating dist/render_digest.py. Left as None
# in the source tree so the package path reads digest_template.html — the editable
# source of truth — and the two paths can be diffed for staleness.
# The approved digest design, baked in at build time.
EMBEDDED_TEMPLATE = r'''<title>Inbox Triage Digest</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Manrope:wght@600;700;800&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@500;600&display=swap">
<style>
  :root{
    --ink:#171a24; --ink-soft:#4a5170; --ink-faint:#8791ab;
    --paper:#f2f4fa; --surface:#ffffff; --border:#e2e5f0;
    --brand:#2451b8; --brand-soft:#eaf0fe; --brand-line:#c9d9fb;
    --green:#1e9e74; --green-soft:#e4f7ef; --green-line:#bfead9;
    --purple:#7b5cc9; --purple-soft:#f1ecfc; --purple-line:#ded2f5;
    --amber:#b9790e; --amber-soft:#fcf1dd; --amber-line:#f2dcae;
    --red:#c8463d; --red-soft:#fbeae8;
  }
  @media (prefers-color-scheme: dark){
    :root:not([data-theme="light"]){
      --ink:#eef0f7; --ink-soft:#aab2cc; --ink-faint:#6d7590;
      --paper:#0d1018; --surface:#161a26; --border:#262b3c;
      --brand-soft:#182444; --brand-line:#28418c;
      --green-soft:#0f2b23; --green-line:#1c5943;
      --purple-soft:#241c3d; --purple-line:#4a3b7a;
      --amber-soft:#2e2312; --amber-line:#6b4f16;
      --red-soft:#331b19;
    }
  }
  :root[data-theme="dark"]{
    --ink:#eef0f7; --ink-soft:#aab2cc; --ink-faint:#6d7590;
    --paper:#0d1018; --surface:#161a26; --border:#262b3c;
    --brand-soft:#182444; --brand-line:#28418c;
    --green-soft:#0f2b23; --green-line:#1c5943;
    --purple-soft:#241c3d; --purple-line:#4a3b7a;
    --amber-soft:#2e2312; --amber-line:#6b4f16;
    --red-soft:#331b19;
  }
  *{box-sizing:border-box;}
  body{
    margin:0; background:var(--paper); color:var(--ink);
    font-family:'IBM Plex Sans',-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;
    padding:40px 16px 80px;
  }
  .shell{max-width:700px; margin:0 auto;}
  .intro{margin:0 4px 28px;}
  .intro h1{
    font-family:'Manrope',-apple-system,sans-serif; font-weight:800; font-size:22px;
    letter-spacing:-0.01em; margin:0 0 6px;
  }
  .intro p{margin:0; color:var(--ink-soft); font-size:14px; line-height:1.6; max-width:60ch;}
  .subject-line{
    display:flex; gap:10px; align-items:baseline; margin-top:14px;
    font-family:'IBM Plex Mono',ui-monospace,Menlo,Consolas,monospace;
    font-size:12.5px; color:var(--ink-soft); background:var(--surface);
    border:1px solid var(--border); border-radius:8px; padding:10px 14px;
  }
  .subject-line b{color:var(--ink); font-weight:600; font-family:'IBM Plex Sans',sans-serif;}
  .frame{
    background:var(--surface); border:1px solid var(--border); border-radius:16px;
    overflow:hidden; box-shadow:0 1px 2px rgba(23,26,36,0.04), 0 12px 32px -20px rgba(23,26,36,0.35);
  }
  .frame-bar{
    display:flex; align-items:center; gap:8px; padding:10px 16px;
    border-bottom:1px solid var(--border); color:var(--ink-faint);
    font-family:'IBM Plex Mono',ui-monospace,monospace; font-size:11px;
  }
  .frame-dot{width:8px; height:8px; border-radius:50%; background:var(--border);}
  .caption{
    text-align:center; margin-top:16px; color:var(--ink-faint); font-size:12px;
    font-family:'IBM Plex Mono',ui-monospace,monospace; letter-spacing:.02em;
  }
</style>

<div class="shell">
  <div class="intro">
    <h1>Inbox Triage — Email Template</h1>
    <p>Production markup below (inline-styled, table-based) — this is the literal HTML the digest sends. It reads as a document with headed sections: each one is an icon, an uppercase title and a count over a rule, with its cards indented underneath, so the structure survives with the color taken out. Fills are <code>background-color</code> and <code>bgcolor</code> only, and every icon is a Unicode glyph, because the Gmail send path drops the <code>background</code> shorthand and deletes <code>&lt;img&gt;</code> outright — remote or attached, it makes no difference.</p>
    <div class="subject-line">Subject: <b>{{subject}}</b></div>
  </div>

  <div class="frame">
    <div class="frame-bar"><span class="frame-dot"></span><span class="frame-dot"></span><span class="frame-dot"></span>&nbsp; to: fisher@fisherevans.com</div>

<!-- ======================= EMAIL BODY (portable / inline-styled) ======================= -->
<div style="background-color:#eef1f8;padding:28px 16px;font-family:-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
<div style="max-width:600px;margin:0 auto;background-color:#ffffff;border-radius:14px;overflow:hidden;border:1px solid #e2e5f0;">

  <!-- Masthead -->
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" bgcolor="#1c3f96" style="background-color:#1c3f96;">
    <tr>
      <td bgcolor="#1c3f96" style="background-color:#1c3f96;padding:24px 26px 22px;">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>
          <td width="32" valign="top" style="padding:2px 12px 0 0;">
            <span style="font-size:17px;line-height:20px;">✉️</span>
          </td>
          <td valign="middle">
            <div style="font-family:'Manrope',-apple-system,sans-serif;font-weight:800;font-size:19px;color:#ffffff;letter-spacing:-0.01em;">Inbox triage</div>
            <div style="font-family:'IBM Plex Mono',ui-monospace,Menlo,Consolas,monospace;font-size:12px;color:#c7d6f7;margin-top:3px;">{{date_label}}</div>
          </td>
          <td align="right" valign="middle">
{{#completed_at}}
            <table role="presentation" cellpadding="0" cellspacing="0" align="right"><tr>
              <td bgcolor="#33589f" style="background-color:#33589f;border-radius:20px;padding:7px 13px;font-family:'IBM Plex Mono',ui-monospace,monospace;font-size:11px;color:#e8edfb;white-space:nowrap;">Completed {{completed_at}}</td>
            </tr></table>
{{/completed_at}}
          </td>
        </tr></table>
      </td>
    </tr>
  </table>

  <!-- KPI strip -->
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" bgcolor="#f7f9fd" style="background-color:#f7f9fd;border-bottom:1px solid #e6eaf4;">
    <tr>
      <td width="25%" align="center" style="padding:18px 6px;border-right:1px solid #e6eaf4;">
        <div style="font-family:'IBM Plex Mono',ui-monospace,monospace;font-weight:600;font-size:22px;color:#2451b8;">{{count_todos}}</div>
        <div style="font-size:11px;color:#6b7390;margin-top:2px;">{{label_todos}}</div>
      </td>
      <td width="25%" align="center" style="padding:18px 6px;border-right:1px solid #e6eaf4;">
        <div style="font-family:'IBM Plex Mono',ui-monospace,monospace;font-weight:600;font-size:22px;color:#1e9e74;">{{count_events}}</div>
        <div style="font-size:11px;color:#6b7390;margin-top:2px;">{{label_events}}</div>
      </td>
      <td width="25%" align="center" style="padding:18px 6px;border-right:1px solid #e6eaf4;">
        <div style="font-family:'IBM Plex Mono',ui-monospace,monospace;font-weight:600;font-size:22px;color:#7b5cc9;">{{count_archived}}</div>
        <div style="font-size:11px;color:#6b7390;margin-top:2px;">archived</div>
      </td>
      <td width="25%" align="center" style="padding:18px 6px;">
        <div style="font-family:'IBM Plex Mono',ui-monospace,monospace;font-weight:600;font-size:22px;color:#b9790e;">{{count_left_in_inbox}}</div>
        <div style="font-size:11px;color:#6b7390;margin-top:2px;">left in inbox</div>
      </td>
    </tr>
  </table>

{{#fetch_failed}}
  <!-- ===== FETCH FAILURE NOTICE ===== -->
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin:18px 0 0;"><tr>
    <td style="padding:0 22px;">
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>
        <td bgcolor="#fbeae8" style="background-color:#fbeae8;border:1px solid #f3cfcb;border-radius:12px;padding:12px 16px;font-size:12px;color:#a53a32;line-height:1.6;">
          <b style="font-family:'IBM Plex Sans',sans-serif;font-weight:600;color:#c8463d;">Partial run —</b> at least one fetch failed while this digest was built, so the sections below may be incomplete.
        </td>
      </tr></table>
    </td>
  </tr></table>
{{/fetch_failed}}

  <div style="padding:4px 22px 10px;">

{{#has_events}}
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>
      <td style="padding:24px 0 0;">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>
          <td width="26" valign="middle" style="padding:0 0 7px;">
            <span style="font-size:16px;line-height:18px;">📅</span>
          </td>
          <td valign="middle" style="padding:0 0 7px;font-family:'Manrope',-apple-system,sans-serif;font-weight:800;font-size:12px;letter-spacing:0.11em;color:#14785a;text-transform:uppercase;">Events</td>
          <td align="right" valign="middle" style="padding:0 0 7px;">
            <table role="presentation" cellpadding="0" cellspacing="0" align="right"><tr>
              <td bgcolor="#e4f7ef" style="background-color:#e4f7ef;border-radius:9px;padding:2px 9px;font-family:'IBM Plex Mono',ui-monospace,monospace;font-size:10.5px;font-weight:600;color:#14785a;">{{count_events}}</td>
            </tr></table>
          </td>
        </tr></table>
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>
          <td height="2" bgcolor="#1e9e74" style="background-color:#1e9e74;height:2px;line-height:2px;font-size:2px;">&nbsp;</td>
        </tr></table>
      </td>
    </tr></table>
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>
      <td style="padding:13px 0 0 14px;">
{{#events}}
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:{{#_last}}0{{/_last}}{{^_last}}10{{/_last}}px;"><tr>
          <td bgcolor="#e4f7ef" style="background-color:#e4f7ef;border:1px solid #bfead9;border-radius:12px;padding:13px 15px;">
            <table role="presentation" cellpadding="0" cellspacing="0" style="margin-bottom:8px;"><tr>
              <td bgcolor="#ffffff" style="background-color:#ffffff;border:1px solid #bfead9;border-radius:9px;padding:3px 8px;">
                <table role="presentation" cellpadding="0" cellspacing="0"><tr>
                  <td valign="middle" style="padding-right:5px;"><span style="font-size:11px;line-height:14px;">{{calendar_glyph}}</span></td>
                  <td valign="middle" style="font-family:'IBM Plex Mono',ui-monospace,monospace;font-size:10.5px;font-weight:600;color:#2f6b56;white-space:nowrap;">{{calendar}}</td>
                </tr></table>
              </td>
            </tr></table>
            <div style="font-family:'IBM Plex Sans',sans-serif;font-weight:600;font-size:14px;color:#171a24;line-height:1.4;">
              <a href="{{@link}}" style="color:#171a24;text-decoration:none;border-bottom:1px solid #7fc4ac;">{{title}}</a>
            </div>
{{#when}}
            <table role="presentation" cellpadding="0" cellspacing="0" style="margin-top:9px;"><tr>
              <td valign="middle" style="padding-right:14px;font-family:'IBM Plex Mono',ui-monospace,monospace;font-size:12px;color:#3d7a63;">{{when}}</td>
{{#location}}
              <td valign="middle" style="padding-right:5px;"><span style="font-size:11px;line-height:14px;">📍</span></td>
              <td valign="middle" style="font-family:'IBM Plex Mono',ui-monospace,monospace;font-size:12px;color:#3d7a63;">{{location}}</td>
{{/location}}
            </tr></table>
{{/when}}
{{#reconciled_note}}
            <div style="margin-top:10px;padding-top:10px;border-top:1px dashed #bfead9;font-size:11.5px;color:#4d8a72;line-height:1.55;">
              {{reconciled_note}}
            </div>
{{/reconciled_note}}
          </td>
        </tr></table>
{{/events}}
      </td>
    </tr></table>
{{/has_events}}
{{#has_todos}}
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>
      <td style="padding:24px 0 0;">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>
          <td width="26" valign="middle" style="padding:0 0 7px;">
            <span style="font-size:16px;line-height:18px;">☑️</span>
          </td>
          <td valign="middle" style="padding:0 0 7px;font-family:'Manrope',-apple-system,sans-serif;font-weight:800;font-size:12px;letter-spacing:0.11em;color:#1d4295;text-transform:uppercase;">To-dos created</td>
          <td align="right" valign="middle" style="padding:0 0 7px;">
            <table role="presentation" cellpadding="0" cellspacing="0" align="right"><tr>
              <td bgcolor="#eaf0fe" style="background-color:#eaf0fe;border-radius:9px;padding:2px 9px;font-family:'IBM Plex Mono',ui-monospace,monospace;font-size:10.5px;font-weight:600;color:#1d4295;">{{count_todos}}</td>
            </tr></table>
          </td>
        </tr></table>
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>
          <td height="2" bgcolor="#2451b8" style="background-color:#2451b8;height:2px;line-height:2px;font-size:2px;">&nbsp;</td>
        </tr></table>
      </td>
    </tr></table>
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>
      <td style="padding:13px 0 0 14px;">
{{#todos}}
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:{{#_last}}0{{/_last}}{{^_last}}10{{/_last}}px;"><tr>
          <td bgcolor="#eaf0fe" style="background-color:#eaf0fe;border:1px solid #c9d9fb;border-radius:12px;padding:13px 15px;">
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>
              <td style="font-family:'IBM Plex Sans',sans-serif;font-weight:600;font-size:14px;line-height:1.4;">
                <a href="{{@url}}" style="color:#171a24;text-decoration:none;border-bottom:1px solid #8fabe4;">{{title}}</a>
              </td>
{{#due}}
              <td align="right" valign="top" style="white-space:nowrap;padding-left:10px;">
                <table role="presentation" cellpadding="0" cellspacing="0" align="right"><tr>
                  <td bgcolor="#fbdedb" style="background-color:#fbdedb;border-radius:10px;padding:3px 9px;font-family:'IBM Plex Mono',ui-monospace,monospace;font-size:10.5px;font-weight:600;color:#b53d34;white-space:nowrap;">{{due}}</td>
                </tr></table>
              </td>
{{/due}}
            </tr></table>
{{#source_link}}
            <div style="margin-top:8px;font-size:12px;color:#3355a3;"><a href="{{@source_link}}" style="color:#3355a3;">source email</a></div>
{{/source_link}}
{{#reconciled_note}}
            <div style="margin-top:10px;padding-top:10px;border-top:1px dashed #c9d9fb;font-size:11.5px;color:#3355a3;line-height:1.55;">
              {{reconciled_note}}
            </div>
{{/reconciled_note}}
          </td>
        </tr></table>
{{/todos}}
      </td>
    </tr></table>
{{/has_todos}}
{{#has_threads}}
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>
      <td style="padding:24px 0 0;">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>
          <td width="26" valign="middle" style="padding:0 0 7px;">
            <span style="font-size:16px;line-height:18px;">💬</span>
          </td>
          <td valign="middle" style="padding:0 0 7px;font-family:'Manrope',-apple-system,sans-serif;font-weight:800;font-size:12px;letter-spacing:0.11em;color:#8a5c0a;text-transform:uppercase;">Left in your inbox</td>
          <td align="right" valign="middle" style="padding:0 0 7px;">
            <table role="presentation" cellpadding="0" cellspacing="0" align="right"><tr>
              <td bgcolor="#fcf1dd" style="background-color:#fcf1dd;border-radius:9px;padding:2px 9px;font-family:'IBM Plex Mono',ui-monospace,monospace;font-size:10.5px;font-weight:600;color:#8a5c0a;">{{count_threads}}</td>
            </tr></table>
          </td>
        </tr></table>
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>
          <td height="2" bgcolor="#b9790e" style="background-color:#b9790e;height:2px;line-height:2px;font-size:2px;">&nbsp;</td>
        </tr></table>
      </td>
    </tr></table>
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>
      <td style="padding:13px 0 0 14px;">
{{#from_personal_threads}}
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:{{#_last}}0{{/_last}}{{^_last}}10{{/_last}}px;"><tr>
          <td bgcolor="#fcf1dd" style="background-color:#fcf1dd;border:1px solid #f2dcae;border-radius:12px;padding:13px 15px;">
            <div style="font-family:'IBM Plex Sans',sans-serif;font-weight:600;font-size:14px;color:#171a24;line-height:1.4;">
              <a href="{{@link}}" style="color:#171a24;text-decoration:none;border-bottom:1px solid #d9b055;">{{title}}</a>
{{#kind_label}}
              <span style="display:inline-block;background-color:#f2dcae;font-family:'IBM Plex Mono',ui-monospace,monospace;font-size:10px;font-weight:600;color:#8a5c0a;padding:2px 7px;border-radius:8px;margin-left:6px;">{{kind_label}}</span>
{{/kind_label}}
            </div>
{{#when_or_due}}
            <table role="presentation" cellpadding="0" cellspacing="0" style="margin-top:9px;"><tr>
              <td valign="middle" style="font-family:'IBM Plex Mono',ui-monospace,monospace;font-size:12px;color:#8a5c0a;">{{when_or_due}}</td>
            </tr></table>
{{/when_or_due}}
{{#note}}
            <div style="margin-top:10px;padding-top:10px;border-top:1px dashed #f2dcae;font-size:11.5px;color:#8a5c0a;line-height:1.55;">
              {{note}}
            </div>
{{/note}}
          </td>
        </tr></table>
{{/from_personal_threads}}
      </td>
    </tr></table>
{{/has_threads}}
{{#has_archived}}
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>
      <td style="padding:24px 0 0;">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>
          <td width="26" valign="middle" style="padding:0 0 7px;">
            <span style="font-size:16px;line-height:18px;">📥</span>
          </td>
          <td valign="middle" style="padding:0 0 7px;font-family:'Manrope',-apple-system,sans-serif;font-weight:800;font-size:12px;letter-spacing:0.11em;color:#5f43a8;text-transform:uppercase;">Archived</td>
          <td align="right" valign="middle" style="padding:0 0 7px;">
            <table role="presentation" cellpadding="0" cellspacing="0" align="right"><tr>
              <td bgcolor="#ece5fa" style="background-color:#ece5fa;border-radius:9px;padding:2px 9px;font-family:'IBM Plex Mono',ui-monospace,monospace;font-size:10.5px;font-weight:600;color:#6a4cb8;">{{count_archived}}</td>
            </tr></table>
          </td>
        </tr></table>
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>
          <td height="2" bgcolor="#7b5cc9" style="background-color:#7b5cc9;height:2px;line-height:2px;font-size:2px;">&nbsp;</td>
        </tr></table>
      </td>
    </tr></table>
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>
      <td style="padding:13px 0 0 14px;">
{{#archived}}
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin:{{#_first}}0{{/_first}}{{^_first}}16{{/_first}}px 0 6px;"><tr>
          <td style="font-family:'IBM Plex Sans',sans-serif;font-weight:600;font-size:11.5px;color:#5b4a91;letter-spacing:0.02em;text-transform:uppercase;">{{category}}</td>
          <td align="right" width="40">
            <table role="presentation" cellpadding="0" cellspacing="0" align="right"><tr>
              <td bgcolor="#ece5fa" style="background-color:#ece5fa;border-radius:8px;padding:2px 9px;font-family:'IBM Plex Mono',ui-monospace,monospace;font-size:10.5px;font-weight:600;color:#6a4cb8;">{{count}}</td>
            </tr></table>
          </td>
        </tr></table>
        <div style="border:1px solid #eee9fa;border-radius:10px;overflow:hidden;">
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
{{#items}}
            <tr{{^_last}} style="border-bottom:1px solid #f2effa;"{{/_last}}>
              <td valign="top" style="padding:11px 0 11px 12px;width:34px;">
                <table role="presentation" cellpadding="0" cellspacing="0"><tr>
                  <td width="22" height="22" align="center" valign="middle" bgcolor="{{brand_color}}" style="width:22px;height:22px;background-color:{{brand_color}};border-radius:6px;color:#ffffff;font-family:'Manrope',sans-serif;font-weight:700;font-size:11px;text-align:center;">{{brand_initial}}</td>
                </tr></table>
              </td>
              <td style="padding:10px 4px 10px 10px;">
                <a href="#" style="font-size:13px;color:#171a24;text-decoration:none;">{{subject}}</a>
                <div style="font-size:11px;color:#9aa0b4;margin-top:1px;">{{sender}}{{#gist}} &middot; {{gist}}{{/gist}}</div>
              </td>
{{#unsubscribe_link}}
              <td align="right" valign="middle" style="padding:10px 12px;white-space:nowrap;">
                <table role="presentation" cellpadding="0" cellspacing="0" align="right"><tr>
                  <td bgcolor="#f0ebfb" style="background-color:#f0ebfb;border-radius:8px;padding:4px 10px;">
                    <a href="{{@unsubscribe_link}}" style="color:#6a4cb8;font-size:11px;font-weight:600;text-decoration:none;">Unsub</a>
                  </td>
                </tr></table>
              </td>
{{/unsubscribe_link}}
{{^unsubscribe_link}}
              <td></td>
{{/unsubscribe_link}}
            </tr>
{{/items}}
          </table>
        </div>
{{/archived}}
      </td>
    </tr></table>
{{/has_archived}}
{{#has_recent_logins}}
    <div style="margin:22px 0 0;font-family:'IBM Plex Mono',ui-monospace,monospace;font-size:11px;color:#9aa0b4;line-height:1.7;">
      Recent logins: {{#recent_logins}}{{.}}{{^_last}} &nbsp;&middot;&nbsp; {{/_last}}{{/recent_logins}}
    </div>
{{/has_recent_logins}}

  </div>

  <!-- Footer -->
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin:6px 0 0;"><tr>
    <td style="padding:0 22px 22px;">
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>
        <td bgcolor="#fcf1dd" style="background-color:#fcf1dd;border:1px solid #f2dcae;border-radius:12px;padding:14px 16px;">
          <div style="font-family:'IBM Plex Sans',sans-serif;font-weight:600;font-size:12.5px;color:#171a24;margin-bottom:4px;">Triage summary</div>
          <div style="font-size:12px;color:#5f5233;line-height:1.6;">
            All routine items handled — this digest is never archived, so past summaries stay put. Reconcile anytime with <code style="background-color:#f2dcae;padding:1px 5px;border-radius:4px;">label:AI/Triaged</code>.{{#has_left_in_inbox}} Left in your inbox: {{count_left_in_inbox}} {{label_left_in_inbox}} that need you.{{/has_left_in_inbox}}
          </div>
        </td>
      </tr></table>
    </td>
  </tr></table>

</div>
</div>
<!-- ===================== /EMAIL BODY ===================== -->


  </div>
  <div class="caption">↑ this frame's contents are the literal email — inline styles, table layout, no external assets</div>
</div>
'''

TEMPLATE_FILENAME = "digest_template.html"

# The template doubles as a standalone preview page: the email itself is the slice
# between these two markers. Both are literal template text, and no interpolated value
# can forge one (every "<" from the payload is escaped), so slicing the output is safe.
BODY_START = "<!-- ======================= EMAIL BODY"
BODY_END = "<!-- ===================== /EMAIL BODY ===================== -->"

# Body-only output carries no HTML comments at all — not the markers, not the
# section labels inside them. The Gmail send path the routine uses rewrites the
# markup it is handed, and a comment does not reliably survive: the 2026-09-03
# digest rendered the opening marker as a visible line of text above the card
# (#340). Dropping them costs nothing (they are notes to whoever edits the
# template, and the preview page keeps them) and removes the failure mode.
# A comment on a line of its own takes the whole line with it, so the body keeps the
# template's shape instead of gaining a blank line wherever a note used to be.
COMMENT_RE = re.compile(r"[ \t]*<!--.*?-->[ \t]*\n?", re.DOTALL)


class TemplateError(Exception):
    """Raised for a malformed template — a build-time bug, never payload-driven."""


# ---------------------------------------------------------------------------
# Mini template engine
# ---------------------------------------------------------------------------

_TAG = re.compile(r"\{\{\s*([#^/@]?)\s*([\w.]+)\s*\}\}")
_STANDALONE = re.compile(r"^[ \t]*(\{\{[#^/][^{}]*\}\})[ \t]*(?:\r?\n|$)", re.M)


def _parse(source: str) -> list:
    """Compile the template into a nested node list: text / var / url / section."""
    source = _STANDALONE.sub(r"\1", source)
    root: list = []
    stack = [root]
    open_names: list[str] = []
    pos = 0
    for match in _TAG.finditer(source):
        if match.start() > pos:
            stack[-1].append(("text", source[pos:match.start()]))
        pos = match.end()
        sigil, name = match.group(1), match.group(2)
        if sigil in ("#", "^"):
            block: list = []
            stack[-1].append(("section" if sigil == "#" else "inverted", name, block))
            stack.append(block)
            open_names.append(name)
        elif sigil == "/":
            if not open_names or open_names[-1] != name:
                expected = open_names[-1] if open_names else "nothing"
                raise TemplateError(f"{{{{/{name}}}}} closes {expected}")
            open_names.pop()
            stack.pop()
        elif sigil == "@":
            stack[-1].append(("url", name))
        else:
            stack[-1].append(("var", name))
    if open_names:
        raise TemplateError(f"unclosed section {{{{#{open_names[-1]}}}}}")
    if pos < len(source):
        root.append(("text", source[pos:]))
    return root


def _lookup(stack: list, name: str):
    for frame in reversed(stack):
        if isinstance(frame, dict) and name in frame:
            return frame[name]
    return None


def _text(value) -> str:
    """Escaped text. Note 0 renders as "0" — a zero count is data, not emptiness."""
    if value is None or value is False:
        return ""
    return html.escape(str(value), quote=True)


def validate_url(value):
    """Return the URL if it is a plain http(s) URL, else None.

    An allow-list, not a blocklist: `javascript:`, `data:`, `vbscript:`, a scheme-less
    path, and anything with a newline (header/attribute splitting) all fail closed.
    """
    if not isinstance(value, str):
        return None
    candidate = value.strip()
    if any(c in candidate for c in "\r\n\t") or any(ord(c) < 0x20 for c in candidate):
        return None
    if candidate.lower().startswith(("http://", "https://")):
        return candidate
    return None


def _url(value) -> str:
    """An href value. Anything not provably http(s) collapses to a dead anchor."""
    valid = validate_url(value)
    return html.escape(valid, quote=True) if valid else "#"


def _render_nodes(nodes: list, stack: list, out: list) -> None:
    for node in nodes:
        kind = node[0]
        if kind == "text":
            out.append(node[1])
        elif kind == "var":
            out.append(_text(_lookup(stack, node[1])))
        elif kind == "url":
            out.append(_url(_lookup(stack, node[1])))
        elif kind == "section":
            value = _lookup(stack, node[1])
            if isinstance(value, (list, tuple)):
                total = len(value)
                for index, item in enumerate(value):
                    meta = {
                        ".": item,
                        "_first": index == 0,
                        "_last": index == total - 1,
                        "_index": index + 1,
                        "_count": total,
                    }
                    frames = stack + [meta] + ([item] if isinstance(item, dict) else [])
                    _render_nodes(node[2], frames, out)
            elif value:
                frames = stack + ([value] if isinstance(value, dict) else [])
                _render_nodes(node[2], frames, out)
        elif kind == "inverted":
            value = _lookup(stack, node[1])
            if not value:
                _render_nodes(node[2], stack, out)
    return None


def render(template: str, context: dict) -> str:
    out: list[str] = []
    _render_nodes(_parse(template), [context], out)
    return "".join(out)


# ---------------------------------------------------------------------------
# Payload -> template context
# ---------------------------------------------------------------------------

# Keys whose values are hrefs. Sanitized once here so that `{{#link}}` is *false* for a
# hostile URL and the surrounding element disappears entirely, rather than rendering an
# element around a neutered href.
URL_FIELDS = frozenset({"link", "url", "source_link", "unsubscribe_link"})

# Sender avatar colors, all lifted from the approved mockup's own palette.
BRAND_COLORS = ("#4285f4", "#403494", "#f56400", "#e44332", "#c94f7c", "#1e9e74",
                "#7b5cc9", "#2451b8", "#b9790e")

# The handful of senders that show up nearly every run get their real brand color, as
# the mockup hand-assigned them. Everything else falls through to the stable hash, so
# this table is a nicety, not a dependency — order matters, first substring wins.
BRAND_OVERRIDES = (
    ("youtube", "#e44332"), ("google", "#4285f4"), ("gmail", "#4285f4"),
    ("todoist", "#e44332"), ("etsy", "#f56400"), ("itch.io", "#403494"),
    ("github", "#2f3242"), ("amazon", "#f56400"), ("apple", "#4a5170"),
)

KIND_LABELS = {"event": "event created", "todo": "to-do created"}

# The digest shows one Events section, not two. Fisher's own calendar and the shared
# family one are the same kind of thing to a reader glancing at the morning email, and
# splitting them buried "Lisa moved swim lessons" four sections down from "you have a
# dentist appointment". They merge, and each row carries a badge naming its calendar
# instead — the calendars are "Personal" and "Nottingham" in ROUTINE-PROMPT.md, shown
# here as the shorter labels below.
#
# Both payload keys are still accepted, so a payload written against the old schema
# renders unchanged; `events` rows default to Fisher's label and `family_calendar` rows
# to the family one. A row may override with its own `calendar` field, which is the
# forward-looking form — most events the routine creates land on Nottingham.
PERSONAL_CALENDAR = "Fisher"
FAMILY_CALENDAR = "Nottingham"

# Substrings that mean "the shared one" for the purpose of picking the badge glyph, so
# the icon follows the label rather than which payload key the row arrived under.
FAMILY_HINTS = ("nottingham", "family", "shared")

# Icons are Unicode, not images. The Gmail send path the routine uses deletes every
# `<img>` it is handed — remote src and `cid:` inline attachment alike, verified by
# probe on 2026-09-03 (#342) — so an image in this template is a blank gap by
# construction, exactly as `<svg>` was before it. A glyph is text and arrives.
FAMILY_GLYPH = "\N{BUSTS IN SILHOUETTE}"
PERSONAL_GLYPH = "\N{BUST IN SILHOUETTE}"


def _rows(value) -> list:
    return [r for r in value if isinstance(r, dict)] if isinstance(value, list) else []


def _clean(raw: dict) -> dict:
    """Drop empty fields (so `{{#due}}` omits the pill) and sanitize every href."""
    out = {}
    for key, value in raw.items():
        if key in URL_FIELDS:
            valid = validate_url(value)
            if valid:
                out[key] = valid
        elif value is None or value == "":
            continue
        else:
            out[key] = value
    return out


def _calendar_row(raw: dict, default_label: str) -> dict:
    """One event row, tagged with the calendar it belongs to.

    `calendar` and `calendar_glyph` are always set here, never taken from the payload as
    given — the label is a caption a reader trusts, so it is derived from a fixed set
    rather than accepted from email-shaped input.
    """
    row = _clean(raw)
    label = str(row.get("calendar") or default_label).strip() or default_label
    row["calendar"] = label
    lowered = label.lower()
    family = any(hint in lowered for hint in FAMILY_HINTS)
    row["calendar_glyph"] = FAMILY_GLYPH if family else PERSONAL_GLYPH
    return row


def _count(value) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _brand(sender: str) -> tuple[str, str]:
    """Deterministic avatar for a sender: stable color + first alphanumeric initial.

    crc32, not hash() — hash() is salted per process, which would make the rendered
    bytes differ between runs for identical input.
    """
    lowered = sender.lower()
    color = next((c for key, c in BRAND_OVERRIDES if key in lowered), None)
    if color is None:
        color = BRAND_COLORS[zlib.crc32(sender.encode("utf-8")) % len(BRAND_COLORS)]
    initial = next((c for c in sender if c.isalnum()), "?")
    return color, initial.upper()


def build_context(payload: dict) -> dict:
    counts = payload.get("counts") if isinstance(payload.get("counts"), dict) else {}
    # `left_in_inbox` has no corresponding list (those threads are deliberately absent
    # from the digest), so it can only come from the payload.
    n_left = _count(counts.get("left_in_inbox"))

    events = [_calendar_row(r, PERSONAL_CALENDAR) for r in _rows(payload.get("events"))]
    events += [_calendar_row(r, FAMILY_CALENDAR)
               for r in _rows(payload.get("family_calendar"))]
    todos = [_clean(r) for r in _rows(payload.get("todos"))]
    threads = []
    for raw in _rows(payload.get("from_personal_threads")):
        row = _clean(raw)
        kind = row.get("kind")
        if kind:
            row["kind_label"] = KIND_LABELS.get(str(kind), f"{kind} created")
        threads.append(row)
    archived = []
    for raw in _rows(payload.get("archived")):
        items = []
        for item_raw in _rows(raw.get("items")):
            item = _clean(item_raw)
            color, initial = _brand(str(item.get("sender", "")))
            item["brand_color"] = color
            item["brand_initial"] = initial
            items.append(item)
        if items:
            archived.append({"category": raw.get("category") or "Other",
                             "count": len(items), "items": items})

    logins = [str(l) for l in payload.get("recent_logins") or [] if l]

    # Counts are DERIVED from the lists they label, not read from `counts`. The KPI strip
    # and the "Archived · N" header sit directly above the rows they count, so a payload
    # whose `counts` disagreed with its own lists rendered a digest that visibly
    # contradicted itself (the first sample payload said 6 and listed 7). The routine
    # composing this is an LLM keeping two representations of the same number in sync by
    # hand; deriving deletes that failure mode. `counts` is still accepted as a fallback
    # for a section whose list is absent entirely.
    n_todos = len(todos) or _count(counts.get("todos"))
    n_events = len(events) or _count(counts.get("events"))
    n_threads = len(threads)
    n_archived = sum(c["count"] for c in archived) or _count(counts.get("archived"))

    return {
        "subject": payload.get("subject") or "",
        "date_label": payload.get("date_label") or "",
        "completed_at": payload.get("completed_at") or "",
        "fetch_failed": bool(payload.get("fetch_failed")),
        "count_todos": n_todos,
        "count_events": n_events,
        "count_threads": n_threads,
        "count_archived": n_archived,
        "count_left_in_inbox": n_left,
        "label_todos": "to-do" if n_todos == 1 else "to-dos",
        "label_events": "event" if n_events == 1 else "events",
        "label_left_in_inbox": "thread" if n_left == 1 else "threads",
        "has_left_in_inbox": n_left > 0,
        "events": events, "has_events": bool(events),
        "todos": todos, "has_todos": bool(todos),
        "from_personal_threads": threads, "has_threads": bool(threads),
        "archived": archived, "has_archived": bool(archived),
        "recent_logins": logins, "has_recent_logins": bool(logins),
    }


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------

def load_template() -> str:
    if EMBEDDED_TEMPLATE is not None:
        return EMBEDDED_TEMPLATE
    return (pathlib.Path(__file__).resolve().parent / TEMPLATE_FILENAME).read_text(encoding="utf-8")


def email_body(document: str) -> str:
    """Just the inline-styled email, without the preview page's chrome or any comments.

    Stripping every `<!-- ... -->` from the slice is safe because each interpolated
    value is HTML-escaped, so no payload can introduce a comment of its own.
    """
    start = document.find(BODY_START)
    end = document.find(BODY_END)
    if start == -1 or end == -1:
        return document
    return COMMENT_RE.sub("", document[start:end + len(BODY_END)]).strip() + "\n"


def render_digest(payload: dict, body_only: bool = False, template: str | None = None) -> str:
    document = render(template if template is not None else load_template(),
                      build_context(payload))
    return email_body(document) if body_only else document


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Render the inbox-triage digest email.")
    parser.add_argument("payload", help="path to the payload JSON, or - to read stdin")
    parser.add_argument("--body-only", action="store_true",
                        help="emit only the email body, dropping the preview page chrome")
    args = parser.parse_args(argv)

    raw = sys.stdin.read() if args.payload == "-" else \
        pathlib.Path(args.payload).read_text(encoding="utf-8")
    sys.stdout.write(render_digest(json.loads(raw), body_only=args.body_only))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
