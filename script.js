// ✅ UPDATE THIS with your actual Render backend URL
const API_BASE = "https://<your-service>.onrender.com";
const API_URL = `${API_BASE}/api/bom`;

let bomData = []; // Stores full API response

// ✅ Load BOM from Flask API
async function loadBOM() {
    try {
        const res = await fetch(API_URL);
        const data = await res.json();

        bomData = data.table;   // Save for filtering + CSV export

        renderTable(bomData);   // Build table
        updateTotalCost(data.total_cost);  // Show total BOM price

    } catch (err) {
        console.error("API Fetch Error:", err);
        document.getElementById("bomTable").innerHTML =
            "<p style='color:red'>Failed to load BOM from API.</p>";
    }
}

// ✅ Render HTML Table
function renderTable(rows) {
    if (!rows.length) return;

    let html = "<table border='1' style='width:100%;border-collapse:collapse;'>";

    // Header
    html += "<tr style='background:#e0e0e0'>";
    Object.keys(rows[0]).forEach(col => {
        html += `<th style="padding:6px;text-align:left">${col}</th>`;
    });
    html += "</tr>";

    // Rows
    rows.forEach(row => {
        html += "<tr>";
        Object.values(row).forEach(val => {
            html += `<td style="padding:6px">${val}</td>`;
        });
        html += "</tr>";
    });

    html += "</table>";

    document.getElementById("bomTable").innerHTML = html;
}

// ✅ Update Total Price Box
function updateTotalCost(amount) {
    document.getElementById("totalCost").innerText =
        "$" + amount.toLocaleString();
}

// ✅ Search Filter
document.getElementById("searchInput").addEventListener("keyup", function () {
    const q = this.value.toLowerCase();

    const filtered = bomData.filter(row =>
        JSON.stringify(row).toLowerCase().includes(q)
    );

    renderTable(filtered);
});

// ✅ Download Results CSV
document.getElementById("downloadBtn").addEventListener("click", () => {
    if (!bomData.length) return;

    const headers = Object.keys(bomData[0]).join(",");
    const rows = bomData.map(r => Object.values(r).join(",")).join("\n");
    const csv = headers + "\n" + rows;

    const blob = new Blob([csv], { type: "text/csv" });
    const url = URL.createObjectURL(blob);

    const a = document.createElement("a");
    a.href = url;
    a.download = "bom_results.csv";
    a.click();

    URL.revokeObjectURL(url);
});

// ✅ Start
window.onload = loadBOM;
``
