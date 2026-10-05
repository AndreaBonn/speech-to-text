// sbobina · course detail: DOM builders of the "Frasi da esame" list (lecture
// groups, cue rows, skeleton, empty and unavailable texts). Split out of
// corso-frasi-esame.js to keep its fetch logic under the size limits. Quotes
// come from the transcript, so they reach the DOM only via textContent.
(function () {
  "use strict";

  var dom = window.SbobinaDom;
  if (!dom) {
    return;
  }

  var ALL_LEVELS = "all";
  var LEVEL_LABELS = { strong: "forte", weak: "debole" };
  var SKELETON_ROWS = 3;

  function levelBadge(level) {
    var badge = document.createElement("span");
    badge.className = "badge badge--" + level;
    badge.textContent = LEVEL_LABELS[level] || level;
    return badge;
  }

  // job_id/segment_index/quote/revision as data-*: exam-cue-cards.js reads
  // them via event delegation and never fetches the cues itself.
  function cardButton(cue) {
    var button = document.createElement("button");
    button.type = "button";
    button.className = "btn btn--ghost examcues__card-btn";
    button.textContent = "Crea carta";
    button.dataset.jobId = cue.job_id;
    button.dataset.segmentIndex = cue.segment_index;
    button.dataset.quote = cue.quote;
    button.dataset.revision = cue.revision || "";
    return button;
  }

  function cueNode(cue) {
    var li = document.createElement("li");
    li.className = "examcues__cue";
    var link = document.createElement("a");
    link.className = "table__link examcues__time";
    link.href = cue.href;
    link.textContent = dom.formatTime(cue.start);
    link.setAttribute("aria-label", "Ascolta da " + dom.formatTime(cue.start));
    li.appendChild(link);
    li.appendChild(levelBadge(cue.level));
    var quote = document.createElement("p");
    quote.className = "examcues__quote";
    quote.textContent = cue.quote;
    li.appendChild(quote);
    // The quote alone ("e all'esame") may not say what will be asked.
    if (cue.followup) {
      var followup = document.createElement("p");
      followup.className = "examcues__followup";
      followup.textContent = "Segue: «" + cue.followup + "»";
      li.appendChild(followup);
    }
    li.appendChild(cardButton(cue));
    return li;
  }

  function groupNode(title, cues) {
    var group = document.createElement("li");
    group.className = "examcues__group";
    var heading = document.createElement("h4");
    heading.className = "examcues__group-title";
    heading.textContent = title;
    group.appendChild(heading);
    var cuesList = document.createElement("ul");
    cuesList.className = "examcues__cues";
    cues.forEach(function (cue) {
      cuesList.appendChild(cueNode(cue));
    });
    group.appendChild(cuesList);
    return group;
  }

  // Cues arrive ordered by lecture; one group per lecture, in arrival order.
  function renderGroups(listEl, data, titleOf) {
    dom.clearChildren(listEl);
    var order = [];
    var byJob = {};
    data.forEach(function (cue) {
      if (!byJob[cue.job_id]) {
        byJob[cue.job_id] = [];
        order.push(cue.job_id);
      }
      byJob[cue.job_id].push(cue);
    });
    order.forEach(function (jobId) {
      listEl.appendChild(groupNode(titleOf(jobId), byJob[jobId]));
    });
  }

  function showSkeleton(listEl) {
    dom.clearChildren(listEl);
    listEl.hidden = false;
    for (var i = 0; i < SKELETON_ROWS; i++) {
      var li = document.createElement("li");
      li.className = "examcues__skeleton skeleton-row";
      listEl.appendChild(li);
    }
  }

  function unavailableCount(meta) {
    return (meta && meta.unavailable_jobs ? meta.unavailable_jobs : []).length;
  }

  function emptyMessage(level, meta) {
    // With unreadable lectures, "no cues" is only true of the readable ones.
    if (unavailableCount(meta) > 0) {
      return (
        "Nelle lezioni che riesco a leggere non trovo frasi in cui il docente " +
        "parla dell'esame. Le altre non sono leggibili ora." +
        (level === ALL_LEVELS ? "" : " Con i segnali deboli attivi se ne vedono di più.")
      );
    }
    if (level === ALL_LEVELS) {
      return (
        "In queste lezioni non trovo frasi in cui il docente parla " +
        "dell'esame, nemmeno fra i segnali deboli (per esempio «importante», " +
        "«attenzione»)."
      );
    }
    return (
      "In queste lezioni non trovo frasi in cui il docente parla " +
      "chiaramente dell'esame (per esempio «all'esame vi chiederò» o " +
      "«ricordatevi»). Con i segnali deboli attivi se ne vedono di più, " +
      "anche se meno affidabili."
    );
  }

  // Lessons the server could not read are listed in meta, not silently dropped.
  function showUnavailable(unavailableEl, meta) {
    var count = unavailableCount(meta);
    unavailableEl.hidden = count === 0;
    unavailableEl.textContent = count === 1
      ? "Una lezione non è leggibile ora: le sue frasi non compaiono."
      : count + " lezioni non sono leggibili ora: le loro frasi non compaiono.";
  }

  window.SbobinaExamCueRender = {
    renderGroups: renderGroups,
    showSkeleton: showSkeleton,
    emptyMessage: emptyMessage,
    showUnavailable: showUnavailable,
  };
})();
