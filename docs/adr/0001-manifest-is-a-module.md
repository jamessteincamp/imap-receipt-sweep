# The manifest is a module; judgement stays in the skill

The sweep's mechanical rules — file naming, never overwriting, Message-ID de-dupe, the per-account cap, the window, file-before-line — used to live as prose in SKILL.md that the model carried out by hand, with `manifest_check.py` validating afterwards. They now live in one module, `skill/imap-receipt-sweep/scripts/manifest.py`, with two entry points: `status` (the state a run starts from) and `save` (file one keep, refusing anything invalid before a byte is written). Classification, amounts, vendor and which artifact to save remain the model's judgement, in prose. The README's "why a skill and not code" holds: the judgement is the skill; the easy parts are now code, not a few lines the skill states.

## Considered options

- **A wide interface** (separate `has`, `query`, `check --repair`, `schema` commands, and a new `run` field on every line): rejected. A per-candidate `has` costs one shell call per message, and a new field breaks any consumer validating against the published schema, whose `additionalProperties` is false. Run membership is derived from `swept_at` instead.
- **Handing `save` the raw `mail_fetch` record** so it derives Message-ID, date, sender and subject itself: rejected. It ties the manifest to the upstream server's result format, which we pin but do not own. `save` normalises those fields from whatever the model passes instead.

## Consequences

- `manifest.schema.json` moved from the repo root into the skill folder, and `manifest.py` reads it at runtime: one source for the line format, shipped with the skill. Its published URL (`$id`) changed with it.
- `account` has one definition: the server config file's stem. By the kit's convention the MCP server is `mail-<stem>`, so `save` writes `mail-personal` (or `icloud-personal`) as `personal`. Manifests written under the earlier prose rule may hold other labels; de-dupe is unaffected (it is cross-account), per-account counts are not.
- The sender slug skips a two-label public suffix (`shop.co.uk` → `shop`, previously `co`). Files already saved keep their names.
