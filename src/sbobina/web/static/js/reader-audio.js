// sbobina · reader audio bar: play/pause, ±10 s, speed, seek slider and the
// time callback that drives the word highlight. Split out of reader.js (T082).
// An imported lecture has no audio (no <audio> in the page): then seeking
// only moves the text to that point, so links and word clicks still work.
(function () {
  "use strict";

  var SEEK_STEPS = 1000;
  var SKIP_SECONDS = 10;

  // No audio file: "seek" just moves the text to that time.
  function textOnly(options) {
    function noop() {}
    return { seekTo: options.onTime, seekAndPlay: options.onTime, show: noop, hide: noop };
  }

  // options: { formatTime(s), onTime(s), showStatus(message, kind) }
  function attach(options) {
    var player = document.getElementById("audio-player");
    if (!player) {
      return textOnly(options);
    }
    var bar = document.getElementById("audio-bar");
    var state = { dragging: false };
    wireTransport(player, options);
    wireSeek(player, state);
    wireTime(player, state, options);
    wireError(player, bar, options);
    return {
      seekTo: function (seconds) {
        player.currentTime = clampTime(player, seconds);
      },
      seekAndPlay: function (seconds) {
        seekAndPlay(player, seconds);
      },
      show: function () {
        bar.hidden = false;
      },
      hide: function () {
        bar.hidden = true;
      },
    };
  }

  function wireError(player, bar, options) {
    player.addEventListener("error", function () {
      options.showStatus(
        "Impossibile decodificare l'audio di questa lezione. Il testo resta leggibile.",
        "danger"
      );
      bar.hidden = true;
    });
  }

  function clampTime(player, seconds) {
    var duration = isFinite(player.duration) ? player.duration : seconds;
    return Math.max(0, Math.min(seconds, duration));
  }

  function seekAndPlay(player, seconds) {
    player.currentTime = clampTime(player, seconds);
    player.play().catch(function () {
      // Autoplay can still be refused by the browser; the transport stays
      // paused and the user can press play again.
    });
  }

  function wireTransport(player, options) {
    var playButton = document.getElementById("audio-playpause");
    var playIcon = document.getElementById("audio-playpause-icon");
    var speedSelect = document.getElementById("audio-speed");
    function updatePlayIcon() {
      playIcon.innerHTML = player.paused ? "&#9654;" : "&#10073;&#10073;";
      playButton.setAttribute("aria-label", player.paused ? "Riproduci" : "Metti in pausa");
    }
    playButton.addEventListener("click", function () {
      if (!player.paused) {
        player.pause();
        return;
      }
      player.play().catch(function () {
        options.showStatus("Impossibile avviare la riproduzione.", "warning");
      });
    });
    document.getElementById("audio-back").addEventListener("click", function () {
      seekAndPlay(player, player.currentTime - SKIP_SECONDS);
    });
    document.getElementById("audio-forward").addEventListener("click", function () {
      seekAndPlay(player, player.currentTime + SKIP_SECONDS);
    });
    speedSelect.addEventListener("change", function () {
      player.playbackRate = parseFloat(speedSelect.value) || 1;
    });
    player.addEventListener("play", updatePlayIcon);
    player.addEventListener("pause", updatePlayIcon);
  }

  function wireSeek(player, state) {
    var seekInput = document.getElementById("audio-seek");
    seekInput.addEventListener("input", function () {
      state.dragging = true;
      if (isFinite(player.duration)) {
        player.currentTime = (seekInput.value / SEEK_STEPS) * player.duration;
      }
    });
    seekInput.addEventListener("change", function () {
      state.dragging = false;
    });
  }

  function wireTime(player, state, options) {
    var seekInput = document.getElementById("audio-seek");
    var timeEl = document.getElementById("audio-time");
    player.addEventListener("loadedmetadata", function () {
      timeEl.textContent = options.formatTime(0) + " / " + options.formatTime(player.duration);
    });
    player.addEventListener("timeupdate", function () {
      if (!state.dragging && isFinite(player.duration) && player.duration > 0) {
        seekInput.value = String(Math.round((player.currentTime / player.duration) * SEEK_STEPS));
      }
      timeEl.textContent =
        options.formatTime(player.currentTime) + " / " + options.formatTime(player.duration || 0);
      options.onTime(player.currentTime);
    });
  }

  window.SbobinaReaderAudio = { attach: attach };
})();
