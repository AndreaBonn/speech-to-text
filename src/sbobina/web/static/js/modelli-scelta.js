// sbobina · Whisper models page (M1): which models stay in view. Lectures are
// Italian, so the recommended models and the one in use come first; the
// others fold away, with the English-only ones (".en") last.
(function () {
  "use strict";

  var ENGLISH_ONLY_SUFFIX = ".en";

  function isEnglishOnly(model) {
    return model.name.slice(-ENGLISH_ONLY_SUFFIX.length) === ENGLISH_ONLY_SUFFIX;
  }

  function isActive(model, activeName) {
    return Boolean(activeName) && (model.name === activeName || model.aliases.indexOf(activeName) !== -1);
  }

  function split(models, activeName) {
    var primary = [];
    var multilingual = [];
    var english = [];
    models.forEach(function (model) {
      if (model.recommended_gpu || model.recommended_cpu || isActive(model, activeName)) {
        primary.push(model);
      } else if (isEnglishOnly(model)) {
        english.push(model);
      } else {
        multilingual.push(model);
      }
    });
    return { primary: primary, others: multilingual.concat(english) };
  }

  window.SbobinaModelChoice = { split: split, isEnglishOnly: isEnglishOnly, isActive: isActive };
})();
