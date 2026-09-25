(() => {
  "use strict";

  const root = document.documentElement;
  const body = document.body;
  const themeStorageKey = "signalwatch-theme";
  const themeQuery = window.matchMedia("(prefers-color-scheme: dark)");

  const getCookie = (name) => {
    const prefix = `${encodeURIComponent(name)}=`;
    const part = document.cookie.split(";").map((value) => value.trim()).find((value) => value.startsWith(prefix));
    return part ? decodeURIComponent(part.slice(prefix.length)) : "";
  };

  const getCsrfToken = () => {
    const meta = document.querySelector('meta[name="csrf-token"]');
    if (meta && meta.content) return meta.content;
    const input = document.querySelector("input[name=csrfmiddlewaretoken]");
    if (input && input.value) return input.value;
    return getCookie("csrftoken");
  };

  const fetchJSON = async (url, options = {}) => {
    const requestOptions = { credentials: "same-origin", ...options };
    const method = String(requestOptions.method || "GET").toUpperCase();
    const headers = new Headers(requestOptions.headers || {});
    headers.set("Accept", "application/json");
    if (!["GET", "HEAD", "OPTIONS"].includes(method)) headers.set("X-CSRFToken", getCsrfToken());
    const isStructuredBody = requestOptions.body instanceof FormData || requestOptions.body instanceof URLSearchParams || requestOptions.body instanceof Blob || (typeof ReadableStream !== "undefined" && requestOptions.body instanceof ReadableStream) || typeof requestOptions.body === "string";
    if (requestOptions.body && !isStructuredBody && !(typeof ReadableStream !== "undefined" && requestOptions.body instanceof ReadableStream)) {
      headers.set("Content-Type", "application/json");
      requestOptions.body = JSON.stringify(requestOptions.body);
    }
    requestOptions.headers = headers;
    const response = await window.fetch(url, requestOptions);
    const contentType = response.headers.get("content-type") || "";
    const responseBody = contentType.includes("application/json") ? await response.json() : await response.text();
    if (!response.ok) {
      let message = `Request failed with status ${response.status}.`;
      if (responseBody && typeof responseBody === "object") {
        message = responseBody.detail || responseBody.message || responseBody.error?.message || message;
      } else if (typeof responseBody === "string" && responseBody.trim()) {
        message = responseBody;
      }
      const error = new Error(message);
      error.status = response.status;
      error.payload = responseBody;
      throw error;
    }
    return responseBody;
  };

  const postJSON = (url, data = {}, options = {}) => fetchJSON(url, { ...options, method: "POST", body: data });

  const iconForToast = (type) => {
    if (type === "success") return "✓";
    if (type === "error") return "!";
    if (type === "warning") return "!";
    return "i";
  };

  const dismissToast = (toast) => {
    if (!toast || toast.classList.contains("is-leaving")) return;
    toast.classList.add("is-leaving");
    window.setTimeout(() => toast.remove(), 190);
  };

  const showToast = (message, type = "info", timeout = 5000) => {
    const region = document.querySelector("[data-toast-region]");
    if (!region) return null;
    const allowedTypes = ["info", "success", "error", "warning"];
    const toastType = allowedTypes.includes(type) ? type : "info";
    const toast = document.createElement("div");
    toast.className = `toast toast--${toastType}`;
    toast.setAttribute("role", toastType === "error" ? "alert" : "status");
    toast.dataset.toast = "";
    const icon = document.createElement("span");
    icon.className = "toast__icon";
    icon.setAttribute("aria-hidden", "true");
    icon.textContent = iconForToast(toastType);
    const content = document.createElement("div");
    content.className = "toast__content";
    content.textContent = String(message || "The request was completed.");
    const close = document.createElement("button");
    close.className = "toast__close";
    close.type = "button";
    close.setAttribute("aria-label", "Dismiss notification");
    close.dataset.toastClose = "";
    close.textContent = "×";
    close.addEventListener("click", () => dismissToast(toast));
    toast.append(icon, content, close);
    region.append(toast);
    if (timeout > 0) window.setTimeout(() => dismissToast(toast), timeout);
    return toast;
  };

  const setupTheme = () => {
    const buttons = [...document.querySelectorAll("[data-theme-toggle]")];
    const applyTheme = (theme, persist = false) => {
      const normalized = theme === "dark" ? "dark" : "light";
      root.dataset.theme = normalized;
      document.querySelector('meta[name="theme-color"]')?.setAttribute("content", normalized === "dark" ? "#070b13" : "#ffffff");
      buttons.forEach((button) => {
        button.setAttribute("aria-pressed", normalized === "dark" ? "true" : "false");
        button.setAttribute("aria-label", normalized === "dark" ? "Use light theme" : "Use dark theme");
      });
      if (persist) {
        try {
          localStorage.setItem(themeStorageKey, normalized);
        } catch (error) {
          void error;
        }
      }
      window.dispatchEvent(new CustomEvent("signalwatch:themechange", { detail: { theme: normalized } }));
    };
    let storedTheme = "";
    try {
      storedTheme = localStorage.getItem(themeStorageKey) || "";
    } catch (error) {
      void error;
    }
    applyTheme(storedTheme || (themeQuery.matches ? "dark" : "light"));
    buttons.forEach((button) => button.addEventListener("click", () => applyTheme(root.dataset.theme === "dark" ? "light" : "dark", true)));
    themeQuery.addEventListener?.("change", (event) => {
      try {
        if (!localStorage.getItem(themeStorageKey)) applyTheme(event.matches ? "dark" : "light");
      } catch (error) {
        void error;
      }
    });
  };

  const setupSidebar = () => {
    const sidebar = document.querySelector("[data-sidebar]");
    const scrim = document.querySelector(".sidebar-scrim");
    const triggers = [...document.querySelectorAll("[data-sidebar-toggle]")];
    if (!sidebar) return;
    const setOpen = (open) => {
      sidebar.classList.toggle("is-open", open);
      scrim?.classList.toggle("is-visible", open);
      document.body.classList.toggle("sidebar-open", open);
      triggers.forEach((trigger) => {
        if (trigger.closest(".topbar")) trigger.setAttribute("aria-expanded", open ? "true" : "false");
      });
      if (open) sidebar.querySelector("a, button")?.focus({ preventScroll: true });
    };
    triggers.forEach((trigger) => trigger.addEventListener("click", () => setOpen(!sidebar.classList.contains("is-open"))));
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && sidebar.classList.contains("is-open")) setOpen(false);
    });
  };

  const setupDropdowns = () => {
    const triggers = [...document.querySelectorAll("[data-dropdown-toggle]")];
    const panels = [...document.querySelectorAll("[data-dropdown-panel]")];
    const closePanel = (panel) => {
      panel.hidden = true;
      const trigger = triggers.find((item) => item.getAttribute("data-dropdown-toggle") === panel.id);
      trigger?.setAttribute("aria-expanded", "false");
    };
    const closeAll = (exception = null) => panels.forEach((panel) => {
      if (panel !== exception) closePanel(panel);
    });
    triggers.forEach((trigger) => trigger.addEventListener("click", (event) => {
      event.stopPropagation();
      const panel = document.getElementById(trigger.getAttribute("data-dropdown-toggle"));
      if (!panel) return;
      const willOpen = panel.hidden;
      closeAll(panel);
      panel.hidden = !willOpen;
      trigger.setAttribute("aria-expanded", willOpen ? "true" : "false");
    }));
    panels.forEach((panel) => {
      panel.addEventListener("click", (event) => event.stopPropagation());
      panel.addEventListener("focusout", (event) => {
        if (!panel.contains(event.relatedTarget)) closePanel(panel);
      });
    });
    document.addEventListener("click", () => closeAll());
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") closeAll();
    });
  };

  const copyText = async (text) => {
    const value = String(text || "");
    if (!value) throw new Error("There is nothing to copy.");
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(value);
      return;
    }
    const field = document.createElement("textarea");
    field.value = value;
    field.setAttribute("readonly", "");
    field.style.position = "fixed";
    field.style.opacity = "0";
    field.style.pointerEvents = "none";
    document.body.append(field);
    field.select();
    const copied = document.execCommand("copy");
    field.remove();
    if (!copied) throw new Error("Copying is not available in this browser.");
  };

  const setupCopyButtons = () => {
    document.addEventListener("click", async (event) => {
      const button = event.target.closest("[data-copy-target], [data-copy-text], [data-copy-path]");
      if (!button) return;
      event.preventDefault();
      let value = button.dataset.copyText || "";
      const selector = button.dataset.copyTarget;
      if (selector) value = document.querySelector(selector)?.textContent || "";
      if (button.hasAttribute("data-copy-path")) value = window.location.href;
      try {
        await copyText(value);
        showToast("Copied to clipboard.", "success", 2800);
      } catch (error) {
        showToast(error.message || "Could not copy the value.", "error");
      }
    });
  };

  const setupConfirmDialog = () => {
    const dialog = document.querySelector("[data-confirm-dialog]");
    if (!dialog) return;
    const message = dialog.querySelector("[data-confirm-message]");
    const acceptButton = dialog.querySelector("[data-confirm-accept]");
    const cancelButton = dialog.querySelector("[data-confirm-cancel]");
    let pendingForm = null;
    const reset = () => {
      pendingForm = null;
      if (dialog.open) dialog.close();
    };
    document.addEventListener("submit", (event) => {
      const form = event.target;
      if (!(form instanceof HTMLFormElement) || !form.dataset.confirm || form.dataset.confirmBypass === "true") return;
      event.preventDefault();
      if (typeof dialog.showModal !== "function") {
        if (window.confirm(form.dataset.confirm)) {
          form.dataset.confirmBypass = "true";
          form.requestSubmit();
        }
        return;
      }
      pendingForm = form;
      message.textContent = form.dataset.confirm || "Are you sure you want to continue?";
      dialog.showModal();
    }, true);
    cancelButton?.addEventListener("click", reset);
    dialog.addEventListener("cancel", (event) => {
      event.preventDefault();
      reset();
    });
    acceptButton?.addEventListener("click", () => {
      if (!pendingForm) return reset();
      const form = pendingForm;
      form.dataset.confirmBypass = "true";
      pendingForm = null;
      if (dialog.open) dialog.close();
      form.requestSubmit();
    });
  };

  const setupLoadingForms = () => {
    document.addEventListener("submit", (event) => {
      if (event.defaultPrevented) return;
      const form = event.target;
      if (!(form instanceof HTMLFormElement) || !form.matches("[data-loading-form]")) return;
      form.classList.add("is-loading");
      const submitter = event.submitter;
      if (submitter instanceof HTMLButtonElement) submitter.disabled = true;
    });
  };

  const setupExistingToasts = () => {
    document.querySelectorAll("[data-toast]").forEach((toast) => {
      const close = toast.querySelector("[data-toast-close]");
      close?.addEventListener("click", () => dismissToast(toast));
      if (!toast.closest("[data-toast-region]")) window.setTimeout(() => dismissToast(toast), 6000);
    });
  };

  const setupHistoryBack = () => {
    document.querySelectorAll("[data-history-back]").forEach((button) => button.addEventListener("click", () => window.history.back()));
  };

  const setupReload = () => {
    document.querySelectorAll("[data-reload-page]").forEach((button) => button.addEventListener("click", () => window.location.reload()));
  };

  window.SignalWatch = Object.freeze({
    fetchJSON,
    getCsrfToken,
    postJSON,
    showToast,
  });

  setupTheme();
  setupSidebar();
  setupDropdowns();
  setupCopyButtons();
  setupConfirmDialog();
  setupLoadingForms();
  setupExistingToasts();
  setupHistoryBack();
  setupReload();
})();
