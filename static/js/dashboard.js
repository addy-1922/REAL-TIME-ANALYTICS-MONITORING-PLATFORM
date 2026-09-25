(() => {
  "use strict";

  const charts = new Map();
  const numberFormatter = new Intl.NumberFormat();
  const dateFormatter = new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
  const canvasCharts = new WeakMap();

  const numberValue = (value) => {
    if (value === null || value === undefined || value === "") return null;
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  };

  const readJSON = (selector) => {
    const element = document.querySelector(selector);
    if (!element) return null;
    try {
      return JSON.parse(element.textContent || "null");
    } catch (error) {
      void error;
      return null;
    }
  };

  const chartRows = (canvas) => {
    const selector = canvas.dataset.chartRows;
    if (!selector) return [];
    return [...document.querySelectorAll(`${selector} [data-chart-row]`)];
  };

  const color = (name, fallback) => {
    const value = getComputedStyle(root).getPropertyValue(name).trim();
    return value || fallback;
  };

  const root = document.documentElement;

  const palette = () => [
    color("--primary", "#6366f1"),
    color("--danger", "#ef4444"),
    color("--success", "#10b981"),
    color("--warning", "#f59e0b"),
    color("--info", "#0ea5e9"),
    color("--purple", "#8b5cf6"),
    color("--text-muted", "#64748b"),
  ];

  const formatLabel = (value) => {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value || "—");
    return dateFormatter.format(date);
  };

  const formatTooltipValue = (value, suffix = "") => {
    const parsed = numberValue(value);
    if (parsed === null) return "No data";
    return `${numberFormatter.format(parsed)}${suffix}`;
  };

  const timelineConfig = (rows, primaryKey = "total") => {
    const labels = rows.map((row) => formatLabel(row.timestamp));
    const colors = palette();
    const primaryValues = rows.map((row) => numberValue(row[primaryKey]) ?? 0);
    const errorValues = rows.map((row) => numberValue(row.errors) ?? 0);
    const responseValues = rows.map((row) => numberValue(row.avg_response_time ?? row.response));
    const hasResponse = responseValues.some((value) => value !== null);
    const datasets = [
      {
        label: primaryKey === "errors" ? "Errors" : "Events",
        data: primaryValues,
        borderColor: primaryKey === "errors" ? colors[1] : colors[0],
        backgroundColor: primaryKey === "errors" ? color("--danger-soft", "#fef2f2") : color("--primary-soft", "#eef2ff"),
        pointBackgroundColor: primaryKey === "errors" ? colors[1] : colors[0],
        pointBorderColor: color("--surface", "#ffffff"),
        pointHoverRadius: 5,
        pointRadius: 0,
        borderWidth: 2,
        tension: 0.32,
        fill: true,
        yAxisID: "y",
      },
    ];
    if (primaryKey !== "errors") {
      datasets.push({
        label: "Errors",
        data: errorValues,
        borderColor: colors[1],
        backgroundColor: "transparent",
        pointBackgroundColor: colors[1],
        pointBorderColor: color("--surface", "#ffffff"),
        pointHoverRadius: 5,
        pointRadius: 0,
        borderWidth: 2,
        tension: 0.32,
        fill: false,
        yAxisID: "y",
      });
    }
    if (hasResponse) {
      datasets.push({
        label: "Avg response",
        data: responseValues.map((value) => value ?? null),
        borderColor: colors[3],
        backgroundColor: "transparent",
        pointBackgroundColor: colors[3],
        pointHoverRadius: 4,
        pointRadius: 0,
        borderWidth: 1.5,
        borderDash: [5, 4],
        tension: 0.3,
        fill: false,
        yAxisID: "response",
        spanGaps: false,
      });
    }
    return {
      type: "line",
      data: { labels, datasets },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { intersect: false, mode: "index" },
        animation: { duration: 450 },
        plugins: {
          legend: {
            align: "start",
            labels: { usePointStyle: true, pointStyle: "circle", boxWidth: 7, boxHeight: 7, padding: 16, color: color("--text-soft", "#475569") },
          },
          tooltip: {
            backgroundColor: color("--sidebar", "#0f172a"),
            borderColor: color("--border", "#e2e8f0"),
            borderWidth: 1,
            padding: 11,
            titleColor: "#ffffff",
            bodyColor: "#dbe4f0",
            callbacks: {
              label: (context) => `${context.dataset.label}: ${formatTooltipValue(context.parsed.y, context.dataset.yAxisID === "response" ? " ms" : "")}`,
            },
          },
        },
        scales: {
          x: { grid: { display: false }, ticks: { color: color("--text-muted", "#64748b"), maxRotation: 0, autoSkip: true, maxTicksLimit: 8 }, border: { display: false } },
          y: { beginAtZero: true, grid: { color: color("--border", "#e2e8f0"), drawTicks: false }, ticks: { color: color("--text-muted", "#64748b"), precision: 0, maxTicksLimit: 6 }, border: { display: false } },
          response: { display: hasResponse, position: "right", beginAtZero: true, grid: { drawOnChartArea: false }, ticks: { color: color("--text-muted", "#64748b"), callback: (value) => `${value} ms`, maxTicksLimit: 5 }, border: { display: false } },
        },
      },
    };
  };

  const doughnutConfig = (labels, values) => {
    const colors = palette();
    return {
      type: "doughnut",
      data: {
        labels,
        datasets: [{
          data: values,
          backgroundColor: labels.map((_, index) => colors[index % colors.length]),
          borderColor: color("--surface", "#ffffff"),
          borderWidth: 3,
          hoverOffset: 4,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        cutout: "67%",
        animation: { duration: 450 },
        plugins: {
          legend: {
            position: "bottom",
            labels: { usePointStyle: true, pointStyle: "circle", boxWidth: 7, boxHeight: 7, padding: 13, color: color("--text-soft", "#475569"), font: { size: 10 } },
          },
          tooltip: { callbacks: { label: (context) => `${context.label}: ${formatTooltipValue(context.parsed)}` } },
        },
      },
    };
  };

  const showChartUnavailable = (canvas) => {
    canvas.hidden = true;
    const container = canvas.closest(".chart-container");
    if (!container || container.querySelector("[data-chart-error]")) return;
    const message = document.createElement("p");
    message.className = "chart-error";
    message.dataset.chartError = "";
    message.textContent = "Chart rendering is unavailable. The measured data remains available in the page.";
    container.append(message);
  };

  const createChart = (canvas, config) => {
    if (!window.Chart) {
      showChartUnavailable(canvas);
      return;
    }
    canvas.hidden = false;
    canvas.closest(".chart-container")?.querySelector("[data-chart-error]")?.remove();
    const existing = canvasCharts.get(canvas);
    if (existing) existing.destroy();
    const chart = new window.Chart(canvas.getContext("2d"), config);
    canvasCharts.set(canvas, chart);
    charts.set(canvas.dataset.chartSource || canvas.dataset.chartRows || canvas.id, chart);
  };

  const renderCharts = () => {
    if (window.Chart) {
      window.Chart.defaults.font.family = getComputedStyle(root).fontFamily;
      window.Chart.defaults.color = color("--text-soft", "#475569");
    }
    document.querySelectorAll("canvas[data-chart]").forEach((canvas) => {
      const type = canvas.dataset.chart;
      if (type === "timeline") {
        const payload = readJSON(canvas.dataset.chartSource);
        const rows = Array.isArray(payload?.timeline) ? payload.timeline : [];
        if (rows.length) createChart(canvas, timelineConfig(rows, "total"));
        return;
      }
      if (type === "attribute-doughnut") {
        const labels = String(canvas.dataset.chartLabels || "").split(",").map((label) => label.trim()).filter(Boolean);
        const values = labels.map((_, index) => numberValue(index === 0 ? canvas.dataset.chartSuccesses : canvas.dataset.chartErrors) ?? 0);
        if (values.some((value) => value > 0)) createChart(canvas, doughnutConfig(labels, values));
        return;
      }
      if (type === "doughnut") {
        const payload = readJSON(canvas.dataset.chartSource);
        const group = canvas.dataset.chartGroup || "event_types";
        const rows = Array.isArray(payload?.[group]) ? payload[group] : [];
        if (rows.length) createChart(canvas, doughnutConfig(rows.map((row) => String(row.value ?? "Unspecified")), rows.map((row) => numberValue(row.count) ?? 0)));
        return;
      }
      if (type === "row-line") {
        const rows = chartRows(canvas).map((row) => ({
          timestamp: row.dataset.timestamp,
          total: numberValue(row.dataset.total),
          errors: numberValue(row.dataset.errors),
          successes: numberValue(row.dataset.successes),
          response: numberValue(row.dataset.response),
        }));
        if (rows.length) createChart(canvas, timelineConfig(rows, canvas.dataset.chartLineKey || "total"));
        return;
      }
      if (type === "row-doughnut") {
        const labelKey = canvas.dataset.chartLabelKey || "label";
        const valueKey = canvas.dataset.chartValueKey || "value";
        const rows = chartRows(canvas);
        if (rows.length) createChart(canvas, doughnutConfig(rows.map((row) => row.dataset[labelKey] || "Unspecified"), rows.map((row) => numberValue(row.dataset[valueKey]) ?? 0)));
      }
    });
  };

  const renderJSONBlocks = () => {
    document.querySelectorAll("[data-json-render]").forEach((target) => {
      const source = document.querySelector(target.dataset.jsonRender);
      if (!source) return;
      try {
        const value = JSON.parse(source.textContent || "null");
        target.textContent = JSON.stringify(value, null, 2);
      } catch (error) {
        void error;
      }
    });
  };

  const displayName = (event) => {
    if (event.custom_event_name) return String(event.custom_event_name);
    if (event.event_type) return String(event.event_type).replaceAll("_", " ").toLowerCase().replace(/(^|\s)\S/g, (value) => value.toUpperCase());
    return "Event";
  };

  const isErrorEvent = (event) => {
    const eventType = String(event.event_type || "").toUpperCase();
    const statusCode = numberValue(event.status_code);
    return eventType === "APPLICATION_ERROR" || eventType === "DATABASE_ERROR" || (statusCode !== null && statusCode >= 400);
  };

  const isSuccessEvent = (event) => {
    const statusCode = numberValue(event.status_code);
    return !isErrorEvent(event) && statusCode !== null && statusCode >= 200 && statusCode < 400;
  };

  const updateKpis = (event) => {
    document.querySelectorAll("[data-live-kpi]").forEach((element) => {
      const key = element.dataset.liveKpi;
      if (key === "total" || key === "errors" || key === "successes") {
        const current = numberValue(element.dataset.value);
        if (current === null) return;
        const increment = key === "total" ? 1 : key === "errors" ? Number(isErrorEvent(event)) : Number(isSuccessEvent(event));
        const next = current + increment;
        element.dataset.value = String(next);
        element.textContent = numberFormatter.format(next);
      }
    });
  };

  const eventURL = (template, id) => {
    if (!template || !id) return "";
    return template.replace(/\/0\/?$/, `/${id}/`);
  };

  const textCell = (text, className = "") => {
    const cell = document.createElement("td");
    if (className) cell.className = className;
    cell.textContent = text ?? "—";
    return cell;
  };

  const createEventRow = (event, table, card) => {
    const headers = [...table.querySelectorAll("thead th")].map((header) => header.textContent.trim());
    const row = document.createElement("tr");
    row.dataset.eventId = String(event.id || "");
    const id = numberValue(event.id);
    headers.forEach((header, index) => {
      if (index === 0) {
        const cell = document.createElement("td");
        const primary = document.createElement("span");
        primary.className = "table-primary";
        const url = eventURL(card.dataset.eventUrlTemplate, id);
        if (url) {
          const link = document.createElement("a");
          link.className = "table-primary";
          link.href = url;
          link.textContent = displayName(event);
          primary.remove();
          cell.append(link);
        } else {
          primary.textContent = displayName(event);
          cell.append(primary);
        }
        if (id !== null) {
          const secondary = document.createElement("span");
          secondary.className = "table-secondary";
          secondary.textContent = `#${id}`;
          cell.append(secondary);
        }
        row.append(cell);
        return;
      }
      if (header === "Service") row.append(textCell(event.service || "—"));
      else if (header === "Environment") row.append(textCell(event.environment || "—"));
      else if (header === "Status") {
        const cell = document.createElement("td");
        const status = numberValue(event.status_code);
        const badge = document.createElement("span");
        badge.className = `status-code status-code--${status !== null && status >= 500 ? "danger" : status !== null && status >= 400 ? "warning" : "success"}`;
        badge.textContent = status === null ? "—" : String(status);
        cell.append(badge);
        row.append(cell);
      } else if (header === "Response") {
        const response = numberValue(event.response_time);
        row.append(textCell(response === null ? "—" : `${numberFormatter.format(response)} ms`, response === null ? "" : "text-warning"));
      } else if (header === "Result") {
        const cell = document.createElement("td");
        const badge = document.createElement("span");
        badge.className = `badge badge-${isErrorEvent(event) ? "danger" : isSuccessEvent(event) ? "success" : "neutral"}`;
        badge.textContent = isErrorEvent(event) ? "Error" : isSuccessEvent(event) ? "Success" : "Other";
        cell.append(badge);
        row.append(cell);
      } else if (header === "Time") {
        const cell = document.createElement("td");
        const time = document.createElement("time");
        const value = event.created_at || event.timestamp || "";
        const date = new Date(value);
        if (value && !Number.isNaN(date.getTime())) {
          time.dateTime = date.toISOString();
          time.textContent = dateFormatter.format(date);
        } else {
          time.textContent = value || "—";
        }
        cell.append(time);
        row.append(cell);
      } else {
        row.append(textCell("—"));
      }
    });
    return row;
  };

  const updateLiveRows = (event) => {
    document.querySelectorAll("[data-live-events-card]").forEach((card) => {
      if (card.dataset.liveErrorOnly === "true" && !isErrorEvent(event)) return;
      const body = card.querySelector("[data-live-table-body]");
      if (!body || !event.id) return;
      if (body.querySelector(`[data-event-id="${CSS.escape(String(event.id))}"]`)) return;
      const empty = card.querySelector("[data-live-empty]");
      if (empty) empty.hidden = true;
      const row = createEventRow(event, body.closest("table"), card);
      body.prepend(row);
      const limit = numberValue(card.dataset.liveLimit) || 8;
      while (body.children.length > limit) body.lastElementChild.remove();
    });
  };

  const handleEvent = (event) => {
    if (!event || typeof event !== "object") return;
    updateKpis(event);
    updateLiveRows(event);
  };

  renderJSONBlocks();
  renderCharts();
  window.addEventListener("signalwatch:event", (event) => handleEvent(event.detail));
  window.addEventListener("signalwatch:themechange", () => {
    charts.clear();
    renderCharts();
  });
})();
