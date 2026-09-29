const API_BASE = "http://127.0.0.1:7000/api";

document.addEventListener('DOMContentLoaded', () => {

    const showGridCheckbox = document.getElementById('showGrid');
    const showMinimapCheckbox = document.getElementById('showMinimap');
    const showPanelCheckbox = document.getElementById('showPanel');
    const rightSidebar = document.getElementById('rightSidebar');
    const canvas = document.getElementById('canvas');

    showGridCheckbox.addEventListener('change', (e) => {
        canvas.style.backgroundImae = e.target.checked
            ? "url('data:image/svg+xml,<svg width=\"20\" height=\"20\" xmlns=\"http://www.w3.org/2000/svg\"><rect x=\"0\" y=\"0\" width=\"20\" height=\"20\" fill=\"%230f1115\"/><circle cx=\"2\" cy=\"2\" r=\"0.5\" fill=\"%23334155\"/></svg>')"
            : "none";
    });

    showMinimapCheckbox.addEventListener('change', (e) => {
        console.log('Minimap toggle:', e.target.checked);
    });

    showPanelCheckbox.addEventListener('change', (e) => {
        if (!window.workflow?.selectedNode) return;
        rightSidebar.style.display = e.target.checked ? 'flex' : 'none';
    });

    document.addEventListener('keydown', (e) => {
        if (e.ctrlKey || e.metaKey) {
            if (e.key === 's') {
                e.preventDefault();
                saveProjectToBackend();
            }
            if (e.key === 'z' && !e.shiftKey) {
                e.preventDefault();
                workflow.undo();
            }
            if ((e.key === 'z' && e.shiftKey) || e.key === 'y') {
                e.preventDefault();
                workflow.redo();
            }
        }

        if (e.key === 'Delete' && workflow.selectedNode) {
            workflow.deleteNode(workflow.selectedNode);
        }
    });

    console.log('🚀 VisionMaster v4.4.0 Ready (Backend Connected)');
});
function saveProjectToBackend() {
    const projectData = {
        name: workflow.projectName,
        nodes: workflow.nodes,
        edges: workflow.edges
    };

    fetch(`${API_BASE}/project/save`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(projectData)
    })
        .then(res => res.json())
        .then(() => {
            workflow.showToast("💾 Project saved to backend");
        })
        .catch(err => {
            console.error(err);
            workflow.showToast("❌ Save failed");
        });
}

function loadDemoFromBackend() {
    fetch(`${API_BASE}/project/demo`)
        .then(res => res.json())
        .then(data => {
            workflow.nodes = data.nodes || [];
            workflow.edges = data.connections || [];
            workflow.projectName = data.name || "Demo_Project";

            workflow.history = [{
                nodes: JSON.parse(JSON.stringify(workflow.nodes)),
                edges: JSON.parse(JSON.stringify(workflow.edges))
            }];
            workflow.historyIndex = 0;

            workflow.render();
            document.getElementById("projectName").textContent = workflow.projectName;
            workflow.showToast("⭕ Demo loaded from backend");
        });
}
function runWorkflowBackend() {
    const payload = {
        nodes: workflow.nodes,
        edges: workflow.edges
    };

    document.getElementById("runBtn").disabled = true;
    document.getElementById("runBtn").textContent = "⟳ Running...";

    fetch(`${API_BASE}/workflow/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
    })
        .then(res => res.json())
        .then(data => {
            document.getElementById("execTimeText").textContent =
                `⏱ ${data.execution_time_ms} ms`;

            workflow.nodes.forEach(n => n.status = "success");
            workflow.render();

            workflow.showToast(`✓ Executed ${data.nodes_executed} modules`);

            setTimeout(() => {
                workflow.nodes.forEach(n => n.status = "ready");
                workflow.render();
                document.getElementById("execTimeText").textContent = "";
            }, 2000);
        })
        .catch(() => {
            workflow.showToast("❌ Execution failed");
        })
        .finally(() => {
            document.getElementById("runBtn").disabled = false;
            document.getElementById("runBtn").textContent = "▶ Run";
        });
}

window.exportProject = saveProjectToBackend;
window.loadDemo = loadDemoFromBackend;
window.runWorkflow = runWorkflowBackend;
