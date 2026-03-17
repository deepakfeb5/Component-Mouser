let bomData = [];
let apiUrl = "https://YOUR_RENDER_URL/api/bom";   // ← update after deployment!

async function loadBOM() {
    const res = await fetch(apiUrl);
    const data = await res.json();

    bomData = data.table;

    renderTable(bomData);
    document.getElementById("totalCost").innerText =
        "$" + data.total_cost.toLocaleString();
}

function renderTable(rows) {
    if (!rows.length) return;

    let html = "<table border='1' style='width:100%; border-collapse:collapse;'>";

    // Header
    html += "<tr style='background:#e0e0e0'>";
    Object.keys(rows[0]).forEach(col => {
        html += `<th style="padding:6px; text-align:left">${col}</th>`;
    });
    html += "</tr>";

    // Rows
    rows.forEach(r => {
        html += "<tr>";
        Object.values(r).forEach(val => {
            html += `<td style="padding:6px">${val}</td>`;
        });
        html += "</tr>";
    });

    html += "</table>";
    document.getElementById("bomTable").innerHTML = html;
}

// Search
document.getElementById("searchInput").addEventListener("keyup", function () {
    const q = this.value.toLowerCase();
    const filtered = bomData.filter(item =>
        JSON.stringify(item).toLowerCase().includes(q)
    );
    renderTable(filtered);
});

// CSV Download
document.getElementById("downloadBtn").addEventListener("click", () => {
    let csv = Object.keys(bomData[0]).join(",") + "\n";

    bomData.forEach(row => {
        csv += Object.values(row).join(",") + "\n";
    });

    const blob = new Blob([csv], { type: "text/csv" });
    const url = URL.createObjectURL(blob);

    const a = document.createElement("a");
    a.href = url;
    a.download = "bom_results.csv";
    a.click();
});

window.onload = loadBOM;
