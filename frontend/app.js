let currentFilter = "all";

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, ch => ({
    "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"
  }[ch]));
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: {"Content-Type": "application/json"},
    ...options
  });
  if (!response.ok) {
    const body = await response.text();
    throw new Error(`${response.status}: ${body}`);
  }
  return response.json();
}

function renderDevices(devices) {
  const root = document.getElementById("devices");
  const visible = currentFilter === "all" ? devices : devices.filter(d => d.protocol === currentFilter);
  if (!visible.length) {
    root.innerHTML = '<div class="empty-state"><h2>No devices</h2><p>Run a local scan or change the filter.</p></div>';
    return;
  }
  root.innerHTML = visible.map(d => {
    const props = Object.entries(d.properties || {})
      .filter(([k,v]) => ["source","service_type","arp_state","model","vendor"].includes(k) && v)
      .map(([k,v]) => `<span>${esc(k)}: ${esc(v)}</span>`).join("");
    return `<article class="device-card">
      <div class="type-badge badge-${esc(d.device_type)}">${esc(d.device_type)}</div>
      <div class="device-name"><span class="online-dot ${d.online ? "online":"offline"}"></span>${esc(d.name)}</div>
      <div class="device-addr">${esc(d.address || "")}${d.port ? ":" + esc(d.port) : ""}</div>
      <div class="device-props">
        <span>protocol: ${esc(d.protocol)}</span>
        ${d.mac ? `<span>mac: ${esc(d.mac)}</span>` : ""}
        ${d.interface ? `<span>interface: ${esc(d.interface)}</span>` : ""}
        ${props}
      </div>
    </article>`;
  }).join("");
}

async function refresh() {
  const [health, inventory] = await Promise.all([
    api("/rest/api/v1/health"), api("/rest/api/v1/devices")
  ]);
  document.getElementById("stat-total").textContent = health.inventory.total;
  document.getElementById("stat-online").textContent = health.inventory.online;
  document.getElementById("stat-protocols").textContent = Object.keys(health.inventory.protocols || {}).length;
  renderDevices(inventory.devices);
}

async function scan() {
  const button = document.getElementById("scan-btn");
  const message = document.getElementById("message");
  button.disabled = true;
  message.textContent = "Scanning ARP + mDNS...";
  try {
    const result = await api("/rest/api/v1/discovery/scan", {
      method: "POST",
      body: JSON.stringify({arp:true, mdns:true, mdns_timeout:2.0, lookup_vendors:false})
    });
    message.textContent = `Found ${result.discovered} observations${result.errors.length ? `; ${result.errors.length} warning(s)` : ""}`;
    await refresh();
  } catch (error) {
    message.textContent = `Scan failed: ${error.message}`;
  } finally {
    button.disabled = false;
  }
}

async function clearInventory() {
  await api("/rest/api/v1/devices", {method:"DELETE"});
  await refresh();
}

document.getElementById("scan-btn").addEventListener("click", scan);
document.getElementById("refresh-btn").addEventListener("click", refresh);
document.getElementById("clear-btn").addEventListener("click", clearInventory);
document.querySelectorAll(".filter-btn").forEach(button => {
  button.addEventListener("click", async () => {
    document.querySelectorAll(".filter-btn").forEach(b => b.classList.remove("active"));
    button.classList.add("active");
    currentFilter = button.dataset.filter;
    const inventory = await api("/rest/api/v1/devices");
    renderDevices(inventory.devices);
  });
});
refresh().catch(error => {
  document.getElementById("message").textContent = `Backend unavailable: ${error.message}`;
});
