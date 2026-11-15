(() => {
  const byId = (id) => document.getElementById(id);
  const invoke = window.__TAURI__?.core?.invoke;
  let finished = false;

  function fail(code, message, controls = true) {
    finished = true;
    byId("startup-title").textContent = "Your workspace could not open";
    byId("loader").hidden = true;
    byId("message").textContent = message;
    byId("error-code").textContent = "Error code: " + code;
    byId("error-code").hidden = false;
    byId("details").hidden = false;
    byId("actions").hidden = !controls;
    if (controls) byId("retry").focus();
  }

  async function command(name) {
    let timer;
    try {
      return await Promise.race([
        invoke(name),
        new Promise((_, reject) => { timer = setTimeout(() => reject(new Error("The desktop service did not respond.")), 8000); })
      ]);
    } finally {
      clearTimeout(timer);
    }
  }

  async function refresh() {
    try {
      const status = await command("desktop_startup_status");
      if (status.phase === "failed") {
        fail(status.code || "startup-failed", status.message);
      } else if (status.phase === "ready") {
        byId("message").textContent = "Your workspace is ready. Opening the tracker…";
      }
    } catch {
      fail("desktop-control", "The desktop startup status is unavailable. Quit InternTrack from its tray menu and reopen it.");
    }
    if (!finished) setTimeout(refresh, 500);
  }

  byId("retry").addEventListener("click", async () => {
    byId("retry").disabled = true;
    byId("quit").disabled = true;
    byId("action-error").hidden = true;
    try {
      await command("retry_desktop_startup");
      byId("message").textContent = "Restarting InternTrack…";
    } catch (error) {
      byId("action-error").textContent = error instanceof Error ? error.message : "Use Quit from the tray menu, then reopen InternTrack.";
      byId("action-error").hidden = false;
      byId("retry").disabled = false;
      byId("quit").disabled = false;
    }
  });
  byId("quit").addEventListener("click", async () => {
    try {
      await command("quit_desktop_startup");
    } catch {
      byId("action-error").textContent = "Choose Quit from the InternTrack system-tray menu to stop the app.";
      byId("action-error").hidden = false;
    }
  });

  if (typeof invoke !== "function") {
    fail("desktop-app-required", "Open InternTrack from the installed desktop app to access your local workspace.", false);
  } else {
    void refresh();
  }
})();
