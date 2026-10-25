# mahdiartwebsite

Portfolio site for the painter Mahdi Parnianpour. Paintings are shown together
with the sketches, stages and studio days that produced them, so visitors can
see the thinking and decisions behind each abstract work.

| Page | What it shows |
| --- | --- |
| **Home** | Short introduction, a featured painting with its stages, recent works, a calendar of studio days, latest journal entries, statement |
| **Works** | All paintings by year. Each painting has its own page with a stage-by-stage viewer, its sketches and related journal entries |
| **Journal** | A dated studio log: painting sessions, sketches, tests, notes |
| **Sketchbook** | Daily sketches, and sketches grouped by the painting they led to |
| **About** | Statement, biography, CV, contact |

Live at **https://mparnianpour.github.io/mahdiartwebsite/**

The **Journal** and **Sketchbook** links appear in the menu automatically once
they have entries.

---

## 1. Publishing

GitHub Pages builds the site from the `main` branch
(**Settings → Pages → Deploy from a branch**, `main`, `/ (root)`).
Every change committed to `main` updates the live site within a minute or two.

## 2. Edit your details

- **`_config.yml`**: your name, the headline on the home page, your email
  (leave `email: ""` to hide it), Instagram name and portrait photo.
- **`about/index.md`**: your statement and biography. The text there now is a
  **draft**, so rewrite it in your own words. The short quote at the top
  (`statement_short`) appears on the home page.
- **`_data/cv.yml`**: exhibitions, education, residencies, press. Empty sections stay hidden.

## 3. Add a painting

The archive pipeline (section 6) does this automatically from Google Drive.
To add a painting by hand, you can do all of this in the browser on github.com.

1. **Watermark and add the photos.** Every photo must go through
   `tools/protect_image.py` first (see **5. Photos**); don't upload photos
   straight from your phone. Put them in a folder named after the painting,
   e.g. `assets/img/works/blue-ground/`, with simple names:
   `stage-1.jpg`, `stage-2.jpg`, …, `final.jpg`, `sketch-1.jpg`.
2. **Create the page.** Go to `_works/`, click **Add file → Create new file**,
   name it `blue-ground.md`, and paste in the contents of
   [`_templates/work.md`](_templates/work.md). Fill in the title, size,
   medium, dates and the image paths, then write a few sentences under the
   `---` about what the painting is working through.
3. **Commit.**

Notes:
- List `stages` oldest first. The main `image` is added automatically as the last stage.
- Set `status: In progress` for a painting that is still on the easel, and add stages as it develops.
- Set `featured: true` on the one painting you want shown large on the home page.
- If you only have a photo of the finished work, leave out `stages` and `sketches`.

## 4. Add a journal entry (daily)

1. Upload the day's photo(s) to `assets/img/journal/`, e.g. `2026-10-14-1.jpg`.
2. In `_posts/`, create a file whose name **starts with the date**:
   `2026-10-14-short-title.md`, and paste in
   [`_templates/journal-entry.md`](_templates/journal-entry.md).
3. Choose a `type`:
   - `painting`: worked on a canvas
   - `sketch`: also appears in the Sketchbook
   - `studio`: preparing, tests, photographing, anything else
   - `note`: a thought, something you read or saw (pictures optional)
4. If the entry belongs to a painting, add `work: blue-ground` (the painting's
   file name without `.md`). The entry then also appears on that painting's page.

Each entry also fills in a square on the studio calendar on the home page.

## 5. Photos

- **Watermark every photo.** Run each one through the script before adding it:

  ```
  python3 tools/protect_image.py phone-photo.jpg assets/img/works/blue-ground/final.jpg
  ```

  It resizes the photo to at most 2000 px, adds a faint diagonal
  "© MAHDI PARNIANPOUR" across the image and a "© year Mahdi Parnianpour"
  credit in the corner, and embeds your copyright with a "no AI training"
  flag (IPTC/PLUS Data Mining) in the file. Use `--crop x0,y0,x1,y1` to
  crop first. The site's pages also carry "noai" and TDM-reservation tags.
  Keep your full-resolution originals off GitHub.
- **Stages:** photograph the canvas from the same spot and in the same light
  each time. The stage viewer fades from one photo to the next, so consistent
  photos show the changes clearly.
- **Finished works:** photograph straight on, in daylight without glare, and crop to the edge of the canvas.
- **From Instagram:** use the original photos from your phone if you still
  have them. Otherwise download your posts via Instagram
  **Settings → Accounts Center → Your information and permissions → Download your information**.

## 6. The archive pipeline (automatic)

Instead of adding paintings by hand, photos can flow in from Google Drive.
A scheduled Claude session runs a **batch** every few hours: it reads new
photos from Drive, recognises which photos show the same painting (even
months apart), writes a short note for each stage, puts sketches and
drawings into the private sketchbook, reads visitor comments, reviews how the
site presents the work, and publishes the result to `main`. It never uses
more than 80% of your Claude plan's usage, so 20% always stays free for you.

- **How to feed it:** export Google Photos albums with
  [Google Takeout](https://takeout.google.com) to Drive (they arrive in the
  `Takeout` folder), or let an auto-sync app copy new photos into a Drive
  folder named `Studio Archive`. Full-size photos never go to GitHub.
- **What it did:** each batch writes a log in [`archive/batches/`](archive/batches/),
  with links to new works and a list of anything waiting for you.
- **Titles:** new works get working titles like *Untitled (Reeds)*. Rename
  them in the work's file in `_works/` (or ask Claude); later batches keep
  your title, medium and size.
- **How it works:** [`pipeline/PLAYBOOK.md`](pipeline/PLAYBOOK.md) has the
  steps each batch follows; [`archive/`](archive/README.md) is its memory.

### Private sketchbook

Sketches and drawings are encrypted before they are added, and the
**Sketchbook** page asks for a password to show them. The repository is
public, so this is the only way to keep them private: without the password
the files cannot be opened. The password is the `VAULT_PASSWORD` setting of
the cloud environment; share it only with people who should see the drawings.

### Visitor comments

The **Comments** page sends comments to a Google Form; they appear on the
site after a batch has read them.

1. Create a Google Form with three questions: *Name* (short answer),
   *About* (short answer) and *Comment* (paragraph, required).
2. In the form's **Responses** tab, click **Link to Sheets**. Share that sheet
   with the pipeline's service account (Viewer).
3. Click **⋮ → Get pre-filled link**, type `x` in each field, **Get link**,
   and send that link to Claude. It contains the ids that go into
   `_config.yml` under `comments:`.

## 7. Your own domain (optional)

If you buy a domain such as `mahdiparnianpour.com`, add it under
**Settings → Pages → Custom domain**, then in `_config.yml` set
`url: https://mahdiparnianpour.com` and `baseurl: ""`.

## Preview on your own computer (optional)

Requires Ruby. Run `bundle install`, then `bundle exec jekyll serve`, and open
http://localhost:4000/mahdiartwebsite/
