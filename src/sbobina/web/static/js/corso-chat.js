// sbobina · course chat: conversation list. Thread rendering and the
// question form live in corso-chat-thread.js (split to stay under the file
// size limit). Everything from the API reaches the DOM only via textContent
// (see dom.js), never innerHTML.
(function () {
  "use strict";

  var dom = window.SbobinaDom;
  var clearChildren = dom.clearChildren;
  var clearStatus = dom.clearStatus;
  var showRetryStatus = dom.showRetryStatus;
  var detail = window.SbobinaGenerationDetail;
  var el = detail.el;
  var thread = window.SbobinaCourseChatThread;

  var newButton = document.getElementById("chat-new");
  var emptyNewButton = document.getElementById("chat-empty-new");
  var listStatusEl = document.getElementById("chat-list-status");
  var listEl = document.getElementById("chat-list");
  var emptyEl = document.getElementById("chat-list-empty");

  var currentKey = null;
  var currentChatId = null;
  var chats = [];

  function apiBase(key) {
    return "/api/v1/courses/" + encodeURIComponent(key) + "/chats";
  }

  function chatTitle(chat) {
    return chat.title || "Nuova conversazione";
  }

  function formatDate(iso) {
    return window.SbobinaWhen.format(iso);
  }

  function onMessageSent() {
    if (currentKey !== null) {
      loadList(currentKey);
    }
  }

  function openChat(key, chatId) {
    currentChatId = chatId;
    renderChatList(key, chats);
    thread.load(key, chatId, onMessageSent);
  }

  // ---------- conversation list ----------

  function renderChatListItem(key, chat) {
    var li = el("li", "chat__list-item");
    var openButton = el("button", "btn btn--ghost chat__list-item-open");
    openButton.type = "button";
    if (chat.id === currentChatId) {
      li.classList.add("is-active");
      openButton.setAttribute("aria-current", "true");
    }
    openButton.appendChild(el("span", "chat__list-item-title", chatTitle(chat)));
    openButton.appendChild(el("span", "chat__list-item-date", formatDate(chat.created_at)));
    openButton.addEventListener("click", function () {
      openChat(key, chat.id);
    });
    li.appendChild(openButton);

    var deleteButton = el("button", "btn btn--danger chat__list-item-delete", "Elimina");
    deleteButton.type = "button";
    deleteButton.addEventListener("click", function () {
      if (window.confirm("Eliminare questa conversazione? L'operazione non si può annullare.")) {
        deleteChat(key, chat.id);
      }
    });
    li.appendChild(deleteButton);
    return li;
  }

  function renderChatList(key, items) {
    chats = items;
    clearChildren(listEl);
    if (items.length === 0) {
      listEl.hidden = true;
      emptyEl.hidden = false;
      return;
    }
    emptyEl.hidden = true;
    listEl.hidden = false;
    items.forEach(function (chat) {
      listEl.appendChild(renderChatListItem(key, chat));
    });
  }

  function loadList(key) {
    clearStatus(listStatusEl);
    fetch(apiBase(key) + "?page=1&per_page=50")
      .then(function (response) {
        if (!response.ok) {
          throw new Error("chats fetch failed");
        }
        return response.json();
      })
      .then(function (body) {
        if (key === currentKey) {
          renderChatList(key, body.data);
        }
      })
      .catch(function () {
        if (key !== currentKey) {
          return;
        }
        clearChildren(listEl);
        listEl.hidden = true;
        showRetryStatus(listStatusEl, "Impossibile caricare le conversazioni.", function () {
          loadList(key);
        });
      });
  }

  function createChat(key) {
    fetch(apiBase(key), { method: "POST" })
      .then(function (response) {
        if (!response.ok) {
          throw new Error("create chat failed");
        }
        return response.json();
      })
      .then(function (body) {
        loadList(key);
        openChat(key, body.data.id);
      })
      .catch(function () {
        showRetryStatus(listStatusEl, "Impossibile creare la conversazione.", function () {
          createChat(key);
        });
      });
  }

  function deleteChat(key, chatId) {
    fetch(apiBase(key) + "/" + encodeURIComponent(chatId), { method: "DELETE" })
      .then(function (response) {
        if (!response.ok && response.status !== 204) {
          throw new Error("delete chat failed");
        }
        if (chatId === currentChatId) {
          currentChatId = null;
          thread.clear();
        }
        loadList(key);
      })
      .catch(function () {
        showRetryStatus(listStatusEl, "Impossibile eliminare la conversazione.", function () {
          deleteChat(key, chatId);
        });
      });
  }

  newButton.addEventListener("click", function () {
    if (currentKey !== null) {
      createChat(currentKey);
    }
  });
  emptyNewButton.addEventListener("click", function () {
    if (currentKey !== null) {
      createChat(currentKey);
    }
  });

  // ---------- public API ----------

  function show(key) {
    currentKey = key;
    currentChatId = null;
    thread.clear();
    loadList(key);
  }

  function hide() {
    currentKey = null;
    currentChatId = null;
    thread.clear();
    clearChildren(listEl);
  }

  window.SbobinaCourseChat = { show: show, hide: hide };
})();
