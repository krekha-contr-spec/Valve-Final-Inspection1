// VisionMaster Tools Database

const TOOL_CATEGORIES = [
    {
        id: 'acquisition',
        name: 'Image Acquisition',
        icon: '📷',
        tools: [
            { id: 'local_image', name: 'Local Image', desc: 'Load from disk' },
            { id: 'camera_capture', name: 'Camera Capture', desc: 'Acquire from device' },
            { id: 'stream_input', name: 'Stream Input', desc: 'Live stream source' },
        ]
    },
    {
        id: 'localization',
        name: 'Localization',
        icon: '🎯',
        tools: [
            { id: 'pattern_match', name: 'Pattern Match', desc: 'Find pattern in image' },
            { id: 'blob_analysis', name: 'Blob Analysis', desc: 'Find blobs' },
            { id: 'edge_detection', name: 'Edge Detection', desc: 'Detect edges' },
            { id: 'contour_match', name: 'Contour Match', desc: 'Match contours' },
        ]
    },
    {
        id: 'measurement',
        name: 'Measurement',
        icon: '📏',
        tools: [
            { id: 'distance', name: 'Distance', desc: 'Point-to-point distance' },
            { id: 'circle_fit', name: 'Circle Fit', desc: 'Fit circle to points' },
            { id: 'line_fit', name: 'Line Fit', desc: 'Fit line to points' },
            { id: 'angle_measure', name: 'Angle Measure', desc: 'Measure angles' },
        ]
    },
    {
        id: 'identification',
        name: 'Identification',
        icon: '📱',
        tools: [
            { id: 'code_reader', name: 'Code Reader', desc: 'Read 1D/2D codes' },
            { id: 'ocr', name: 'OCR', desc: 'Optical Character Recognition' },
            { id: 'registration_learning', name: 'Registration Learning', desc: 'Learn registration patterns' },
            { id: 'deep_learning', name: 'Deep Learning', desc: 'Neural network inference' },
        ]
    },
    {
        id: 'color',
        name: 'Color Processing',
        icon: '🎨',
        tools: [
            { id: 'color_segment', name: 'Color Segment', desc: 'Segment by color' },
            { id: 'color_image_gen', name: 'Color Image Gen', desc: 'Generate color images' },
            { id: 'color_match', name: 'Color Match', desc: 'Match color patterns' },
        ]
    },
    {
        id: 'data',
        name: 'Data Processing',
        icon: '📊',
        tools: [
            { id: 'data_record', name: 'Data Record', desc: 'Record data logs' },
            { id: 'data_filter', name: 'Data Filter', desc: 'Filter data' },
            { id: 'data_sort', name: 'Data Sort', desc: 'Sort data' },
            { id: 'data_classify', name: 'Data Classify', desc: 'Classify data' },
        ]
    },
    {
        id: 'geometry',
        name: 'Geometry & Transform',
        icon: '📐',
        tools: [
            { id: 'coordinate_sys', name: 'Coordinate System', desc: 'Define coordinate space' },
            { id: 'transform', name: 'Transform', desc: 'Geometric transformation' },
            { id: 'roi', name: 'ROI Module', desc: 'Region of interest' },
        ]
    },
    {
        id: 'communication',
        name: 'Communication',
        icon: '🌐',
        tools: [
            { id: 'ethernet_ip', name: 'EtherNet/IP', desc: 'AB PLC Communication' },
            { id: 'modbus', name: 'Modbus TCP', desc: 'Modbus communication' },
            { id: 'http_api', name: 'HTTP API', desc: 'HTTP requests' },
            { id: 'mqtt', name: 'MQTT', desc: 'MQTT messaging' },
            { id: 'serial', name: 'Serial COM', desc: 'Serial communication' },
        ]
    },
    {
        id: 'logic',
        name: 'Logic & Control',
        icon: '⚙️',
        tools: [
            { id: 'script', name: 'Script', desc: 'Custom C#/Python script' },
            { id: 'branch', name: 'Branch', desc: 'Conditional branching' },
            { id: 'loop', name: 'Loop', desc: 'Looping control' },
            { id: 'switch', name: 'Switch', desc: 'Multi-way branching' },
            { id: 'group', name: 'Group', desc: 'Group modules' },
        ]
    },
    {
        id: 'io',
        name: 'Input/Output',
        icon: '📤',
        tools: [
            { id: 'display', name: 'Display', desc: 'Display output' },
            { id: 'save_image', name: 'Save Image', desc: 'Save to disk' },
            { id: 'export_data', name: 'Export Data', desc: 'Export results' },
        ]
    }
];

// Get all tools as flat array
function getAllTools() {
    let allTools = [];
    TOOL_CATEGORIES.forEach(cat => {
        allTools = allTools.concat(cat.tools);
    });
    return allTools;
}

// Search tools
function searchTools(query) {
    if (!query.trim()) return [];
    const q = query.toLowerCase();
    return getAllTools().filter(tool =>
        tool.name.toLowerCase().includes(q) ||
        tool.desc.toLowerCase().includes(q)
    );
}

// Render tools in sidebar
function renderTools(tools = TOOL_CATEGORIES) {
    const container = document.getElementById('toolsContainer');
    container.innerHTML = '';
    
    tools.forEach(category => {
        const categoryEl = document.createElement('div');
        categoryEl.className = 'tool-category';
        
        const headerBtn = document.createElement('button');
        headerBtn.className = 'category-header expanded';
        headerBtn.innerHTML = `<span class="category-icon">${category.icon}</span> ${category.name} (${category.tools.length})`;
        headerBtn.onclick = (e) => {
            e.preventDefault();
            headerBtn.classList.toggle('expanded');
            toolList.classList.toggle('expanded');
        };
        
        const toolList = document.createElement('div');
        toolList.className = 'tool-list expanded';
        
        category.tools.forEach(tool => {
            const toolEl = document.createElement('div');
            toolEl.className = 'tool-item';
            toolEl.draggable = true;
            toolEl.innerHTML = `<div class="tool-name">${tool.name}</div><div class="tool-desc">${tool.desc}</div>`;
            
            toolEl.addEventListener('dragstart', (e) => {
                e.dataTransfer.effectAllowed = 'move';
                e.dataTransfer.setData('tool', JSON.stringify(tool));
            });
            
            toolList.appendChild(toolEl);
        });
        
        categoryEl.appendChild(headerBtn);
        categoryEl.appendChild(toolList);
        container.appendChild(categoryEl);
    });
}

// Initialize tools on page load
document.addEventListener('DOMContentLoaded', () => {
    renderTools();
    
    // Handle search
    const searchInput = document.getElementById('searchTools');
    const clearBtn = document.getElementById('clearSearchBtn');
    
    searchInput.addEventListener('input', (e) => {
        const query = e.target.value;
        clearBtn.style.display = query ? 'block' : 'none';
        
        if (query.trim()) {
            const results = searchTools(query);
            const grouped = {
                id: 'search-results',
                name: `Search Results (${results.length})`,
                icon: '🔍',
                tools: results
            };
            renderTools([grouped]);
        } else {
            renderTools();
        }
    });
});

function clearSearch() {
    document.getElementById('searchTools').value = '';
    document.getElementById('clearSearchBtn').style.display = 'none';
    renderTools();
}
