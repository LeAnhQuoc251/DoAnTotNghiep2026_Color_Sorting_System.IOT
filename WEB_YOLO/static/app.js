// Giao diện web điều khiển hệ thống phân loại màu sắc.
// Toàn bộ dữ liệu lấy từ máy chủ Python qua /api/status (không dùng CSDL).
const $ = (id) => document.getElementById(id);
const POLL_MS = 400;
const ST_TEXT = { 0: "CHỜ", 1: "ĐANG CHẠY", 2: "ĐÃ DỪNG" };

let lastResultId = null;
let historyKey = "";
let counts = { do: null, luc: null, lam: null };
let offline = false;
let everConnected = false;
let shutDown = false;

// ------------------------------------------------------------------ tiện ích
let toastTimer;
function toast(msg, type = "error") {
  const t = $("toast");
  t.textContent = msg;
  t.className = `toast show ${type}`;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (t.className = "toast"), 2600);
}

async function post(url) {
  try {
    const r = await fetch(url, { method: "POST" });
    const j = await r.json().catch(() => ({}));
    if (!r.ok || j.ok === false) {
      toast(j.error || `Lỗi máy chủ (${r.status})`);
      return null;
    }
    return j;
  } catch {
    toast("Không kết nối được máy chủ");
    return null;
  }
}

function setPill(el, ok, text) {
  el.classList.toggle("ok", ok);
  el.classList.toggle("bad", !ok);
  el.querySelector("span").textContent = text;
}

function showOverlay(show, title, text) {
  $("overlay").hidden = !show;
  if (title) $("overlay-title").textContent = title;
  if (text) $("overlay-text").textContent = text;
}

function reloadVideo() {
  $("video").src = `/video_feed?t=${Date.now()}`;
}

// ------------------------------------------------------------------ hiển thị
function renderResult(r) {
  $("res-swatch").style.background = r.hex;
  $("res-swatch").classList.add("filled");
  $("res-color").textContent = r.color_name;
  $("res-color").style.color = r.hex;
  $("res-meta").textContent = `Lúc ${r.time}${r.test ? " · nhận diện thử" : ""}`;

  const pct = r.conf == null ? 0 : Math.round(r.conf * 100);
  $("conf-text").textContent = r.conf == null ? "—" : `${pct}%`;
  $("conf-fill").style.width = `${pct}%`;
  $("conf-fill").style.background = r.hex;

  $("res-method").textContent = r.method;
  $("res-ms").textContent = `${r.ms} ms`;
  $("res-sent").textContent = r.test ? "Không (thử)" : r.sent ? "Đã gửi" : "Lỗi gửi";

  const img = $("snapshot");
  img.onload = () => { img.hidden = false; $("snapshot-empty").hidden = true; };
  img.src = `/snapshot.jpg?id=${r.id}`;
}

function renderHistory(list) {
  const key = list.length ? `${list[0].id}-${list.length}` : "empty";
  if (key === historyKey) return;
  historyKey = key;
  const body = $("history");
  body.replaceChildren();
  if (!list.length) {
    body.innerHTML = '<tr class="empty-row"><td colspan="5">Chưa có dữ liệu</td></tr>';
    return;
  }
  for (const r of list) {
    const tr = document.createElement("tr");
    const cells = [
      [r.time, "num"],
      null,
      [r.conf == null ? "—" : `${Math.round(r.conf * 100)}%`, "num"],
      [r.method, ""],
      null,
    ];
    cells.forEach((c, i) => {
      const td = document.createElement("td");
      if (i === 1) {
        const tag = document.createElement("span");
        tag.className = "tag";
        tag.style.color = r.hex;
        const dot = document.createElement("i");
        dot.style.background = r.hex;
        tag.append(dot, r.color_name);
        td.append(tag);
      } else if (i === 4) {
        const s = document.createElement("span");
        s.className = r.test ? "src" : "src esp";
        s.textContent = r.test ? "Thử" : "ESP32";
        td.append(s);
      } else {
        td.textContent = c[0];
        if (c[1]) td.className = c[1];
      }
      tr.append(td);
    });
    body.append(tr);
  }
}

function setCount(id, key, value) {
  const el = $(id);
  if (counts[key] !== null && value !== counts[key]) {
    const box = el.parentElement;
    box.classList.remove("bump");
    void box.offsetWidth; // khởi động lại hiệu ứng
    box.classList.add("bump");
  }
  counts[key] = value;
  el.textContent = value;
}

