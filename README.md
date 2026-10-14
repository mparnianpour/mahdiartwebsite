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

Everything you see now is **example content** with placeholder images marked
“EXAMPLE IMAGE”. Replace it with your own work (steps below).

---

## 1. Put the site online (once)

1. Merge this branch into `main`.
2. On GitHub open **Settings → Pages**.
3. Under **Build and deployment** choose **Deploy from a branch**, branch `main`, folder `/ (root)`, and save.
4. After a minute or two the site is live at
   **https://mparnianpour.github.io/mahdiartwebsite/**

Every change you commit to `main` after that updates the site automatically.

## 2. Edit your details

- **`_config.yml`**: your name, the headline on the home page, your email
  (leave `email: ""` to hide it), Instagram name and portrait photo.
- **`about/index.md`**: your statement and biography. The text there now is a
  **draft**, so rewrite it in your own words. The short quote at the top
  (`statement_short`) appears on the home page.
- **`_data/cv.yml`**: exhibitions, education, residencies, press. Empty sections stay hidden.

## 3. Add a painting

You can do all of this in the browser on github.com.

1. **Upload the photos.** Go to `assets/img/works/`, click **Add file → Upload files**,
   and upload them into a new folder named after the painting,
   e.g. `assets/img/works/blue-ground/`
   (type `blue-ground/` in front of the file name to create the folder).
   Use simple names: `stage-1.jpg`, `stage-2.jpg`, …, `final.jpg`, `sketch-1.jpg`.
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

- **Size:** resize to about **2000 px** on the long side and save as JPG
  (around 300–800 KB). Photos straight from a phone are much larger and make the site slow.
- **Stages:** photograph the canvas from the same spot and in the same light
  each time. The stage viewer fades from one photo to the next, so consistent
  photos show the changes clearly.
- **Finished works:** photograph straight on, in daylight without glare, and crop to the edge of the canvas.
- **From Instagram:** use the original photos from your phone if you still
  have them. Otherwise download your posts via Instagram
  **Settings → Accounts Center → Your information and permissions → Download your information**.

## 6. Remove the examples

When you have added your own work, delete:

- `_works/example-1.md`, `_works/example-2.md`, `_works/example-3.md`
- every file in `_posts/` that you did not write
- the folders `assets/img/works/example-1`, `example-2`, `example-3`
- the example images in `assets/img/journal/`

## 7. Your own domain (optional)

If you buy a domain such as `mahdiparnianpour.com`, add it under
**Settings → Pages → Custom domain**, then in `_config.yml` set
`url: https://mahdiparnianpour.com` and `baseurl: ""`.

## Preview on your own computer (optional)

Requires Ruby. Run `bundle install`, then `bundle exec jekyll serve`, and open
http://localhost:4000/mahdiartwebsite/
