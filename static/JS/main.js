let cameraStarted = false;
let liveInterval = null;
let statsInterval = null;
let autoCaptureInterval = null;
let shiftChart = null;
let statsBusy = false;
let reconnectAttempts = 0;

// ======================================
// HELPERS
// ======================================

const $ = (id) => document.getElementById(id);

function log(message, type = "info") {
    const timestamp = new Date().toLocaleTimeString();
    console.log(`[${timestamp}] [${type.toUpperCase()}] ${message}`);
}

function showNotification(message, type = "info") {
    console.log(`[${type.toUpperCase()}] ${message}`);
}

const CAMERA_STATE_KEY = "inspectionCameraActive";

function setSavedCameraState(active) {
    localStorage.setItem(CAMERA_STATE_KEY, active ? "true" : "false");
}

function getSavedCameraState() {
    return localStorage.getItem(CAMERA_STATE_KEY) === "true";
}

async function fetchCameraStatus() {
    try {
        const response = await fetch("/camera/config", {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({ cam_id: "cam1" })
        });

        const data = await response.json();
        if (!response.ok) {
            console.error("Failed to fetch camera status", data);
            return null;
        }

        return data.camera_status || null;
    } catch (error) {
        console.error("Error fetching camera status:", error);
        return null;
    }
}

function updateInspectionUI(active) {
    const statusElement = $("liveStatus");
    if (statusElement) {
        statusElement.innerText = active ? "Running" : "Stopped";
        statusElement.className = `status ${active ? "running" : "stopped"}`;
    }

    const startBtn = $("startBtn");
    const stopBtn = $("stopBtn");
    if (startBtn) startBtn.disabled = active;
    if (stopBtn) stopBtn.disabled = !active;
}

async function restoreInspectionState() {
    if (!getSavedCameraState()) {
        updateInspectionUI(false);
        return;
    }

    const status = await fetchCameraStatus();
    if (status && status.running) {
        cameraStarted = true;
        updateInspectionUI(true);
        loadCameraStreams(["cam1", "cam2", "cam3"]);
        startLiveLoop();
        startAutoCaptureLoop();
        updateStats();
        console.log("Restored active inspection state after navigation.");
    } else {
        setSavedCameraState(false);
        cameraStarted = false;
        updateInspectionUI(false);
        console.log("Inspection state not active on server, clearing preserved state.");
    }
}

// ======================================
// DOM READY
// ======================================