function render(s) {
  const e = s.esp;
  setPill($("pill-esp"), e.connected,
    e.connected ? `ESP32 · ${e.port}` : `ESP32 · chưa kết nối (${e.port})`);
  setPill($("pill-cam"), s.camera.ok,
    s.camera.ok ? `Camera · ${s.camera.fps} FPS` : "Camera · không có tín hiệu");
  $("clock").textContent = s.server_time;

  // Chế độ + trạng thái chạy/dừng
  const manual = e.mode === 1;
  const bm = $("btn-mode");
  bm.textContent = manual ? "CHẾ ĐỘ: MANUAL" : "CHẾ ĐỘ: AUTO";
  bm.classList.toggle("manual", manual);
  $("status-light").dataset.st = e.st;
  $("status-text").textContent = ST_TEXT[e.st] ?? "—";
  for (const id of ["btn-mode", "btn-start", "btn-stop"]) $(id).disabled = !e.connected;

  // Bộ đếm (do ESP32 đếm sau khi gạt sản phẩm)
  setCount("cnt-do", "do", e.sl_do);
  setCount("cnt-luc", "luc", e.sl_luc);
  setCount("cnt-lam", "lam", e.sl_lam);
  $("cnt-total").textContent = e.sl_do + e.sl_luc + e.sl_lam;

  // Điều khiển tay
  const pairs = [["btn-g1", "g1"], ["btn-g2", "g2"], ["btn-bt", "bt"]];
  for (const [id, key] of pairs) {
    const btn = $(id);
    const on = e.outputs[key] === 1;
    btn.classList.toggle("on", on);
    btn.querySelector("em").textContent = on ? "BẬT" : "TẮT";
    btn.disabled = !e.connected || !manual;
  }
  $("manual-hint").textContent = !e.connected
    ? "Chưa kết nối ESP32."
    : !manual
      ? "Chuyển sang chế độ MANUAL để dùng các nút này."
      : e.st !== 1
        ? "Nhấn START để kích hoạt điều khiển tay."
        : "";

  // Kết quả phân loại
  $("btn-detect").disabled = !s.camera.ok || s.busy;
  $("res-card").classList.toggle("busy", s.busy);
  if (s.last && s.last.id !== lastResultId) {
    lastResultId = s.last.id;
    renderResult(s.last);
  }
  renderHistory(s.history);
}

// -------------------------------------------------------------- vòng cập nhật
async function poll() {
  if (shutDown) return;
  try {
    const r = await fetch("/api/status", { cache: "no-store" });
    if (!r.ok) throw new Error(r.status);
    render(await r.json());
    everConnected = true;
    if (offline) {
      offline = false;
      showOverlay(false);
      reloadVideo();
    }
  } catch {
    if (!offline) {
      offline = true;
      if (everConnected) {
        showOverlay(true, "Mất kết nối tới máy chủ", "Kiểm tra cửa sổ run.bat trên máy tính. Đang thử kết nối lại...");
      } else {
        showOverlay(true, "Đang khởi động hệ thống", "Đang tải model YOLO và camera, vui lòng chờ vài giây...");
      }
    }
  } finally {
    setTimeout(poll, POLL_MS);
  }
}

// ------------------------------------------------------------------ sự kiện
$("btn-mode").onclick = () => post("/api/cmd/mode");
$("btn-start").onclick = () => post("/api/cmd/start");
$("btn-stop").onclick = () => post("/api/cmd/stop");
for (const id of ["btn-g1", "btn-g2", "btn-bt"]) {
  $(id).onclick = () => post(`/api/cmd/${$(id).dataset.cmd}`);
}

$("btn-detect").onclick = async () => {
  $("btn-detect").disabled = true;
  const j = await post("/api/detect");
  if (j) toast(`Nhận diện: ${j.result.color_name} (${j.result.method})`, "ok");
};

$("btn-exit").onclick = async () => {
  if (!confirm("Thoát hệ thống?\nBăng tải sẽ dừng và chương trình Python trên máy tính sẽ tắt.")) return;
  const j = await post("/api/exit");
  if (!j) return;
  shutDown = true;
  $("video").removeAttribute("src");
  showOverlay(true, "Hệ thống đã tắt", "Chạy lại run.bat trên máy tính để khởi động lại.");
};

$("video").onerror = () => {
  if (!shutDown) setTimeout(reloadVideo, 2000);
};

poll();
