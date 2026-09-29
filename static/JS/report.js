// Report id comes from the URL path, e.g. /report/12 -> reportId = 12.
// Falls back to 0 (latest) if the page is opened without an id segment.
function getReportIdFromUrl() {
  const parts = window.location.pathname.split("/").filter(Boolean);
  const last = parts[parts.length - 1];
  const id = parseInt(last, 10);
  return Number.isNaN(id) ? 0 : id;
}

const REPORT_ID = getReportIdFromUrl();
const API_URL = `/api/report/data?id=${REPORT_ID}`;

// Fetch data from backend
async function loadReport() {
  const res = await fetch(API_URL);
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.error || `API Error ${res.status}`);
  }
  const data = await res.json();

  buildMeta(data);
  buildComponent(data);
  buildDefects(data);
}

// META
function buildMeta(r) {
  document.getElementById("meta").innerHTML = `
    <p><b>Customer:</b> ${r.customer ?? "-"}</p>
    <p><b>Part No:</b> ${r.partNo ?? "-"}</p>
    <p><b>Date:</b> ${r.date ?? "-"}</p>
  `;
}

// COMPONENT
function buildComponent(r) {
  const inspected = r.qtyInspected ?? 0;
  const rejected = r.qtyRejected ?? 0;
  const errors = r.qtyErrors ?? 0;
  // Prefer the backend's own accepted count; only fall back to subtraction
  // if an older API response doesn't include qtyAccepted yet.
  const accepted = r.qtyAccepted ?? Math.max(0, inspected - rejected - errors);

  document.getElementById("componentTable").innerHTML = `
    <tr><td>Height</td><td>${r.height ?? "-"}</td></tr>
    <tr><td>Cycle Time</td><td>${r.cycleTime ?? "-"}</td></tr>
    <tr><td>Total Inspected</td><td>${inspected}</td></tr>
    <tr><td>Rejected</td><td>${rejected}</td></tr>
    <tr><td>Errors</td><td>${errors}</td></tr>
    <tr><td>Accepted</td><td>${accepted}</td></tr>
    <tr><td>Final</td><td>${r.finalDecision ?? "-"}</td></tr>
  `;
}

// DEFECT TABLE
function buildDefects(r) {
  let html = `
    <tr>
      <th>Sl</th><th>Defect</th><th>Location</th>
      <th>Camera</th><th>Image</th><th>Status</th>
    </tr>
  `;

  const defects = Array.isArray(r.defects) ? r.defects : [];

  if (defects.length === 0) {
    html += `<tr><td colspan="6">No defects found</td></tr>`;
  } else {
    defects.forEach((d, i) => {
      // status comes straight from the backend (Rejected / Accepted / Error);
      // isError flags pipeline failures separately so they don't get
      // mistaken for a genuine reject or accept.
      const statusClass = d.isError
        ? "status-error"
        : /reject/i.test(d.status || "")
          ? "status-ng"
          : "status-ok";

      html += `
        <tr>
          <td>${i + 1}</td>
          <td>${d.type ?? "-"}</td>
          <td>${d.location ?? "-"}</td>
          <td>${d.camera ?? "-"}</td>
          <td>${d.image ? `<img src="${d.image}" alt="Defect" style="max-width:120px; max-height:80px; border-radius:3px;" />` : "-"}</td>
          <td><span class="${statusClass}">${d.status ?? "-"}</span></td>
        </tr>
      `;
    });
  }

  document.getElementById("defectTable").innerHTML = html;
}

// IMAGE PREVIEW
document.getElementById("originalInput").onchange = e => {
  if (e.target.files[0]) {
    document.getElementById("originalPreview").src =
      URL.createObjectURL(e.target.files[0]);
  }
};

document.getElementById("zoomInput").onchange = e => {
  if (e.target.files[0]) {
    document.getElementById("zoomPreview").src =
      URL.createObjectURL(e.target.files[0]);
  }
};

// SAVE JPG
function saveJPG() {
  html2canvas(document.getElementById("report")).then(canvas => {
    const link = document.createElement("a");
    link.download = "report.jpg";
    link.href = canvas.toDataURL();
    link.click();
  });
}

loadReport().catch(err => {
  console.error("Failed to load report:", err);
  const meta = document.getElementById("meta");
  if (meta) {
    meta.innerHTML = `<p style="color:#a53d30"><b>Couldn't load report:</b> ${err.message}</p>`;
  }
});