document.addEventListener("DOMContentLoaded", () => {

    log("Initializing inspection dashboard");

    const startBtn = $("startBtn");
    const stopBtn = $("stopBtn");

    if (!startBtn || !stopBtn) {
        log("Buttons not found", "error");
        return;
    }

    startBtn.addEventListener("click", startInspection);
    stopBtn.addEventListener("click", stopInspection);

    stopBtn.disabled = true;

    ["cam1", "cam2", "cam3"].forEach(id => {

        const img = $(id);

        if (!img) {
            log(`${id} missing`, "error");
            return;
        }

        img.style.display = "block";
        img.style.width = "100%";
        img.style.height = "100%";
        img.style.objectFit = "cover";
        img.style.opacity = "1";
    });

    updateStats();
    restoreInspectionState();

    statsInterval = setInterval(
        updateStats,
        3000
    );

    pollLiveOnce();
    startLiveLoop();

    initShiftChart();
    refreshShiftChart();

    setInterval(
        refreshShiftChart,
        15000
    );

    log("Dashboard ready");
    const locationFilter =
        document.getElementById("locationFilter");

    const shiftFilter =
        document.getElementById("shiftFilter");
    const partNumberFilter =
        document.getElementById("partNumberFilter");

    locationFilter.addEventListener("change", () => {
        console.log(
            "Location:",
            locationFilter.value
        );
    });

    shiftFilter.addEventListener("change", () => {
        console.log(
            "Shift:",
            shiftFilter.value
        );
    });

    if (partNumberFilter) {
        partNumberFilter.addEventListener("change", async () => {
            console.log(
                "PartNumber:",
                partNumberFilter.value
            );
            const partNumber = partNumberFilter.value;
            if (partNumber) {
                await setActivePartOnServer(partNumber);
            }
        });
    }

    // ======================================
    // UPLOAD IMAGE HANDLER
    // ======================================

    const uploadBtn = $("uploadBtn");
    const uploadForm = $("uploadForm");
    const imageInput = $("imageInput");

    if (uploadBtn && uploadForm && imageInput) {
        uploadBtn.addEventListener("click", () => {
            imageInput.click();
        });

        imageInput.addEventListener("change", async (e) => {
            const file = e.target.files[0];
            if (!file) return;

            try {
                uploadBtn.disabled = true;
                uploadBtn.innerText = "Uploading...";

                const formData = new FormData();
                formData.append("image", file);
                
                const location = $("locationFilter")?.value || "Unknown";
                const shift = $("shiftFilter")?.value || "Unknown";
                const partNumber = getSelectedPartNumber();

                formData.append("location", location);
                formData.append("shift", shift);
                formData.append("part_number", partNumber);

                const response = await fetch("/upload", {
                    method: "POST",
                    body: formData
                });

                const data = await response.json();

                if (response.ok) {
                    log("Image uploaded successfully", "success");

                    // Show the comparison result in the LIVE READING panel right away,
                    // instead of waiting for the next poll of /api/latest-live.
                    applyLiveData({
                        component: data.part_name || data.part_number || "—",
                        ssim_score: data.ssim,
                        status: data.result
                    });

                    const savedMsg = data.inspection_id
                        ? "Saved to database."
                        : "Could not confirm database save — check logs.";
                    showNotification(
                        `Result: ${data.result} | Score: ${data.ssim} | ${savedMsg}`,
                        data.result === "Rejected" ? "warn" : "success"
                    );

                    // Reset form and button
                    uploadForm.reset();
                    uploadBtn.disabled = false;
                    uploadBtn.innerText = "Upload Image";

                    // Refresh stats/history so counts and the shift chart include this inspection
                    setTimeout(() => {
                        updateStats();
                        pollLiveOnce();
                    }, 500);
                } else {
                    const errorMsg = data.message || "Upload failed";
                    log(`Upload failed: ${errorMsg}`, "error");
                    alert(`✗ Upload failed: ${errorMsg}`);
                    uploadBtn.disabled = false;
                    uploadBtn.innerText = "Upload Image";
                }
            } catch (error) {
                log(`Upload error: ${error.message}`, "error");
                alert(`✗ Upload error: ${error.message}`);
                uploadBtn.disabled = false;
                uploadBtn.innerText = "Upload Image";
            }
        });
    } else {
        log("Upload elements not found in DOM", "warn");
    }

});

document.addEventListener(
    "visibilitychange",
    () => {

        if (!document.hidden) {

            log(
                "Tab active again"
            );

            pollLiveOnce();
            updateStats();

            if (cameraStarted) {

                loadCameraStreams([
                    "cam1",
                    "cam2",
                    "cam3"
                ]);
            }
        }
    }
);


// ======================================
// START INSPECTION
// ======================================

async function startInspection() {

    if (cameraStarted) {
        log("Already running", "warn");
        return;
    }

    const partNumber = getSelectedPartNumber();
    if (!partNumber) {
        log("Please select a Part Number before starting inspection.", "warn");
        alert("Please select a Part Number before starting inspection.");
        return;
    }

    const locked = await setActivePartOnServer(partNumber);
    if (!locked) {
        alert("Unable to lock selected Part Number on the server.");
        return;
    }

    try {

        $("liveStatus").innerText = "Starting...";
        $("liveStatus").className = "status waiting";

        $("startBtn").disabled = true;

        const response = await fetch(
            "/start_camera",
            {
                method: "POST",
                headers: {
                    "Content-Type": "application/json"
                }
            }
        );

        const data = await response.json();

        if (!response.ok || data.status === "error") {

            throw new Error(
                data.message || "Failed to start camera"
            );
        }

        await new Promise(
            resolve => setTimeout(resolve, 2000)
        );

        loadCameraStreams(data.cameras || []);

        cameraStarted = true;
        setSavedCameraState(true);

        $("liveStatus").innerText = "Running";
        $("liveStatus").className = "status running";

        $("startBtn").disabled = true;
        $("stopBtn").disabled = false;

        startLiveLoop();
        startAutoCaptureLoop();

        showNotification(
            "Inspection Started",
            "success"
        );

        log("Inspection started");

    } catch (error) {

        log(error.message, "error");

        $("liveStatus").innerText = "Failed";
        $("liveStatus").className = "status stopped";

        $("startBtn").disabled = false;

        alert(error.message);
    }
}

