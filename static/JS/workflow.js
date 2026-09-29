class WorkflowManager {
    constructor() {
        this.nodes = [];
        this.edges = [];
        this.nodeCounter = 1;
        this.history = [];
        this.historyIndex = -1;
        this.selectedNode = null;
        this.projectName = 'Untitled_Project';
        this.isRunning = false;
        this.isDrawingConnection = false;
        this.connectionSourceNode = null;
        this.tempConnection = null;
        this.isDraggingNode = false;
        this.draggedNodeId = null;
        this.dragOffset = { x: 0, y: 0 };

        this.canvas = document.getElementById('canvas');
        this.nodesContainer = document.getElementById('nodesContainer');
        this.canvasSvg = document.getElementById('canvasSvg');

        this.initEventListeners();
        this.loadDemo();
    }

    initEventListeners() {
        this.canvas.addEventListener('dragover', (e) => this.handleDragOver(e));
        this.canvas.addEventListener('drop', (e) => this.handleDrop(e));
        this.canvas.addEventListener('click', (e) => {
            if (e.target === this.canvas || e.target === this.canvasSvg) {
                this.selectNode(null);
            }
        });
        this.canvas.addEventListener('mousemove', (e) => this.handleMouseMove(e));
        this.canvas.addEventListener('mouseup', (e) => this.handleMouseUp(e));
        this.canvas.addEventListener('dragstart', (e) => {
            if (!e.target.classList.contains('tool')) {
                e.preventDefault();
            }
        });
    }

    handleDragOver(e) {
        e.preventDefault();
        e.dataTransfer.dropEffect = 'move';
    }

    handleDrop(e) {
        e.preventDefault();
        const toolData = e.dataTransfer.getData('tool');
        if (!toolData) return;

        const tool = JSON.parse(toolData);
        const rect = this.canvas.getBoundingClientRect();
        const x = e.clientX - rect.left - 50; // Center the node
        const y = e.clientY - rect.top - 20;

        this.addNode(tool.name, x, y);
    }

    addNode(label, x, y) {
        const node = {
            id: String(this.nodeCounter++),
            label: label,
            x: x,
            y: y,
            status: 'ready',
            enabled: true,
            timeout: 200,
            retry: 0,
            skipError: false,
            notes: ''
        };

        this.nodes.push(node);
        this.saveHistory();
        this.render();
        this.showToast(`✓ Added ${label}`);
    }

    deleteNode(id) {
        if (!id) return;

        this.nodes = this.nodes.filter(n => n.id !== id);
        this.edges = this.edges.filter(e => e.source !== id && e.target !== id);

        if (this.selectedNode === id) {
            this.selectNode(null);
        }

        this.saveHistory();
        this.render();
        this.showToast('✗ Module deleted');
    }

    selectNode(id) {
        this.selectedNode = id;
        this.render();

        if (id) {
            const node = this.nodes.find(n => n.id === id);
            this.showNodeProperties(node);
        } else {
            document.getElementById('rightSidebar').style.display = 'none';
        }
    }

    showNodeProperties(node) {
        if (!node) return;

        const sidebar = document.getElementById('rightSidebar');
        sidebar.style.display = 'flex';

        document.getElementById('moduleName').textContent = node.label;
        document.getElementById('moduleId').textContent = `ID: ${node.id}`;
        document.getElementById('moduleEnabled').checked = node.enabled;
        document.getElementById('moduleTimeout').value = node.timeout;
        document.getElementById('moduleRetry').value = node.retry;
        document.getElementById('moduleSkipError').checked = node.skipError;
        document.getElementById('moduleNotes').value = node.notes;
    }
    startConnection(nodeId, e) {
        e.preventDefault();
        e.stopPropagation();

        this.isDrawingConnection = true;
        this.connectionSourceNode = nodeId;

        const node = this.nodes.find(n => n.id === nodeId);
        const rect = this.canvas.getBoundingClientRect();

        this.tempConnection = {
            x1: node.x + 100,
            y1: node.y + 20,
            x2: e.clientX - rect.left,
            y2: e.clientY - rect.top
        };

        this.render();
    }

    handleMouseMove(e) {
        if (this.isDrawingConnection && this.tempConnection) {
            const rect = this.canvas.getBoundingClientRect();
            this.tempConnection.x2 = e.clientX - rect.left;
            this.tempConnection.y2 = e.clientY - rect.top;
            this.render();
        }
        if (this.isDraggingNode && this.draggedNodeId) {
            const rect = this.canvas.getBoundingClientRect();
            const node = this.nodes.find(n => n.id === this.draggedNodeId);
            if (node) {
                node.x = e.clientX - rect.left - this.dragOffset.x;
                node.y = e.clientY - rect.top - this.dragOffset.y;
                this.render();
            }
        }
    }

    handleMouseUp(e) {
        if (this.isDrawingConnection) {
            const target = e.target.closest('.node');
            if (target) {
                const targetNodeId = target.getAttribute('data-node-id');
                if (targetNodeId && targetNodeId !== this.connectionSourceNode) {
                    this.addConnection(this.connectionSourceNode, targetNodeId);
                }
            }

            this.isDrawingConnection = false;
            this.connectionSourceNode = null;
            this.tempConnection = null;
            this.render();
        }
        if (this.isDraggingNode) {
            this.isDraggingNode = false;
            this.draggedNodeId = null;
            this.saveHistory();
        }
    }

    startNodeDrag(nodeId, e) {
        e.stopPropagation();
        this.isDraggingNode = true;
        this.draggedNodeId = nodeId;

        const node = this.nodes.find(n => n.id === nodeId);
        const rect = this.canvas.getBoundingClientRect();

        this.dragOffset = {
            x: e.clientX - rect.left - node.x,
            y: e.clientY - rect.top - node.y
        };
    }

    addConnection(sourceId, targetId) {
        const exists = this.edges.some(e => e.source === sourceId && e.target === targetId);
        if (!exists && sourceId !== targetId) {
            this.edges.push({ source: sourceId, target: targetId });
            this.saveHistory();
            this.render();
            this.showToast('→ Connection created');
        }
    }

    deleteConnection(sourceId, targetId) {
        this.edges = this.edges.filter(e => !(e.source === sourceId && e.target === targetId));
        this.saveHistory();
        this.render();
        this.showToast('Connection deleted');
    }

    saveHistory() {
        this.history = this.history.slice(0, this.historyIndex + 1);
        this.history.push({
            nodes: JSON.parse(JSON.stringify(this.nodes)),
            edges: JSON.parse(JSON.stringify(this.edges))
        });
        this.historyIndex++;
    }

    undo() {
        if (this.historyIndex > 0) {
            this.historyIndex--;
            this.loadFromHistory();
            this.showToast('↶ Undo');
        }
    }

    redo() {
        if (this.historyIndex < this.history.length - 1) {
            this.historyIndex++;
            this.loadFromHistory();
            this.showToast('↷ Redo');
        }
    }
    loadFromHistory() {
        const state = this.history[this.historyIndex];
        this.nodes = JSON.parse(JSON.stringify(state.nodes));
        this.edges = JSON.parse(JSON.stringify(state.edges));
        this.render();
    }

    render() {
        this.nodesContainer.innerHTML = '';
        this.nodes.forEach(node => {
            const nodeEl = document.createElement('div');
            nodeEl.className = 'node' +
                (this.selectedNode === node.id ? ' selected' : '') +
                (node.status === 'success' ? ' success' : '');
            nodeEl.style.left = node.x + 'px';
            nodeEl.style.top = node.y + 'px';
            nodeEl.setAttribute('data-node-id', node.id);

            nodeEl.innerHTML = `
                <div class="node-label">${node.label}</div>
                <div class="connection-point output" data-node-id="${node.id}" title="Drag to connect"></div>
            `;
            nodeEl.addEventListener('click', (e) => {
                e.stopPropagation();
                this.selectNode(node.id);
            });
            nodeEl.addEventListener('mousedown', (e) => {
                if (!e.target.classList.contains('connection-point')) {
                    this.startNodeDrag(node.id, e);
                }
            });
            const connectionPoint = nodeEl.querySelector('.connection-point');
            connectionPoint.addEventListener('mousedown', (e) => {
                this.startConnection(node.id, e);
            });

            this.nodesContainer.appendChild(nodeEl);
        });
        this.canvasSvg.innerHTML = `
            <defs>
                <marker id="arrowhead" markerWidth="10" markerHeight="10" refX="9" refY="3" orient="auto">
                    <polygon points="0 0, 10 3, 0 6" fill="#64748b" />
                </marker>
            </defs>
        `;

        this.edges.forEach(edge => {
            const source = this.nodes.find(n => n.id === edge.source);
            const target = this.nodes.find(n => n.id === edge.target);

            if (source && target) {
                const x1 = source.x + 100;
                const y1 = source.y + 20;
                const x2 = target.x;
                const y2 = target.y + 20;

                const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
                path.setAttribute('class', 'connection');
                path.setAttribute('d', `M ${x1} ${y1} L ${x2} ${y2}`);
                path.setAttribute('marker-end', 'url(#arrowhead)');
                path.addEventListener('click', (e) => {
                    e.stopPropagation();
                    if (window.confirm('Delete this connection?')) {
                        this.deleteConnection(edge.source, edge.target);
                    }
                });
                path.style.cursor = 'pointer';

                this.canvasSvg.appendChild(path);
            }
        });
        if (this.tempConnection) {
            const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
            path.setAttribute('class', 'connection temp-connection');
            path.setAttribute('d', `M ${this.tempConnection.x1} ${this.tempConnection.y1} L ${this.tempConnection.x2} ${this.tempConnection.y2}`);
            path.setAttribute('stroke', '#3b82f6');
            path.setAttribute('stroke-width', '2');
            path.setAttribute('stroke-dasharray', '5,5');
            path.setAttribute('fill', 'none');
            this.canvasSvg.appendChild(path);
        }

        this.updateStats();
    }

    updateStats() {
        document.getElementById('statsText').textContent = `Nodes: ${this.nodes.length} | Connections: ${this.edges.length}`;
    }

    async runWorkflow() {
        if (this.nodes.length === 0) {
            this.showToast('❌ Workflow is empty');
            return;
        }

        this.isRunning = true;
        document.getElementById('runBtn').disabled = true;
        document.getElementById('runBtn').textContent = '⟳ Running...';

        const startTime = Date.now();

        try {
            await new Promise(resolve => setTimeout(resolve, 2000));

            const endTime = Date.now();
            const duration = endTime - startTime;
            this.nodes.forEach(node => {
                node.status = 'success';
            });
            this.render();

            document.getElementById('execTimeText').textContent = `⏱ ${duration}ms`;
            this.showToast(`✓ Executed in ${duration}ms (${this.nodes.length} modules)`);
            setTimeout(() => {
                this.nodes.forEach(node => {
                    node.status = 'ready';
                });
                this.render();
                document.getElementById('execTimeText').textContent = '';
            }, 2000);

        } catch (error) {
            this.showToast('❌ Execution failed');
        } finally {
            this.isRunning = false;
            document.getElementById('runBtn').disabled = false;
            document.getElementById('runBtn').textContent = '▶ Run';
        }
    }

    clearCanvas() {
        if (!window.confirm('Clear all modules?')) return;

        this.nodes = [];
        this.edges = [];
        this.selectedNode = null;
        this.saveHistory();
        this.render();
        document.getElementById('rightSidebar').style.display = 'none';
        this.showToast('Canvas cleared');
    }

    newProject() {
        if (this.nodes.length > 0 && !window.confirm('Start new project?')) return;

        this.nodes = [];
        this.edges = [];
        this.nodeCounter = 1;
        this.selectedNode = null;
        this.projectName = 'Untitled_Project';
        this.history = [];
        this.historyIndex = -1;

        this.render();
        document.getElementById('projectName').textContent = this.projectName;
        document.getElementById('rightSidebar').style.display = 'none';
        this.showToast('New project created');
    }

    loadDemo() {
        this.nodes = [
            { id: '1', label: 'Camera Capture', x: 250, y: 20, status: 'ready', enabled: true, timeout: 200, retry: 0, skipError: false, notes: '' },
            { id: '2', label: 'Pattern Match', x: 250, y: 100, status: 'ready', enabled: true, timeout: 200, retry: 0, skipError: false, notes: '' },
            { id: '3', label: 'Coordinate Sys', x: 250, y: 200, status: 'ready', enabled: true, timeout: 200, retry: 0, skipError: false, notes: '' },
            { id: '4', label: 'Distance Measure', x: 100, y: 300, status: 'ready', enabled: true, timeout: 200, retry: 0, skipError: false, notes: '' },
            { id: '5', label: 'Tolerance Check', x: 400, y: 300, status: 'ready', enabled: true, timeout: 200, retry: 0, skipError: false, notes: '' },
            { id: '6', label: 'EtherNet/IP Out', x: 250, y: 450, status: 'ready', enabled: true, timeout: 200, retry: 0, skipError: false, notes: '' },
        ];

        this.edges = [
            { source: '1', target: '2' },
            { source: '2', target: '3' },
            { source: '3', target: '4' },
            { source: '3', target: '5' },
            { source: '4', target: '6' },
            { source: '5', target: '6' },
        ];

        this.nodeCounter = 7;
        this.projectName = 'QR_Code_Detection';
        this.selectedNode = null;
        this.history = [{ nodes: JSON.parse(JSON.stringify(this.nodes)), edges: JSON.parse(JSON.stringify(this.edges)) }];
        this.historyIndex = 0;

        this.render();
        document.getElementById('projectName').textContent = this.projectName;
        this.showToast('Demo workflow loaded');
    }

    exportProject() {
        const data = {
            name: this.projectName,
            timestamp: new Date().toISOString(),
            nodes: this.nodes,
            edges: this.edges
        };

        const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `${this.projectName}.json`;
        a.click();

        this.showToast(`📥 Exported: ${this.projectName}.json`);
    }

    importProject() {
        const input = document.getElementById('fileInput');
        input.click();

        input.onchange = (e) => {
            const file = e.target.files[0];
            if (!file) return;

            const reader = new FileReader();
            reader.onload = (event) => {
                try {
                    const data = JSON.parse(event.target.result);
                    this.nodes = data.nodes || [];
                    this.edges = data.edges || [];
                    this.projectName = data.name || 'Imported_Project';
                    this.nodeCounter = Math.max(...this.nodes.map(n => parseInt(n.id))) + 1 || 1;
                    this.selectedNode = null;
                    this.history = [{ nodes: JSON.parse(JSON.stringify(this.nodes)), edges: JSON.parse(JSON.stringify(this.edges)) }];
                    this.historyIndex = 0;

                    this.render();
                    document.getElementById('projectName').textContent = this.projectName;
                    document.getElementById('rightSidebar').style.display = 'none';
                    this.showToast(`📤 Imported: ${this.projectName}`);
                } catch (err) {
                    this.showToast('❌ Failed to import project');
                }
            };
            reader.readAsText(file);
        };
    }

    showToast(message) {
        const toast = document.createElement('div');
        toast.style.cssText = `
            position: fixed;
            bottom: 20px;
            right: 20px;
            background: #1a1f2e;
            color: #e2e8f0;
            padding: 12px 16px;
            border-radius: 4px;
            border: 1px solid #2d3748;
            font-size: 12px;
            z-index: 10000;
            animation: slideIn 0.3s ease-in-out;
        `;
        toast.textContent = message;
        document.body.appendChild(toast);

        setTimeout(() => {
            toast.style.animation = 'slideOut 0.3s ease-in-out';
            setTimeout(() => toast.remove(), 300);
        }, 2000);
    }
}
let workflow;
document.addEventListener('DOMContentLoaded', () => {
    workflow = new WorkflowManager();
    window.newProject = () => workflow.newProject();
    window.loadDemo = () => workflow.loadDemo();
    window.importProject = () => workflow.importProject();
    window.exportProject = () => workflow.exportProject();
    window.undo = () => workflow.undo();
    window.redo = () => workflow.redo();
    window.deleteNode = () => workflow.deleteNode(workflow.selectedNode);
    window.clearCanvas = () => workflow.clearCanvas();
    window.runWorkflow = () => workflow.runWorkflow();
    window.selectNode = (id) => workflow.selectNode(id);
    window.applyChanges = () => {
        const node = workflow.nodes.find(n => n.id === workflow.selectedNode);
        if (node) {
            node.enabled = document.getElementById('moduleEnabled').checked;
            node.timeout = parseInt(document.getElementById('moduleTimeout').value);
            node.retry = parseInt(document.getElementById('moduleRetry').value);
            node.skipError = document.getElementById('moduleSkipError').checked;
            node.notes = document.getElementById('moduleNotes').value;
            workflow.saveHistory();
            workflow.showToast('✓ Changes applied');
        }
    };
    window.resetModule = () => {
        const node = workflow.nodes.find(n => n.id === workflow.selectedNode);
        if (node) {
            node.enabled = true;
            node.timeout = 200;
            node.retry = 0;
            node.skipError = false;
            node.notes = '';
            workflow.showNodeProperties(node);
            workflow.showToast('✓ Reset to default');
        }
    };
    window.switchTab = (tab) => {
        document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
        document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active'));

        const contentEl = document.getElementById(tab + 'Tab');
        const btnEl = event.target;

        if (contentEl) contentEl.classList.add('active');
        if (btnEl) btnEl.classList.add('active');
    };

    const style = document.createElement('style');
    style.textContent = `
        @keyframes slideIn {
            from { transform: translateX(400px); opacity: 0; }
            to { transform: translateX(0); opacity: 1; }
        }
        @keyframes slideOut {
            from { transform: translateX(0); opacity: 1; }
            to { transform: translateX(400px); opacity: 0; }
        }
        
        /* Connection point styling */
        .connection-point {
            position: absolute;
            right: -8px;
            top: 50%;
            transform: translateY(-50%);
            width: 16px;
            height: 16px;
            background: #3b82f6;
            border: 2px solid #1e293b;
            border-radius: 50%;
            cursor: crosshair;
            z-index: 10;
            transition: all 0.2s;
        }
        
        .connection-point:hover {
            background: #60a5fa;
            transform: translateY(-50%) scale(1.2);
        }
        
        .connection {
            stroke: #64748b;
            stroke-width: 2;
            fill: none;
            pointer-events: stroke;
            transition: stroke 0.2s;
        }
        
        .connection:hover {
            stroke: #ef4444;
            stroke-width: 3;
        }
        
        .temp-connection {
            stroke: #3b82f6;
            stroke-width: 2;
            stroke-dasharray: 5,5;
            animation: dash 0.5s linear infinite;
        }
        
        @keyframes dash {
            to {
                stroke-dashoffset: -10;
            }
        }
        
        .node {
            cursor: move;
            user-select: none;
        }
        
        .node.selected {
            box-shadow: 0 0 0 2px #3b82f6;
        }
        
        .node.success {
            box-shadow: 0 0 0 2px #10b981;
        }
    `;
    document.head.appendChild(style);
});