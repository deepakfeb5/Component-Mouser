let bomData = [];  // store rows for search + export

// Load BOM CSV
async function loadCSV() {
    try {
        const response = await fetch("BOM.csv");
        const csvText = await response.text();

        const rows = csvText.trim().split("\n").map(r => r.split(","));
        bomData = rows;

        renderTable(rows);
        calculateTotal(rows);

    } catch (err) {
        document.getElementById("bomTable").innerHTML = "Error loading BOM.csv";
        console.error(err);
    }
}

// Render the table
function renderTable(rows) {
    let html = "<table border='1' style='border-collapse:collapse; width:100%'>";

    rows.forEach((row, i) => {
        html += i === 0 ? "<tr style='background:#e0e0e0'>" : "<tr>";

        row.forEach(col => {
            html += `<td style="padding:6px">${col}</td>`;
        });

        html += "</tr>";
    });

    html += "</table>";
    document.getElementById("bomTable").innerHTML = html;
}

// Calculate total BOM cost from last column (Total Price)
function calculateTotal(rows) {
    let sum = 0;

    for (let i = 1; i < rows.length; i++) {
        const totalPrice = parseFloat(rows[i][rows[i].length - 2]);  // 2nd last column
        
        if (!isNaN(totalPrice)) {
            sum += totalPrice;
        }
    }

    document.getElementById("totalCost").innerText = "$" + sum.toLocaleString();
}

// Search Filter
document.getElementById("searchInput").addEventListener("keyup", function () {
    const query = this.value.toLowerCase();

    const filtered = bomData.filter((row, i) => {
        if (i === 0) return true; // keep header
        return row.join(" ").toLowerCase().includes(query);
    });

    renderTable(filtered);
});

// CSV Download Button
document.getElementById("downloadBtn").addEventListener("click", () => {
    const csvContent = bomData.map(r => r.join(",")).join("\n");
    const blob = new Blob([csvContent], { type: "text/csv" });
    const url = URL.createObjectURL(blob);

    const a = document.createElement("a");
    a.href = url;
    a.download = "bom_results.csv";
    a.click();

    URL.revokeObjectURL(url);
});

window.onload = loadCSV;