// ======================================
// CAMERA STREAMS
// ======================================

const ALL_CAMERAS = ["cam1", "cam2", "cam3"];

function loadCameraStreams(activeCameras) {

    if (!activeCameras) return;

    // Backend may return an object {cam1: ..., cam2: ...} or an array
    if (!Array.isArray(activeCameras)) {
        activeCameras = Object.keys(activeCameras);
    }

    const activeSet = new Set(activeCameras);

    // Mark cameras NOT returned by the backend as "not connected"
    ALL_CAMERAS.forEach(camId => {
        if (!activeSet.has(camId)) {
            _markCameraDisconnected(camId);
        }
    });

    // Start streams only for cameras the backend confirmed
    activeCameras.forEach(camId => {
        const img = $(camId);

        if (!img) {
            console.error(`${camId} not found in DOM`);
            return;
        }

        const url = `/video_feed/${camId}`;

        img.onload = () => {
            img.classList.add("loaded");
            const box = img.closest(".camera-box");
            if (box) {
                box.classList.add("active");
                box.classList.remove("disconnected");
                const label = box.querySelector(".cam-error-label");
                if (label) label.remove();
            }
            log(`Stream connected: ${camId}`);
        };

        img.onerror = () => {
            const box = img.closest(".camera-box");
            if (box) box.classList.remove("active");
            log(`Reconnecting ${camId}`, "warn");
            setTimeout(() => {
                img.src = `${url}?t=${Date.now()}`;
            }, 3000);
        };

        img.src = `${url}?t=${Date.now()}`;
    });
}

function _markCameraDisconnected(camId) {
    const img = $(camId);
    if (!img) return;

    img.src = "";
    img.classList.remove("loaded");

    const box = img.closest(".camera-box");
    if (box) {
        box.classList.remove("active");
        box.classList.add("disconnected");

        // Show a label inside the box if not already there
        if (!box.querySelector(".cam-error-label")) {
            const label = document.createElement("div");
            label.className = "cam-error-label";
            label.innerText = `${camId.toUpperCase()} — Not Connected`;
            label.style.cssText = `
                position:absolute; top:50%; left:50%;
                transform:translate(-50%,-50%);
                color:#ff4444; font-weight:bold;
                background:rgba(0,0,0,0.6);
                padding:8px 14px; border-radius:6px;
                pointer-events:none; font-size:0.9rem;
            `;
            box.style.position = "relative";
            box.appendChild(label);
        }
    }
    log(`${camId} not available from server`, "warn");
}
// ======================================
// STOP INSPECTION
// ======================================

async function stopInspection() {

    try {

        await fetch(
            "/stop_camera",
            {
                method: "POST"
            }
        );

        cameraStarted = false;
        setSavedCameraState(false);

        clearInterval(liveInterval);
        clearInterval(autoCaptureInterval);

        liveInterval = null;
        autoCaptureInterval = null;

        ["cam1", "cam2", "cam3"].forEach(id => {

            const img = $(id);

            if (!img) return;

            img.src = "";

            const box =
                img.closest(".camera-box");

            if (box) {
                box.classList.remove("active");
            }
        });

        $("liveStatus").innerText = "Stopped";
        $("liveStatus").className = "status stopped";

        $("startBtn").disabled = false;
        $("stopBtn").disabled = true;

        log("Inspection stopped");

    } catch (error) {

        log(error.message, "error");
    }
}

