let defectChart = null;

async function fetchDefectDashboardTypes(partNumber = "", timeFilter = "") {
    try {
        const url = `/api/defect-dashboard/types?part_number=${encodeURIComponent(partNumber)}&time_filter=${encodeURIComponent(timeFilter)}`;
        const response = await fetch(url);
        const result = await response.json();

        if (result.error) {
            console.error("Defect API error:", result.error);
            return;
        }

        if (document.getElementById("defectDashboardFilters")) {
            document.getElementById("defectDashboardFilters").innerText =
                `Part Number: ${partNumber || "All"} | Time Filter: ${timeFilter || "All"}`;
        }

        const chartLabels = result.chart_labels || [];
        const chartValues = result.chart_values || [];
        const rawData = result.data || [];

        const defectOrder = [
            "Face Damage", "Head Damage", "Seat Damage", "Neck Damage",
            "Stem Damage", "Groove Damage", "End Chamfer", "Tip End",
            "Bent Valve", "Crack", "Scratch", "Discoloration", "Radius Damage"
        ];

        // Vibrant, distinct colors for each defect type
        const colorMap = {
            "Face Damage": "#FF6B6B",           // Red
            "Head Damage": "#4ECDC4",           // Teal
            "Seat Damage": "#FF1493",           // Deep Pink
            "Neck Damage": "#FF8C00",           // Dark Orange
            "Stem Damage": "#20B2AA",           // Light Sea Green
            "Groove Damage": "#8B008B",         // Dark Magenta
            "End Chamfer": "#00CED1",           // Dark Turquoise
            "Tip End": "#1E90FF",               // Dodger Blue
            "Bent Valve": "#9370DB",            // Medium Purple
            "Crack": "#32CD32",                 // Lime Green
            "Scratch": "#DA70D6",               // Orchid
            "Discoloration": "#87CEEB",         // Sky Blue
            "Radius Damage": "#FFD700"          // Gold
        };

        const labelMap = {
            "Face_Damage": "Face Damage",
            "Head_Damage": "Head Damage",
            "Seat_Damage": "Seat Damage",
            "Neck_Damage": "Neck Damage",
            "Stem_Damage": "Stem Damage",
            "Groove_Damage": "Groove Damage",
            "End_Chamfer": "End Chamfer",
            "Tip_Damage": "Tip End",
            "Tip_End": "Tip End",
            "Bend_Damage": "Bent Valve",
            "Bent_Valve": "Bent Valve",
            "Crack_Damage": "Crack",
            "Scratch_Damage": "Scratch",
            "Discoloration_Damage": "Discoloration",
            "Radius_Damage": "Radius Damage"
        };

        // Build a label -> count map from whatever the API gave us, matching
        // each entry by its ACTUAL defect label (not by array position).
        // This is what fixes counts landing on the wrong bar.
        const defectCountMap = {};

        if (chartLabels.length > 0 && chartValues.length > 0) {
            chartLabels.forEach((rawLabel, i) => {
                if (!rawLabel) return;
                const standardLabel = labelMap[rawLabel.trim()] || rawLabel.trim();
                defectCountMap[standardLabel] = (defectCountMap[standardLabel] || 0) + Math.round(chartValues[i]);
            });
        } else {
            rawData.forEach(item => {
                if (item.label) {
                    const standardLabel = labelMap[item.label.trim()] || item.label.trim();
                    defectCountMap[standardLabel] = (defectCountMap[standardLabel] || 0) + Math.round(item.count);
                }
            });
        }

        // Now build counts in the exact same order as defectOrder, so each
        // count always lines up with the label it actually belongs to.
        const counts = defectOrder.map(defect => defectCountMap[defect] || 0);

        const colors = defectOrder.map(defect => colorMap[defect] || "#999999");

        const ctx = document.getElementById('defectDashboardChart').getContext('2d');

        if (defectChart) {
            defectChart.data.labels = defectOrder;
            defectChart.data.datasets[0].data = counts;
            defectChart.data.datasets[0].backgroundColor = colors;
            defectChart.data.datasets[0].borderColor = colors;
            defectChart.update();
        } else {
            defectChart = new Chart(ctx, {
                type: 'bar',
                data: {
                    labels: defectOrder,
                    datasets: [{
                        label: 'Count',
                        data: counts,
                        backgroundColor: colors,
                        borderColor: colors,
                        borderWidth: 2
                    }]
                },
                options: {
                    responsive: true,
                    scales: {
                        x: {
                            ticks: { 
                                color: '#212121', 
                                font: { weight: 'bold', size: 14 }
                            },
                            title: {
                                display: true,
                                text: 'Defect Type',
                                color: 'green',
                                font: { weight: 'bold', size: 28, style: 'italic' }
                            }
                        },
                        y: {
                            beginAtZero: true,
                            ticks: { 
                                stepSize: 1, 
                                color: '#212121',
                                font: { weight: 'bold', size: 14 }
                            },
                            title: {
                                display: true,
                                text: 'Count',
                                color: 'green',
                                font: { weight: 'bold', size: 28, style: 'italic' }
                            }
                        }
                    },
                    plugins: { 
                        legend: { 
                            display: false 
                        }
                    }
                }
            });
        }
    } catch (err) {
        console.error("Defect chart fetch error:", err);
    }
}

function loadDefectDashboard() {
    let partNumber = document.getElementById("defectPartFilter")?.value || "";
    let timeFilter = document.getElementById("defectTimeFilter")?.value || "";

    if (partNumber.toLowerCase() === "none") partNumber = "";
    if (timeFilter.toLowerCase() === "none") timeFilter = "";

    fetchDefectDashboardTypes(partNumber, timeFilter);
}

function goToDashboard() {
    console.log("Button clicked - navigating to /dashboard");
    window.location.href = "/dashboard";
}

// Wait for DOM to be fully loaded
document.addEventListener("DOMContentLoaded", function() {
    console.log("DOM loaded - setting up event listeners");
    
    loadDefectDashboard();
    
    // Setup dashboard button listener
    const dashboardBtn = document.getElementById("goToDashboardBtn");
    if (dashboardBtn) {
        console.log("Dashboard button found and setting up click listener");
        dashboardBtn.addEventListener("click", function(e) {
            e.preventDefault();
            goToDashboard();
        });
    } else {
        console.warn("Dashboard button not found!");
    }
    
    // Setup filter listeners
    const partFilter = document.getElementById("defectPartFilter");
    if (partFilter) {
        partFilter.addEventListener("change", loadDefectDashboard);
    }
    
    const timeFilter = document.getElementById("defectTimeFilter");
    if (timeFilter) {
        timeFilter.addEventListener("change", loadDefectDashboard);
    }
});

// Auto-refresh every 10 seconds
setInterval(loadDefectDashboard, 10000);