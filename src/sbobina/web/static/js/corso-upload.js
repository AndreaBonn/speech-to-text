// sbobina · course materials upload: file picker, drag and drop, progress
// and error message. The server's message reaches the DOM via textContent.
(function () {
  "use strict";

  var dropzone = document.getElementById("materials-dropzone");
  var dropzoneInput = document.getElementById("materials-dropzone-input");
  var fileError = document.getElementById("materials-file-error");
  var progressWrap = document.getElementById("materials-upload-progress");
  var progressBar = document.getElementById("materials-upload-bar");
  var progressRole = progressWrap.querySelector("[role=progressbar]");
  var hooks = null;

  function apiBase(key) {
    return "/api/v1/courses/" + encodeURIComponent(key) + "/documents";
  }

  function resetUploadError() {
    fileError.hidden = true;
    fileError.textContent = "";
    dropzone.classList.remove("dropzone--invalid");
  }

  function showUploadError(message) {
    fileError.hidden = false;
    fileError.textContent = message;
    dropzone.classList.add("dropzone--invalid");
  }

  function setUploadProgress(fraction) {
    progressBar.style.transform = "scaleX(" + fraction + ")";
    progressRole.setAttribute("aria-valuenow", String(Math.round(fraction * 100)));
  }

  function uploadFile(key, file) {
    resetUploadError();
    progressWrap.hidden = false;
    setUploadProgress(0);

    var formData = new FormData();
    formData.append("file", file);

    var xhr = new XMLHttpRequest();
    xhr.open("POST", apiBase(key));
    xhr.upload.addEventListener("progress", function (event) {
      if (event.lengthComputable) {
        setUploadProgress(event.loaded / event.total);
      }
    });
    xhr.addEventListener("load", function () {
      progressWrap.hidden = true;
      dropzoneInput.value = "";
      if (xhr.status === 202) {
        hooks.onUploaded(key);
        return;
      }
      var message = "Caricamento non riuscito.";
      try {
        var body = JSON.parse(xhr.responseText);
        if (body && body.error && body.error.message) {
          message = body.error.message;
        }
      } catch (error) {
        // Keep the generic message: the response was not a JSON envelope.
      }
      showUploadError(message);
    });
    xhr.addEventListener("error", function () {
      progressWrap.hidden = true;
      showUploadError("Caricamento non riuscito: verifica la connessione.");
    });
    xhr.send(formData);
  }

  function fileFromEvent(fileList) {
    return fileList && fileList.length > 0 ? fileList[0] : null;
  }

  function bind(courseHooks) {
    hooks = courseHooks;
    dropzoneInput.addEventListener("change", function () {
      var file = fileFromEvent(dropzoneInput.files);
      if (file && hooks.currentKey() !== null) {
        uploadFile(hooks.currentKey(), file);
      }
    });

    ["dragenter", "dragover"].forEach(function (eventName) {
      dropzone.addEventListener(eventName, function (event) {
        event.preventDefault();
        dropzone.classList.add("dropzone--dragover");
      });
    });
    ["dragleave", "dragend"].forEach(function (eventName) {
      dropzone.addEventListener(eventName, function () {
        dropzone.classList.remove("dropzone--dragover");
      });
    });
    dropzone.addEventListener("drop", function (event) {
      event.preventDefault();
      dropzone.classList.remove("dropzone--dragover");
      var file = fileFromEvent(event.dataTransfer.files);
      if (file && hooks.currentKey() !== null) {
        dropzoneInput.files = event.dataTransfer.files;
        uploadFile(hooks.currentKey(), file);
      }
    });
  }

  window.SbobinaCourseUpload = { bind: bind };
})();