// ======================================
// LIVE DATA
// ======================================

async function pollLiveOnce() {

    try {

        const response =
            await fetch(
                "/api/latest-live"
            );

        if (!response.ok) return;

        const data =
            await response.json();

        applyLiveData(data);

    } catch (error) {

        log(
            error.message,
            "warn"
        );
    }
}

function applyLiveData(data) {

    if ($("liveComponent")) {

        $("liveComponent").innerText =
            data.component || "—";
    }

    if ($("liveHeight")) {

        $("liveHeight").innerText =
            data.ssim_score ??
            "—";
    }

    if ($("liveStatus")) {

        const status =
            (data.status || "").toLowerCase();

        $("liveStatus").innerText =
            data.status || "Waiting";

        if (status === "accepted") {

            $("liveStatus").className =
                "status accepted";

        } else if (
            status === "rejected"
        ) {

            $("liveStatus").className =
                "status stopped";

        } else {

            $("liveStatus").className =
                "status waiting";
        }
    }

    updateResultStamp(data.status);
}

function updateResultStamp(rawStatus) {

    const stampEl = $("resultStamp");
    if (!stampEl) return;

    const status = (rawStatus || "").toLowerCase();

    if (status === "accepted") {

        stampEl.innerText = "Accepted";
        stampEl.className = "show accepted";

    } else if (status === "rejected") {

        stampEl.innerText = "Rejected";
        stampEl.className = "show rejected";

    } else {

        // No live result yet (waiting/running) — hide the stamp.
        stampEl.className = "";
    }
}

function startLiveLoop() {

    clearInterval(liveInterval);

    liveInterval = setInterval(
        pollLiveOnce,
        2000
    );
}

// ======================================
// SHIFT CHART
// ======================================

