(() => {
  const $ = (id) => document.getElementById(id);
  const app = $("app"), file = $("file"), pick = $("pick"), go = $("go");
  const maxBytes = Number(app.dataset.maxMb) * 1024 * 1024;
  const POLL_MS = 1500, POLL_TIMEOUT_MS = 10 * 60 * 1000;
  let chosen = null, busy = false;

  const fmt = (b) => b > 1048576 ? (b / 1048576).toFixed(1) + " MB" : Math.max(1, Math.round(b / 1024)) + " KB";
  const showError = (m) => { const e = $("error"); e.textContent = m; e.hidden = !m; };
  const setStatus = (m, pct) => {
    $("progress").hidden = false; $("status").textContent = m;
    const f = $("fill");
    if (pct == null) f.classList.add("indeterminate");
    else { f.classList.remove("indeterminate"); f.style.width = pct + "%"; }
  };
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  function choose(f) {
    showError("");
    if (!f) return;
    if (!/\.mp4$/i.test(f.name)) return showError("Only .mp4 videos are supported.");
    if (f.size > maxBytes) return showError(`File is too large (max ${app.dataset.maxMb} MB).`);
    chosen = f;
    $("fname").textContent = f.name; $("fsize").textContent = fmt(f.size);
    $("chosen").hidden = false; $("pick-label").textContent = "Change file";
    go.disabled = false; $("progress").hidden = true;
  }

  pick.addEventListener("click", () => !busy && file.click());
  file.addEventListener("change", () => choose(file.files[0]));
  ["dragenter", "dragover"].forEach((t) => pick.addEventListener(t, (e) => { e.preventDefault(); pick.classList.add("over"); }));
  ["dragleave", "drop"].forEach((t) => pick.addEventListener(t, (e) => { e.preventDefault(); pick.classList.remove("over"); }));
  pick.addEventListener("drop", (e) => !busy && choose(e.dataTransfer.files[0]));

  // XHR (not fetch) so we get real upload progress.
  function upload(f) {
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest(), fd = new FormData();
      fd.append("file", f);
      xhr.open("POST", "/api/upload");
      xhr.upload.onprogress = (e) => e.lengthComputable && setStatus(`Uploading… ${Math.round(e.loaded / e.total * 100)}%`, e.loaded / e.total * 60);
      xhr.upload.onload = () => setStatus("Converting to MP3…", null);
      xhr.onerror = () => reject(new Error("Network error during upload."));
      xhr.onload = () => {
        let body = {}; try { body = JSON.parse(xhr.responseText); } catch (_) {}
        if (xhr.status === 401) { location.href = "/login"; return; }
        xhr.status === 200 ? resolve(body.video_fid) : reject(new Error(body.error || "Upload failed."));
      };
      xhr.send(fd);
    });
  }

  async function waitForMp3(videoFid) {
    const t0 = Date.now();
    while (Date.now() - t0 < POLL_TIMEOUT_MS) {
      const r = await fetch(`/api/status/${videoFid}`);
      if (r.status === 401) { location.href = "/login"; throw new Error("Session expired."); }
      const body = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(body.error || "Could not check conversion status.");
      if (body.ready) return body.mp3_fid;
      await sleep(POLL_MS);
    }
    throw new Error("Conversion is taking longer than expected. Please try again.");
  }

  function triggerDownload(mp3Fid, name) {
    const a = document.createElement("a");
    a.href = `/api/download/${mp3Fid}?name=${encodeURIComponent(name)}`;
    a.download = ""; document.body.appendChild(a); a.click(); a.remove();
  }

  go.addEventListener("click", async () => {
    if (!chosen || busy) return;
    busy = true; go.disabled = true; pick.disabled = true; showError("");
    go.textContent = "Working…";
    try {
      setStatus("Uploading… 0%", 0);
      const videoFid = await upload(chosen);
      const mp3Fid = await waitForMp3(videoFid);
      setStatus("Done! Your download is starting.", 100);
      triggerDownload(mp3Fid, chosen.name);
      go.textContent = "Convert another file";
    } catch (err) {
      $("progress").hidden = true; showError(err.message);
      go.textContent = "Convert & download MP3";
    } finally {
      busy = false; go.disabled = false; pick.disabled = false;
    }
  });
})();
