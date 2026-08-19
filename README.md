# inbox-triage-tools

Two helper scripts for a personal daily email-triage routine that runs as a scheduled
Claude agent.

| Script | Does |
| --- | --- |
| `email_extract.py` | From a raw email body: the primary link, the unsubscribe link, and a one-line gist. |
| `render_digest.py` | From a JSON payload: the digest email's HTML. |

```sh
python3 email_extract.py body.json          # {"html": ..., "plaintext": ..., "subject": ...}
python3 render_digest.py payload.json --body-only > digest.html
```

## Zero dependencies, on purpose

Both are single files using only the Python standard library, on any CPython >= 3.9.
There is nothing to `pip install`.

The routine that uses these runs unattended in a sandbox with a policy-gated network. Every
morning it has to get from nothing to working with no one watching, so each thing it must
fetch or install is a step that can fail silently. Zero dependencies means that once the
files are on disk, they run.

`email_extract.py` parses with `html.parser.HTMLParser` - a real incremental tokenizer, not
a regex tag-stripper. Marketing email HTML is minified, deeply nested, and padded with
invisible characters; regex over it silently returns wrong answers (swallowing `<script>`
bodies as visible text, breaking on `>` inside attribute values, missing a word split
across inline tags like `<span>Un</span>subscribe`).

## Nothing sensitive here

These are generic and self-contained. They hold no configuration, credentials, endpoints,
or personal data, and process only text handed to them in a local file. The routine's
actual triage rules live elsewhere and are not published.

## Source of truth

Generated artifacts, mirrored from a private repo where the source, tests, and the
`digest_template.html` design live. Edit there and re-sync; changes made directly here
will be overwritten.