function initShiftChart() {

    const canvas = $("shiftChart");

    if (!canvas || typeof Chart === "undefined") {
        return;
    }

    shiftChart = new Chart(
        canvas.getContext("2d"),
        {
            type: "bar",
            data: {
                labels: [],
                datasets: [
                    {
                        label: "Accepted",
                        data: [],
                        backgroundColor: "rgb(68, 156, 46)"
                    },
                    {
                        label: "Rejected",
                        data: [],
                        backgroundColor: "rgba(255,50,50,.7)"
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,

                plugins: {
                    legend: {
                        labels: {
                            color: "#000",
                            font: {
                                size: 14,
                                weight: "bold"
                            }
                        }
                    }
                },

                scales: {
                    x: {
                        ticks: {
                            color: "#000",
                            font: {
                                size: 13,
                                weight: "bold"
                            }
                        },
                        grid: {
                            color: "#ddd"
                        }
                    },
                    y: {
                        beginAtZero: true,
                        ticks: {
                            color: "#000",
                            font: {
                                size: 13,
                                weight: "bold"
                            }
                        },
                        grid: {
                            color: "#ddd"
                        }
                    }
                }
            }
        }
    );
}
async function refreshShiftChart() {

    if (!shiftChart) return;

    try {

        const response =
            await fetch(
                "/api/shift-stats"
            );

        if (!response.ok) return;

        const payload =
            await response.json();

        const rows =
            payload.data || [];

        shiftChart.data.labels =
            rows.map(r => r.shift);

        shiftChart.data.datasets[0].data =
            rows.map(r => r.accepted);

        shiftChart.data.datasets[1].data =
            rows.map(r => r.rejected);

        shiftChart.update();

    } catch (error) {

        log(
            error.message,
            "warn"
        );
    }
}

// ======================================
// AUTO CAPTURE
// ======================================

function getSelectedPartNumber() {
    return $("partNumberFilter")?.value || "";
}

async function setActivePartOnServer(partNumber) {
    if (!partNumber) {
        return false;
    }

    try {
        const response = await fetch("/api/inspection/active-part", {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({ part_number: partNumber })
        });
        const data = await response.json();
        if (!response.ok) {
            console.error("Failed to set active part:", data);
            return false;
        }
        return true;
    } catch (error) {
        console.error("setActivePartOnServer error:", error);
        return false;
    }
}

function startAutoCaptureLoop() {

    clearInterval(autoCaptureInterval);

    autoCaptureInterval =
        setInterval(async () => {

            if (!cameraStarted) {
                return;
            }

            try {
                const location = $("locationFilter")?.value || "Unknown";
                const shift = $("shiftFilter")?.value || "Unknown";
                const partNumber = getSelectedPartNumber();

                if (!partNumber) {
                    log("No Part Number selected, skipping capture.", "warn");
                    return;
                }

                const response =
                    await fetch(
                        "/capture_frame",
                        {
                            method: "POST",
                            headers: {
                                "Content-Type": "application/json"
                            },
                            body: JSON.stringify({ location, shift, part_number: partNumber })
                        }
                    );

                if (!response.ok) {
                    const errorData = await response.json().catch(() => null);
                    log(
                        `Capture request failed${errorData?.message ? `: ${errorData.message}` : ""}`,
                        "warn"
                    );
                    return;
                }

                const data =
                    await response.json();

                log(
                    `Captured: ${
                        data.image_name ||
                        data.filename ||
                        "Image"
                    }`
                );

            } catch (error) {

                log(
                    error.message,
                    "warn"
                );
            }

        }, 3000);
}

async function fetchWithTimeout(
    url,
    options = {},
    timeout = 10000
) {

    const controller =
        new AbortController();

    const id =
        setTimeout(
            () => controller.abort(),
            timeout
        );

    try {

        return await fetch(
            url,
            {
                ...options,
                signal: controller.signal
            }
        );

    } finally {

        clearTimeout(id);
    }
}

// ======================================
// STATISTICS
// ======================================

async function updateStats() {
    if (statsBusy) return;
    statsBusy = true;

    try {

        const response =
            await fetchWithTimeout("/api/defect-dashboard");

        if (!response.ok) return;

        const data =
            await response.json();

        const total =
            data.total || 0;

        const accepted =
            data.accepted || 0;

        const rejected =
            data.rejected || 0;

        $("totalCount").innerText =
            total;

        $("passCount").innerText =
            accepted;

        $("rejectCount").innerText =
            rejected;

        const passPercent =
            total > 0
                ? (accepted / total) * 100
                : 0;

        const rejectPercent =
            total > 0
                ? (rejected / total) * 100
                : 0;

        const passBar = $("passBar");
        const rejectBar = $("rejectBar");
        const passLabel = $("passPercentLabel");
        const rejectLabel = $("rejectPercentLabel");

        if (passBar) {
            passBar.style.setProperty("--progress", `${passPercent}%`);
            passBar.style.width = `${passPercent}%`;
        }

        if (rejectBar) {
            rejectBar.style.setProperty("--progress", `${rejectPercent}%`);
            rejectBar.style.width = `${rejectPercent}%`;
        }

        // Labels show the raw COUNT, not the percentage
        if (passLabel) passLabel.innerText = accepted;
        if (rejectLabel) rejectLabel.innerText = rejected;

        console.log("[Stats]", { total, accepted, rejected, passPercent, rejectPercent });

    } catch (error) {

        log(
            error.message,
            "warn"
        );
    }
    finally {   
        statsBusy = false;
    }
}

async function checkServer() {

    try {

        const res =
            await fetchWithTimeout(
                "/api/latest-live"
            );

        if (res.ok) {

            reconnectAttempts = 0;

            if (cameraStarted) {

                loadCameraStreams([
                    "cam1",
                    "cam2",
                    "cam3"
                ]);
            }
        }

    } catch {

        reconnectAttempts++;

        log(
            `Server offline (${reconnectAttempts})`,
            "warn"
        );
    }
}

setInterval(
    checkServer,
    5000
);

// ======================================
// CLEANUP
// ======================================

window.addEventListener("beforeunload", () => {
    clearInterval(liveInterval);
    clearInterval(statsInterval);
    clearInterval(autoCaptureInterval);
});
log("main.js loaded");