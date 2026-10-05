// sbobina · reader "punti da riascoltare": one button per uncertain passage,
// with its time and the doubtful words marked. Split out of reader.js (F59).
// Transcript text reaches the DOM via textContent only.
(function () {
  "use strict";

  function pointButton(point, formatTime) {
    var button = document.createElement("button");
    button.type = "button";
    button.className = "reader__point";
    button.dataset.start = String(point.start);
    var time = document.createElement("span");
    time.className = "reader__point-time";
    time.textContent = formatTime(point.start);
    var text = document.createElement("span");
    text.className = "reader__point-text";
    var marked = document.createElement("mark");
    marked.textContent = point.text;
    text.append(point.before ? point.before + " " : "", marked, point.after ? " " + point.after : "");
    button.append(time, text);
    return button;
  }

  function render(container, points, formatTime) {
    if (points.length === 0) {
      var empty = document.createElement("p");
      empty.className = "reader__points-empty";
      empty.textContent = "Nessun punto incerto da riascoltare.";
      container.replaceChildren(empty);
      return;
    }
    var list = document.createElement("ul");
    list.className = "reader__points-list";
    points.forEach(function (point) {
      var li = document.createElement("li");
      li.appendChild(pointButton(point, formatTime));
      list.appendChild(li);
    });
    container.replaceChildren(list);
  }

  window.SbobinaReaderPoints = { render: render };
})();
