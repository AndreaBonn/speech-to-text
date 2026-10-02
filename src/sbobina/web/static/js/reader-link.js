// sbobina · reader deep link: /lettore/<id>?t=<seconds>&variant=<v> opens the
// requested text version, moves the audio to t and marks the word spoken
// there. Search results and study-note citations land here. A bad t or
// variant is ignored: the reader then behaves as if opened without them.
(function () {
  "use strict";

  var VARIANTS = ["original", "corrected"];
  var TARGET_CLASS = "word--target";

  var root = document.querySelector(".reader[data-job-id]");
  var player = document.getElementById("audio-player");
  if (!root || !player || !window.sbobinaReader) {
    return;
  }
  var reader = window.sbobinaReader;
  var params = new URLSearchParams(window.location.search);
  var target = parseTime(params.get("t"));
  var variant = VARIANTS.indexOf(params.get("variant")) >= 0 ? params.get("variant") : null;
  if (target === null && variant === null) {
    return;
  }

  function parseTime(raw) {
    if (raw === null || raw.trim() === "") {
      return null;
    }
    var seconds = Number(raw);
    return isFinite(seconds) && seconds >= 0 ? seconds : null;
  }

  function nearestWord(seconds) {
    var best = null;
    var bestDistance = Infinity;
    root.querySelectorAll(".word[data-start]").forEach(function (span) {
      var distance = Math.abs(parseFloat(span.dataset.start) - seconds);
      if (distance < bestDistance) {
        best = span;
        bestDistance = distance;
      }
    });
    return best;
  }

  function markWord(seconds) {
    root.querySelectorAll("." + TARGET_CLASS).forEach(function (span) {
      span.classList.remove(TARGET_CLASS);
    });
    var span = nearestWord(seconds);
    if (span) {
      span.classList.add(TARGET_CLASS);
      span.scrollIntoView({ block: "center" });
    }
  }

  function landWhenReady(seconds) {
    function land() {
      // Past the end means the link no longer matches this audio: ignore it.
      if (seconds <= player.duration) {
        markWord(seconds);
        reader.seekTo(seconds);
      }
    }
    if (player.readyState >= HTMLMediaElement.HAVE_METADATA) {
      land();
    } else {
      player.addEventListener("loadedmetadata", land, { once: true });
      // Undecodable audio never sends metadata: still point at the text.
      player.addEventListener("error", function () {
        markWord(seconds);
      }, { once: true });
    }
  }

  function land() {
    if (target !== null) {
      landWhenReady(target);
    }
  }

  function onFirstLoad(event) {
    root.removeEventListener("reader:variant", onFirstLoad);
    if (variant && variant !== event.detail.variant) {
      reader.showCorrectedControls();
      reader.switchVariant(variant).then(land, function () {
        // switchVariant already showed the error; the original stays readable.
      });
      return;
    }
    land();
  }

  root.addEventListener("reader:variant", onFirstLoad);
})();
