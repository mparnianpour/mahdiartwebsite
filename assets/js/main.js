/* Mahdi Parnianpour — small enhancements. The site works without this file. */
(function () {
  "use strict";

  /* Process viewer: step through the stages of a painting. -------------- */

  function initProcess(root) {
    var frames = Array.prototype.slice.call(root.querySelectorAll("[data-frame]"));
    if (frames.length < 2) return;

    var panel = root.querySelector("[data-panel]");
    var caption = root.querySelector("[data-stage-caption]");
    var range = root.querySelector("[data-range]");
    var prev = root.querySelector("[data-prev]");
    var next = root.querySelector("[data-next]");
    var current = root.querySelector("[data-current]");
    var strip = root.querySelector("[data-strip]");
    var index = 0;

    var thumbs = frames.map(function (frame, i) {
      var img = frame.querySelector("img");
      var label = frame.querySelector(".process__label");
      var li = document.createElement("li");
      var btn = document.createElement("button");
      btn.type = "button";
      btn.setAttribute("aria-label", "Stage " + (i + 1) + (label ? ": " + label.textContent.trim() : ""));
      var thumb = document.createElement("img");
      thumb.src = img.currentSrc || img.src;
      thumb.alt = "";
      thumb.loading = "lazy";
      btn.appendChild(thumb);
      btn.appendChild(document.createElement("span"));
      btn.addEventListener("click", function () { show(i); });
      li.appendChild(btn);
      strip.appendChild(li);
      return btn;
    });

    function show(i) {
      index = Math.max(0, Math.min(frames.length - 1, i));
      frames.forEach(function (f, n) {
        f.classList.toggle("is-active", n === index);
        f.setAttribute("aria-hidden", n === index ? "false" : "true");
      });
      thumbs.forEach(function (t, n) {
        if (n === index) t.setAttribute("aria-current", "step");
        else t.removeAttribute("aria-current");
      });
      var info = frames[index].querySelector(".process__info");
      caption.innerHTML = info ? info.outerHTML : "";
      range.value = String(index);
      current.textContent = String(index + 1);
      prev.disabled = index === 0;
      next.disabled = index === frames.length - 1;
    }

    // Load every stage up front so switching is instant.
    frames.forEach(function (f) { f.querySelector("img").loading = "eager"; });

    range.addEventListener("input", function () { show(parseInt(range.value, 10)); });
    prev.addEventListener("click", function () { show(index - 1); });
    next.addEventListener("click", function () { show(index + 1); });
    root.addEventListener("keydown", function (e) {
      if (e.target === range) return; // the slider handles its own arrow keys
      if (e.key === "ArrowLeft") { show(index - 1); e.preventDefault(); }
      if (e.key === "ArrowRight") { show(index + 1); e.preventDefault(); }
    });

    root.classList.add("is-ready");
    panel.hidden = false;
    show(0);
  }

  Array.prototype.forEach.call(document.querySelectorAll("[data-process]"), initProcess);

  /* Lightbox: click an artwork to see it large. ------------------------- */

  var dialog = document.querySelector("[data-lightbox]");
  if (dialog && typeof dialog.showModal === "function") {
    var lbImg = dialog.querySelector("[data-lightbox-img]");
    var lbCap = dialog.querySelector("[data-lightbox-caption]");

    document.addEventListener("click", function (e) {
      var link = e.target.closest("a[data-zoom]");
      if (!link || e.metaKey || e.ctrlKey || e.shiftKey) return;
      e.preventDefault();
      var inner = link.querySelector("img");
      lbImg.src = link.href;
      lbImg.alt = inner ? inner.alt : "";
      lbCap.textContent = link.getAttribute("data-caption") || "";
      dialog.showModal();
    });

    dialog.addEventListener("click", function (e) {
      if (e.target === dialog || e.target.closest(".lightbox__figure")) dialog.close();
    });
    dialog.addEventListener("close", function () { lbImg.removeAttribute("src"); });
  }

  /* Studio calendar: one square per day over the past year. ------------- */

  var cal = document.querySelector("[data-calendar]");
  if (cal) {
    var raw = [];
    try {
      raw = JSON.parse(cal.querySelector("[data-calendar-data]").textContent) || [];
    } catch (err) { raw = []; }

    var days = {};
    raw.forEach(function (item) {
      if (!item) return;
      (days[item.d] = days[item.d] || []).push(item);
    });

    var pad = function (n) { return (n < 10 ? "0" : "") + n; };
    var key = function (d) { return d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate()); };
    var months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

    var today = new Date();
    today.setHours(12, 0, 0, 0);
    // Start on the Monday 52 weeks before this week's Monday.
    var start = new Date(today);
    start.setDate(start.getDate() - ((start.getDay() + 6) % 7) - 52 * 7);

    var grid = cal.querySelector("[data-calendar-grid]");
    var frag = document.createDocumentFragment();
    var activeDays = 0;
    var col = 0;
    var lastMonth = -1;

    for (var d = new Date(start); d <= today || d.getDay() !== 1; d.setDate(d.getDate() + 1)) {
      var dow = (d.getDay() + 6) % 7; // Monday = 0
      if (dow === 0) {
        col++;
        // Skip a label in the first column when its month is almost over.
        if (col === 1 && d.getDate() > 21) lastMonth = d.getMonth();
        if (d.getMonth() !== lastMonth && d <= today) {
          var label = document.createElement("span");
          label.className = "calendar__month";
          label.style.gridColumn = String(col);
          label.textContent = months[d.getMonth()];
          frag.appendChild(label);
          lastMonth = d.getMonth();
        }
      }

      var items = days[key(d)] || [];
      var cell;
      if (d > today) {
        cell = document.createElement("i");
        cell.className = "is-empty";
      } else if (items.length) {
        activeDays++;
        cell = document.createElement("a");
        cell.href = items[0].u;
        cell.className = "l" + Math.min(items.length, 3);
        cell.title = d.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" }) +
          " — " + items.map(function (x) { return x.t; }).join("; ");
      } else {
        cell = document.createElement("i");
      }
      cell.style.gridColumn = String(col);
      cell.style.gridRow = String(dow + 2);
      frag.appendChild(cell);
    }
    grid.appendChild(frag);

    var summary = cal.querySelector("[data-calendar-summary]");
    summary.innerHTML = "<strong>" + activeDays + "</strong> recorded studio day" +
      (activeDays === 1 ? "" : "s") + " in the past twelve months.";

    var scroller = cal.querySelector("[data-calendar-scroll]");
    scroller.scrollLeft = scroller.scrollWidth;
  }
})();
