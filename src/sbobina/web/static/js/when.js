// sbobina · short, readable dates for lists: "oggi, 16:03", "ieri, 09:12",
// "gio 02/10, 16:03", "02/10/2025, 16:03". Seconds and the current year are
// noise in a list of lectures; the full timestamp stays in the title attribute.
(function () {
  "use strict";

  var WEEKDAYS = ["dom", "lun", "mar", "mer", "gio", "ven", "sab"];
  var DAY_MS = 24 * 60 * 60 * 1000;

  function pad(value) {
    return value < 10 ? "0" + value : String(value);
  }

  function startOfDay(date) {
    return new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime();
  }

  function dayMonth(date) {
    return pad(date.getDate()) + "/" + pad(date.getMonth() + 1);
  }

  function formatDay(iso, now) {
    var date = new Date(iso);
    var reference = now || new Date();
    var diff = Math.round((startOfDay(reference) - startOfDay(date)) / DAY_MS);
    if (diff === 0) {
      return "oggi";
    }
    if (diff === 1) {
      return "ieri";
    }
    if (date.getFullYear() === reference.getFullYear()) {
      return WEEKDAYS[date.getDay()] + " " + dayMonth(date);
    }
    return dayMonth(date) + "/" + date.getFullYear();
  }

  function format(iso, now) {
    var date = new Date(iso);
    return formatDay(iso, now) + ", " + pad(date.getHours()) + ":" + pad(date.getMinutes());
  }

  function full(iso) {
    return new Date(iso).toLocaleString("it-IT");
  }

  window.SbobinaWhen = { format: format, formatDay: formatDay, full: full };
})();
