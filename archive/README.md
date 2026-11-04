# Archive memory

What the pipeline (`pipeline/`) remembers between batches. Each batch adds
to these files; nothing is ever started over.

| File | What it holds |
| --- | --- |
| `photos.json` | Every photo seen, one line each, keyed by a hash of the photo: when it was taken, which Drive file it came from, its status (`new`, `published`, `private`, `private-pending`, `held`, `skipped`) and the work it belongs to. |
| `sources.json` | Drive files already read (Takeout zips and loose photos), so they are not read twice. |
| `works.json` | Public paintings: their stages in order, with labels and notes. The pages in `_works/` are written from it. |
| `embeddings/` | Image embeddings (DINOv2), one file per batch, used to recognise new photos of earlier works. |
| `batches/` | A log of each batch: what came in, what was published, what waits for Mahdi, and the critique of the site. |
| `comments.json` | Which visitor comments have been handled. |
| `settings.json` | Drive folders to read, time zone, model, comments sheet, budget limit. |

Private drawings are recorded here only by id, date and status; their titles
and notes live encrypted in `assets/vault/`.
