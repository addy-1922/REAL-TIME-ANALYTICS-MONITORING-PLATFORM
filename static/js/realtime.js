(() => {
  "use strict";

  const body = document.body;
  const MAX_DROPDOWN_ITEMS = 6;

  const resolveSocketURL = (path) => {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    return `${protocol}//${window.location.host}${path}`;
  };

  const statusLabels = {
    connecting: "Connecting",
    online: "Live",
    offline: "Offline",
    reconnecting: "Reconnecting",
  };

  const setConnectionStatus = (kind, state, detail) => {
    document.querySelectorAll(`[data-connection-dot="${kind}"]`).forEach((dot) => {
      dot.classList.remove("is-connecting", "is-online", "is-offline");
      dot.classList.add(`is-${state}`);
    });
    document.querySelectorAll(`[data-connection-status="${kind}"]`).forEach((element) => {
      element.textContent = detail || statusLabels[state] || state;
    });
  };

  class RealtimeConnection {
    constructor({ path, kind, onMessage }) {
      this.path = path;
      this.kind = kind;
      this.onMessage = onMessage;
      this.socket = null;
      this.attempt = 0;
      this.reconnectTimer = null;
      this.shouldRun = true;
    }

    start() {
      this.shouldRun = true;
      this.open();
    }

    open() {
      if (!this.shouldRun || typeof WebSocket === "undefined") return;
      window.clearTimeout(this.reconnectTimer);
      setConnectionStatus(this.kind, this.attempt === 0 ? "connecting" : "reconnecting");
      let socket;
      try {
        socket = new WebSocket(resolveSocketURL(this.path));
      } catch (error) {
        void error;
        this.scheduleReconnect();
        return;
      }
      this.socket = socket;
      socket.addEventListener("open", () => {
        this.attempt = 0;
        setConnectionStatus(this.kind, "online");
      });
      socket.addEventListener("message", (event) => {
        let payload;
        try {
          payload = JSON.parse(event.data);
        } catch (error) {
          void error;
          return;
        }
        this.onMessage(payload);
      });
      socket.addEventListener("close", () => {
        this.socket = null;
        if (this.shouldRun) {
          setConnectionStatus(this.kind, "offline", "Reconnecting");
          this.scheduleReconnect();
        }
      });
      socket.addEventListener("error", () => {
        setConnectionStatus(this.kind, "offline", "Connection issue");
      });
    }

    scheduleReconnect() {
      if (!this.shouldRun) return;
      this.attempt += 1;
      const base = Math.min(30000, 1000 * 2 ** Math.min(this.attempt - 1, 5));
      const delay = base + Math.random() * Math.min(1500, base * 0.3);
      this.reconnectTimer = window.setTimeout(() => this.open(), delay);
    }

    stop() {
      this.shouldRun = false;
      window.clearTimeout(this.reconnectTimer);
      if (this.socket) {
        this.socket.close();
        this.socket = null;
      }
    }
  }

  const getUnreadCount = () => {
    const element = document.querySelector("[data-unread-notification-count]");
    const parsed = Number(element?.textContent?.trim());
    return Number.isFinite(parsed) ? parsed : 0;
  };

  const setUnreadCount = (count) => {
    document.querySelectorAll("[data-unread-notification-count]").forEach((element) => {
      element.textContent = count > 99 ? "99+" : String(count);
      element.classList.toggle("is-empty", count === 0);
    });
  };

  const relativeTime = (isoString) => {
    const date = new Date(isoString);
    if (Number.isNaN(date.getTime())) return "";
    const seconds = Math.round((Date.now() - date.getTime()) / 1000);
    if (seconds < 60) return "just now";
    const minutes = Math.round(seconds / 60);
    if (minutes < 60) return `${minutes}m ago`;
    const hours = Math.round(minutes / 60);
    if (hours < 24) return `${hours}h ago`;
    return `${Math.round(hours / 24)}d ago`;
  };

  const buildNotificationItem = (notification, historyUrl) => {
    const article = document.createElement("article");
    article.className = `notification-item${notification.is_read ? "" : " is-unread"}`;
    article.dataset.notificationItem = "";
    const indicator = document.createElement("span");
    indicator.className = "notification-item__indicator";
    indicator.setAttribute("aria-hidden", "true");
    const link = document.createElement("a");
    link.href = notification.id ? `${historyUrl}#notification-${notification.id}` : historyUrl;
    const title = document.createElement("strong");
    title.textContent = notification.title || "Notification";
    const message = document.createElement("span");
    message.textContent = notification.message || "";
    const time = document.createElement("time");
    const created = notification.created_at || "";
    if (created && !Number.isNaN(new Date(created).getTime())) time.setAttribute("datetime", new Date(created).toISOString());
    time.textContent = relativeTime(created);
    link.append(title, message, time);
    article.append(indicator, link);
    return article;
  };

  const historyBaseURL = () => {
    const feed = document.querySelector("[data-notification-feed]");
    const declared = feed?.dataset.notificationHistoryUrl;
    if (declared) return declared;
    const headerLink = document.querySelector(".dropdown-panel--notifications .dropdown-panel__header a");
    return headerLink ? headerLink.href.replace(/#.*$/, "") : "/notifications/";
  };

  const handleNotification = (notification) => {
    if (!notification || typeof notification !== "object") return;
    const feed = document.querySelector("[data-notification-feed]");
    if (feed) {
      const historyUrl = historyBaseURL();
      const item = buildNotificationItem(notification, historyUrl);
      feed.querySelector("[data-notification-empty]")?.remove();
      feed.prepend(item);
      while (feed.querySelectorAll("[data-notification-item]").length > MAX_DROPDOWN_ITEMS) {
        feed.querySelector("[data-notification-item]:last-of-type")?.remove();
      }
    }
    if (!notification.is_read) {
      setUnreadCount(getUnreadCount() + 1);
    }
    const type = String(notification.notification_type || "info").toLowerCase();
    const toastType = type.includes("error") || type.includes("critical") ? "error" : type.includes("warn") ? "warning" : type.includes("success") ? "success" : "info";
    window.SignalWatch?.showToast?.(notification.title || "New notification", toastType);
  };

  const handleProjectEvent = (message) => {
    if (!message || typeof message !== "object") return;
    const event = message.payload && typeof message.payload === "object" ? message.payload : message;
    window.dispatchEvent(new CustomEvent("signalwatch:event", { detail: event }));
  };

  const startConnections = () => {
    if (body.dataset.authenticated !== "true") return;
    const connections = [];

    const projectHolder = document.querySelector("[data-realtime-project-id]");
    const projectId = projectHolder?.dataset.realtimeProjectId?.trim();
    if (projectId) {
      connections.push(new RealtimeConnection({
        path: `/ws/projects/${encodeURIComponent(projectId)}/stream/`,
        kind: "project",
        onMessage: handleProjectEvent,
      }));
    }

    const notificationPath = body.dataset.notificationWebsocket;
    if (notificationPath) {
      connections.push(new RealtimeConnection({
        path: notificationPath,
        kind: "notification",
        onMessage: handleNotification,
      }));
    }

    connections.forEach((connection) => connection.start());
    window.addEventListener("beforeunload", () => connections.forEach((connection) => connection.stop()));

    document.addEventListener("visibilitychange", () => {
      connections.forEach((connection) => {
        if (document.hidden) {
          connection.stop();
        } else if (!connection.shouldRun || connection.socket === null) {
          connection.attempt = 0;
          connection.start();
        }
      });
    });
  };

  startConnections();
})();
