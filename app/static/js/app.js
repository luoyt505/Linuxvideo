/* mediahub · 前端单页应用（原生 JS，无外部依赖） */
(function () {
  "use strict";

  // ------------------------------------------------------------------ //
  // 状态
  // ------------------------------------------------------------------ //
  const state = {
    page: 1,
    pageSize: 24,
    query: "",
    mediaType: "",
    year: "",
    sort: "created_at:desc",
    total: 0,
    pages: 1,
    currentItem: null,
    pollTimer: null,
    // 正在跟踪的任务：{taskId: element}
    tracked: new Map()
  };

  const $ = (id) => document.getElementById(id);
  const api = {
    list: (params) => request("/api/media?" + new URLSearchParams(params).toString()),
    item: (id) => request(`/api/media/${id}`),
    stats: () => request("/api/library/stats"),
    dirs: () => request("/api/library/dirs"),
    health: () => request("/api/health"),
    scan: (body) => request("/api/library/scan", { method: "POST", body: body || {} }),
    tasks: () => request("/api/tasks?limit=40"),
    task: (id) => request(`/api/tasks/${id}`),
    cancelTask: (id) => request(`/api/tasks/${id}/cancel`, { method: "POST" }),
    transcode: (body) => request("/api/tasks/transcode", { method: "POST", body: body }),
    extractAudio: (body) => request("/api/tasks/extract-audio", { method: "POST", body: body }),
    screenshot: (body) => request("/api/tasks/screenshot", { method: "POST", body: body }),
    removeItem: (id) => request(`/api/media/${id}`, { method: "DELETE" })
  };

  async function request(url, options) {
    const opts = Object.assign({ headers: { "Content-Type": "application/json" } }, options || {});
    if (opts.body && typeof opts.body !== "string") opts.body = JSON.stringify(opts.body);
    const response = await fetch(url, opts);
    const text = await response.text();
    let data = null;
    try { data = text ? JSON.parse(text) : null; } catch (e) { data = text; }
    if (!response.ok) {
      const detail = data && data.detail ? (typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail)) : response.statusText;
      throw new Error(detail || ("HTTP " + response.status));
    }
    return data;
  }

  // ------------------------------------------------------------------ //
  // 通用 UI
  // ------------------------------------------------------------------ //
  let toastTimer = null;
  function toast(message, kind) {
    const el = $("toast");
    el.textContent = message;
    el.className = "toast " + (kind || "");
    if (toastTimer) clearTimeout(toastTimer);
    toastTimer = setTimeout(() => el.classList.add("hidden"), 3200);
  }

  function showModal(id) { $(id).classList.remove("hidden"); }
  function hideModal(id) { $(id).classList.add("hidden"); }

  function formatDuration(seconds) {
    const total = Math.max(0, Math.floor(seconds || 0));
    const h = Math.floor(total / 3600);
    const m = Math.floor((total % 3600) / 60);
    const s = total % 60;
    const pad = (n) => String(n).padStart(2, "0");
    return h > 0 ? `${h}:${pad(m)}:${pad(s)}` : `${m}:${pad(s)}`;
  }

  function formatSize(bytes) {
    let value = Number(bytes || 0);
    const units = ["B", "KB", "MB", "GB", "TB"];
    let index = 0;
    while (value >= 1024 && index < units.length - 1) { value /= 1024; index += 1; }
    return index === 0 ? `${value} B` : `${value.toFixed(2)} ${units[index]}`;
  }

  const TYPE_LABEL = { video: "视频", audio: "音频", image: "图片", other: "其它" };
  const TYPE_ICON = { video: "▶", audio: "♪", image: "▣", other: "▤" };

  // ------------------------------------------------------------------ //
  // 媒体网格
  // ------------------------------------------------------------------ //
  async function loadMedia() {
    const [sortField, order] = state.sort.split(":");
    const params = {
      page: state.page,
      page_size: state.pageSize,
      sort: sortField,
      order: order
    };
    if (state.query) params.q = state.query;
    if (state.mediaType) params.media_type = state.mediaType;
    if (state.year) params.year = state.year;

    try {
      const data = await api.list(params);
      state.total = data.total;
      state.pages = data.pages || 1;
      renderGrid(data.items);
      $("result-count").textContent = `共 ${data.total} 个条目`;
      $("page-info").textContent = `第 ${data.page} / ${Math.max(1, data.pages)} 页`;
      $("prev-page").disabled = data.page <= 1;
      $("next-page").disabled = data.page >= Math.max(1, data.pages);
    } catch (error) {
      toast("加载媒体库失败：" + error.message, "error");
    }
  }

  function renderGrid(items) {
    const grid = $("media-grid");
    grid.innerHTML = "";
    $("empty-state").classList.toggle("hidden", items.length > 0);

    items.forEach((item) => {
      const card = document.createElement("div");
      card.className = "card";

      const thumb = document.createElement("div");
      thumb.className = "card-thumb";
      if (item.has_thumbnail) {
        thumb.style.backgroundImage = `url('/api/media/${item.id}/thumbnail')`;
        thumb.textContent = "";
      } else {
        thumb.textContent = TYPE_ICON[item.media_type] || "▤";
      }

      const typeBadge = document.createElement("span");
      typeBadge.className = "badge-type";
      typeBadge.textContent = TYPE_LABEL[item.media_type] || "其它";
      thumb.appendChild(typeBadge);

      if (item.duration > 0) {
        const duration = document.createElement("span");
        duration.className = "duration";
        duration.textContent = formatDuration(item.duration);
        thumb.appendChild(duration);
      }

      const body = document.createElement("div");
      body.className = "card-body";

      const title = document.createElement("div");
      title.className = "card-title";
      title.textContent = item.title || item.filename;
      title.title = item.path || item.filename;

      const meta = document.createElement("div");
      meta.className = "card-meta";
      const left = document.createElement("span");
      left.textContent = item.width && item.height ? `${item.width}×${item.height}` : formatSize(item.size);
      const right = document.createElement("span");
      right.textContent = item.year || formatSize(item.size);
      meta.appendChild(left);
      meta.appendChild(right);

      body.appendChild(title);
      body.appendChild(meta);
      card.appendChild(thumb);
      card.appendChild(body);

      card.addEventListener("click", () => openPlayer(item, false));
      grid.appendChild(card);
    });
  }

  // ------------------------------------------------------------------ //
  // 播放器
  // ------------------------------------------------------------------ //
  async function openPlayer(item, forceProbe) {
    state.currentItem = item;
    $("player-title").textContent = item.title || item.filename;
    $("player-meta").textContent = [
      TYPE_LABEL[item.media_type] || "其它",
      item.container ? item.container.toUpperCase() : null,
      item.duration ? formatDuration(item.duration) : null,
      item.width && item.height ? `${item.width}×${item.height}` : null,
      item.video_codec ? item.video_codec : null,
      item.audio_codec ? item.audio_codec : null,
      formatSize(item.size)
    ].filter(Boolean).join(" · ");

    const video = $("player-video");
    const image = $("player-image");
    video.pause();

    if (item.media_type === "image") {
      video.classList.add("hidden");
      image.classList.remove("hidden");
      image.src = `/api/media/${item.id}/download`;
    } else {
      image.classList.add("hidden");
      video.classList.remove("hidden");
      video.src = `/api/stream/${item.id}`;
      video.load();
      // 静默探测媒体元信息，失败不影响播放
      try { await api.item(item.id); } catch (e) { /* 忽略 */ }
    }
    showModal("player-modal");
    if (forceProbe) await refreshDetail(item.id);
  }

  async function refreshDetail(id) {
    try {
      const detail = await api.item(id);
      if (detail && detail.duration) {
        state.currentItem = Object.assign({}, state.currentItem, detail);
      }
    } catch (error) {
      toast("获取详情失败：" + error.message, "error");
    }
  }

  function closePlayer() {
    const video = $("player-video");
    video.pause();
    video.removeAttribute("src");
    video.load();
    $("player-image").src = "";
    hideModal("player-modal");
    state.currentItem = null;
  }

  // ------------------------------------------------------------------ //
  // 任务面板
  // ------------------------------------------------------------------ //
  const TASK_LABEL = {
    scan: "扫描",
    transcode: "转码",
    extract_audio: "抽音轨",
    screenshot: "截图"
  };
  const STATUS_LABEL = {
    pending: "排队中",
    running: "执行中",
    success: "已完成",
    failed: "失败",
    canceled: "已取消"
  };

  function taskName(task) {
    const params = task.params || {};
    const source = params.source_path || task.source_path || params.directory || "";
    return source ? source.split("/").pop() : (TASK_LABEL[task.task_type] || task.task_type);
  }

  async function loadTasks(silent) {
    try {
      const data = await api.tasks();
      renderTasks(data.items);
    } catch (error) {
      if (!silent) toast("加载任务失败：" + error.message, "error");
    }
  }

  function renderTasks(items) {
    const list = $("task-list");
    list.innerHTML = "";

    const active = items.filter((t) => t.status === "running" || t.status === "pending").length;
    const badge = $("task-badge");
    badge.textContent = String(active);
    badge.classList.toggle("hidden", active === 0);

    if (!items.length) {
      list.innerHTML = '<p class="muted">暂无任务。可在播放器中提交转码 / 抽音轨 / 截图。</p>';
      return;
    }

    items.forEach((task) => {
      const item = document.createElement("div");
      item.className = "task-item";

      const top = document.createElement("div");
      top.className = "task-top";

      const type = document.createElement("span");
      type.className = "task-type";
      type.textContent = TASK_LABEL[task.task_type] || task.task_type;

      const file = document.createElement("span");
      file.className = "task-file";
      file.textContent = taskName(task);

      const status = document.createElement("span");
      status.className = "task-status status-" + task.status;
      status.textContent = STATUS_LABEL[task.status] || task.status;

      top.appendChild(type);
      top.appendChild(file);
      top.appendChild(status);

      const track = document.createElement("div");
      track.className = "progress-track";
      const fill = document.createElement("div");
      fill.className = "progress-fill";
      fill.style.width = `${task.status === "success" ? 100 : (task.progress || 0)}%`;
      track.appendChild(fill);

      const foot = document.createElement("div");
      foot.className = "task-foot";

      const info = document.createElement("span");
      info.className = "muted";
      if (task.error) {
        info.className = "task-error";
        info.textContent = task.error;
      } else if (task.output_path && task.status === "success") {
        info.textContent = "输出：" + task.output_path;
      } else {
        info.textContent = `进度 ${task.progress || 0}% · #${task.id}`;
      }

      foot.appendChild(info);

      if (task.status === "running" || task.status === "pending") {
        const cancel = document.createElement("button");
        cancel.className = "btn ghost";
        cancel.textContent = "取消";
        cancel.addEventListener("click", async () => {
          try {
            await api.cancelTask(task.id);
            toast("已请求取消任务 #" + task.id);
            loadTasks(true);
          } catch (error) {
            toast("取消失败：" + error.message, "error");
          }
        });
        foot.appendChild(cancel);
      }

      item.appendChild(top);
      item.appendChild(track);
      item.appendChild(foot);
      list.appendChild(item);
    });
  }

  function startPolling() {
    if (state.pollTimer) return;
    state.pollTimer = setInterval(() => {
      if ($("tasks-modal").classList.contains("hidden") === false) loadTasks(true);
      else loadTasks(true);
    }, 3000);
  }

  // ------------------------------------------------------------------ //
  // 统计
  // ------------------------------------------------------------------ //
  async function showStats() {
    try {
      const data = await api.stats();
      const body = $("stats-body");
      body.innerHTML = "";
      const cards = [
        ["条目总数", data.total_items],
        ["视频", data.by_type.video || 0],
        ["音频", data.by_type.audio || 0],
        ["图片", data.by_type.image || 0],
        ["总大小", data.total_size_human],
        ["总时长", data.total_duration_human],
        ["已生成封面", data.thumbnail_count],
        ["媒体目录", (data.media_dirs || []).length]
      ];
      cards.forEach(([label, value]) => {
        const card = document.createElement("div");
        card.className = "stat-card";
        const l = document.createElement("div");
        l.className = "label";
        l.textContent = label;
        const v = document.createElement("div");
        v.className = "value";
        v.textContent = value;
        card.appendChild(l);
        card.appendChild(v);
        body.appendChild(card);
      });
      if (data.media_dirs && data.media_dirs.length) {
        const list = document.createElement("div");
        list.className = "stat-card";
        list.style.gridColumn = "1 / -1";
        list.innerHTML = "<div class='label'>已配置媒体目录</div><div class='value' style='font-size:13px;font-weight:400;word-break:break-all'>"
          + data.media_dirs.join("<br>") + "</div>";
        body.appendChild(list);
      }
      showModal("stats-modal");
      await loadYears();
    } catch (error) {
      toast("加载统计失败：" + error.message, "error");
    }
  }

  async function loadYears() {
    try {
      const data = await api.stats();
      const select = $("year-filter");
      const current = select.value;
      select.innerHTML = '<option value="">全部</option>';
      (data.by_year || []).forEach((row) => {
        const option = document.createElement("option");
        option.value = String(row.year);
        option.textContent = `${row.year}（${row.count}）`;
        select.appendChild(option);
      });
      select.value = current;
    } catch (error) { /* 忽略 */ }
  }

  // ------------------------------------------------------------------ //
  // 操作
  // ------------------------------------------------------------------ //
  async function doScan() {
    try {
      const task = await api.scan({});
      toast(`已提交扫描任务 #${task.id}`, "success");
      loadTasks(true);
      showModal("tasks-modal");
    } catch (error) {
      toast("提交扫描任务失败：" + error.message, "error");
    }
  }

  async function doHealth() {
    try {
      const data = await api.health();
      const lines = [
        `状态：${data.status}`,
        `媒体条目：${data.media_count}`,
        `数据库：${data.database}`,
        `ffmpeg：${data.ffmpeg.available ? "可用" : "不可用"}`,
        `ffprobe：${data.ffprobe.available ? "可用" : "不可用"}`,
        `任务队列：${data.task_queue.workers} 线程 / 排队 ${data.task_queue.pending_in_memory}`,
        `运行时长：${Math.round(data.uptime_seconds)}s`
      ];
      toast(lines.join("　|　"), data.status === "ok" ? "success" : "error");
    } catch (error) {
      toast("健康检查失败：" + error.message, "error");
    }
  }

  async function doTranscode() {
    const item = state.currentItem;
    if (!item) return;
    try {
      const task = await api.transcode({
        media_id: item.id,
        vcodec: "libx264",
        acodec: "aac",
        crf: 23,
        preset: "medium",
        audio_bitrate: "192k"
      });
      toast(`已提交转码任务 #${task.id}`, "success");
      loadTasks(true);
      showModal("tasks-modal");
    } catch (error) {
      toast("提交转码任务失败：" + error.message, "error");
    }
  }

  async function doExtractAudio() {
    const item = state.currentItem;
    if (!item) return;
    try {
      const task = await api.extractAudio({
        media_id: item.id,
        acodec: "libmp3lame",
        bitrate: "192k"
      });
      toast(`已提交抽音轨任务 #${task.id}`, "success");
      loadTasks(true);
      showModal("tasks-modal");
    } catch (error) {
      toast("提交抽音轨任务失败：" + error.message, "error");
    }
  }

  async function doScreenshot() {
    const item = state.currentItem;
    if (!item) return;
    const video = $("player-video");
    const at = item.media_type === "image" ? 0 : Math.max(0, Math.floor(video.currentTime || 0));
    try {
      const task = await api.screenshot({ media_id: item.id, at: at, width: 1280 });
      toast(`已提交截图任务 #${task.id}（第 ${at} 秒）`, "success");
      loadTasks(true);
      showModal("tasks-modal");
    } catch (error) {
      toast("提交截图任务失败：" + error.message, "error");
    }
  }

  // ------------------------------------------------------------------ //
  // 事件绑定
  // ------------------------------------------------------------------ //
  function bindEvents() {
    $("search-btn").addEventListener("click", () => {
      state.query = $("search-input").value.trim();
      state.page = 1;
      loadMedia();
    });
    $("search-input").addEventListener("keydown", (event) => {
      if (event.key === "Enter") $("search-btn").click();
    });

    $("type-filters").addEventListener("click", (event) => {
      const chip = event.target.closest(".chip");
      if (!chip) return;
      Array.prototype.forEach.call($("type-filters").children, (el) => el.classList.remove("active"));
      chip.classList.add("active");
      state.mediaType = chip.dataset.type || "";
      state.page = 1;
      loadMedia();
    });

    $("year-filter").addEventListener("change", (event) => {
      state.year = event.target.value;
      state.page = 1;
      loadMedia();
    });

    $("sort-filter").addEventListener("change", (event) => {
      state.sort = event.target.value;
      state.page = 1;
      loadMedia();
    });

    $("prev-page").addEventListener("click", () => {
      if (state.page > 1) { state.page -= 1; loadMedia(); window.scrollTo({ top: 0 }); }
    });
    $("next-page").addEventListener("click", () => {
      if (state.page < state.pages) { state.page += 1; loadMedia(); window.scrollTo({ top: 0 }); }
    });

    $("scan-btn").addEventListener("click", doScan);
    $("stats-btn").addEventListener("click", showStats);
    $("health-btn").addEventListener("click", doHealth);
    $("tasks-btn").addEventListener("click", () => { showModal("tasks-modal"); loadTasks(true); });

    $("player-screenshot").addEventListener("click", doScreenshot);
    $("player-extract").addEventListener("click", doExtractAudio);
    $("player-transcode").addEventListener("click", doTranscode);

    document.querySelectorAll(".modal-close").forEach((button) => {
      button.addEventListener("click", () => {
        const target = button.dataset.close;
        if (target === "player-modal") closePlayer();
        else hideModal(target);
      });
    });

    document.querySelectorAll(".modal").forEach((modal) => {
      modal.addEventListener("click", (event) => {
        if (event.target === modal) {
          if (modal.id === "player-modal") closePlayer();
          else modal.classList.add("hidden");
        }
      });
    });

    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        if (!$("player-modal").classList.contains("hidden")) closePlayer();
        document.querySelectorAll(".modal").forEach((m) => m.classList.add("hidden"));
      }
    });
  }

  // ------------------------------------------------------------------ //
  // 启动
  // ------------------------------------------------------------------ //
  document.addEventListener("DOMContentLoaded", async () => {
    bindEvents();
    await loadMedia();
    await loadYears();
    await loadTasks(true);
    startPolling();
  });
})();
