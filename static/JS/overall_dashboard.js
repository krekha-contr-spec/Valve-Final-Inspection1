document.addEventListener("DOMContentLoaded", function () {
    loadChart();

    document.getElementById("locationFilter").addEventListener("change", loadChart);
    document.getElementById("shiftFilter").addEventListener("change", loadChart);
    document.getElementById("timeFilter").addEventListener("change", loadChart);
});

let pieChartInstance = null;
let barChartInstance = null;

function loadChart() {
    const location = document.getElementById("locationFilter").value || "";
    const shift = document.getElementById("shiftFilter").value || "";
    const timeFilter = document.getElementById("timeFilter").value || "";
    const part_number = document.getElementById("partFilter").value || "";

    const apiURL = `/api/chart-data?location=${location}&part_number=${part_number}&shift=${shift}&time_filter=${timeFilter}`;
    console.log("Fetching: ", apiURL);

    fetch(apiURL)
        .then(response => response.json())
        .then(data => {
            document.getElementById("acceptedCount").innerText = data.accepted || 0;
            document.getElementById("rejectedCount").innerText = data.rejected || 0;
            document.getElementById("totalCount").innerText = data.total || 0;
            document.getElementById("partFilter").addEventListener("change", loadChart);

            loadPieChart(data);
            loadBarChart(data);
        })
        .catch(err => console.error("API Error:", err));
}

function loadPieChart(data) {
    const ctx = document.getElementById("pieChart").getContext("2d");

    if (pieChartInstance) pieChartInstance.destroy();

    pieChartInstance = new Chart(ctx, {
        type: "pie",
        data: {
            labels: ["Accepted", "Rejected"],
            datasets: [{
                data: [data.accepted, data.rejected],
                backgroundColor: ['#B6F500', '#FF4444']
            }]
        },
        options: {
            plugins: {
                datalabels: {
                    color: "#fff",
                    font: { weight: "bold", size: 14 },
                    formatter: (value) => value
                }
            }
        }
    });
}

function loadBarChart(data) {
    const ctx = document.getElementById("barChart").getContext("2d");

    if (barChartInstance) barChartInstance.destroy();

    barChartInstance = new Chart(ctx, {
        type: "bar",
        data: {
            labels: ["Total", "Accepted", "Rejected"],
            datasets: [{
                label: 'Inspection Count',
                data: [data.total, data.accepted, data.rejected],
                backgroundColor: ['#8a2be2', '#56DFCF', 'red']
            }]
        },
        options: {
            plugins: {
                datalabels: {
                    color: "#fff",
                    font: { weight: "bold", size: 14 },
                    anchor: "end",
                    align: "top"
                }
            },
            scales: {
                y: { beginAtZero: true }
            }
        }
    });
}
