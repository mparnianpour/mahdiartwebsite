/* Private sketchbook: asks for the password and decrypts the drawings in the
   browser. The files in assets/vault/ are AES-GCM encrypted by pipeline/vault.py
   with a key derived from the password (PBKDF2-SHA256); they are unreadable
   without it. */
(function () {
  "use strict";

  var root = document.querySelector("[data-vault]");
  if (!root) return;
  var form = root.querySelector("[data-vault-form]");
  var message = root.querySelector("[data-vault-message]");
  var content = root.querySelector("[data-vault-content]");
  if (!window.crypto || !window.crypto.subtle || !window.TextEncoder) {
    message.textContent = "This browser cannot open the private sketchbook.";
    return;
  }

  var meta = JSON.parse(root.querySelector("[data-vault-meta]").textContent);
  var base = root.getAttribute("data-base");
  var STORE = "sketchbook-key";
  var subtle = window.crypto.subtle;
  var key = null;

  function fromB64(s) {
    var bin = atob(s);
    var out = new Uint8Array(bin.length);
    for (var i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
    return out;
  }
  function toB64(buf) {
    var bytes = new Uint8Array(buf);
    var s = "";
    for (var i = 0; i < bytes.length; i++) s += String.fromCharCode(bytes[i]);
    return btoa(s);
  }
  function remember(raw) { try { sessionStorage.setItem(STORE, toB64(raw)); } catch (e) { /* private mode */ } }
  function remembered() { try { return sessionStorage.getItem(STORE); } catch (e) { return null; } }
  function forget() { try { sessionStorage.removeItem(STORE); } catch (e) { /* private mode */ } }

  function derive(password) {
    return subtle.importKey("raw", new TextEncoder().encode(password), "PBKDF2", false, ["deriveBits"])
      .then(function (material) {
        return subtle.deriveBits({ name: "PBKDF2", salt: fromB64(meta.salt), iterations: meta.iterations, hash: "SHA-256" },
          material, 256);
      });
  }
  function decrypt(buf) {
    var bytes = new Uint8Array(buf);
    return subtle.decrypt({ name: "AES-GCM", iv: bytes.slice(0, 12) }, key, bytes.slice(12));
  }
  function load(name) {
    return fetch(base + name).then(function (r) {
      if (!r.ok) throw new Error("missing " + name);
      return r.arrayBuffer();
    }).then(decrypt);
  }
  function blobUrl(name) {
    return load(name).then(function (plain) {
      return URL.createObjectURL(new Blob([plain], { type: "image/jpeg" }));
    });
  }

  function open(raw, save) {
    return subtle.importKey("raw", raw, "AES-GCM", false, ["decrypt"]).then(function (k) {
      key = k;
      return decrypt(fromB64(meta.check).buffer);
    }).then(function () {
      if (save) remember(raw);
      return load("index.bin");
    }).then(function (plain) {
      render(JSON.parse(new TextDecoder().decode(plain)));
    });
  }

  function formatDate(iso) {
    var d = new Date(iso + "T12:00:00");
    return d.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
  }

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text) node.textContent = text;
    return node;
  }

  function render(index) {
    var entries = Object.keys(index.entries).map(function (slug) { return index.entries[slug]; });
    entries.sort(function (a, b) { return a.date < b.date ? 1 : a.date > b.date ? -1 : 0; });

    var bar = el("p", "vault__bar");
    var lock = el("button", "vault__lock", "Lock");
    lock.type = "button";
    lock.addEventListener("click", function () { forget(); window.location.reload(); });
    bar.appendChild(lock);

    var grid = el("div", "sketch-grid");
    var observer = "IntersectionObserver" in window ? new IntersectionObserver(function (items) {
      items.forEach(function (item) {
        if (!item.isIntersecting) return;
        observer.unobserve(item.target);
        show(item.target);
      });
    }, { rootMargin: "400px" }) : null;

    entries.forEach(function (entry) {
      entry.photos.forEach(function (photo, i) {
        var fig = el("figure", "sketch");
        var link = el("a", "zoomable");
        link.href = "#";
        link.setAttribute("data-zoom", "");
        var caption = (entry.title || "Drawing") + ", " + formatDate(photo.date) +
          (entry.photos.length > 1 ? " (" + (i + 1) + "/" + entry.photos.length + ")" : "");
        link.setAttribute("data-caption", caption + (photo.note ? ". " + photo.note : ""));
        var img = el("img");
        img.alt = caption;
        if (photo.w && photo.h) { img.width = photo.w; img.height = photo.h; }
        img.setAttribute("data-id", photo.id);
        link.appendChild(img);
        link.addEventListener("click", openFull, true);
        fig.appendChild(link);
        var cap = el("figcaption");
        var t = el("time", null, formatDate(photo.date));
        t.dateTime = photo.date;
        cap.appendChild(t);
        if (entry.title && i === 0) cap.appendChild(el("span", null, entry.title));
        if (photo.label) cap.appendChild(el("span", null, photo.label));
        fig.appendChild(cap);
        grid.appendChild(fig);
        if (observer) observer.observe(img); else show(img);
      });
    });

    form.hidden = true;
    content.innerHTML = "";
    content.appendChild(bar);
    content.appendChild(grid);
    content.hidden = false;
  }

  function show(img) {
    blobUrl(img.getAttribute("data-id") + ".t.bin").then(function (url) { img.src = url; })
      .catch(function () { img.alt += " (could not be loaded)"; });
  }

  // The site's lightbox opens link.href; fetch and decrypt the full image first.
  function openFull(e) {
    var link = e.currentTarget;
    if (link.getAttribute("data-ready")) return;
    e.preventDefault();
    e.stopPropagation();
    var id = link.querySelector("img").getAttribute("data-id");
    blobUrl(id + ".bin").then(function (url) {
      link.href = url;
      link.setAttribute("data-ready", "1");
      link.click();
    });
  }

  form.addEventListener("submit", function (e) {
    e.preventDefault();
    var input = form.querySelector("input[type=password]");
    var button = form.querySelector("button");
    button.disabled = true;
    message.textContent = "Opening…";
    derive(input.value).then(function (raw) {
      return open(raw, true);
    }).then(function () {
      message.textContent = "";
    }).catch(function () {
      key = null;
      message.textContent = "That password is not right.";
      input.select();
    }).then(function () {
      button.disabled = false;
    });
  });

  var saved = remembered();
  if (saved) {
    open(fromB64(saved).buffer, false).catch(function () { forget(); key = null; });
  }
})();
