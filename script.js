// Load BOM.csv and convert to table
async function loadCSV() {
    try {
        const response = await fetch("BOM.csv");
        const data = await response.text();

        const rows = data.split("\n").map(row => row.split(","));
        let html = "<table border='1' style='border-collapse:collapse; width:100%'>";

        rows.forEach((row, index) => {
            html += index === 0 ? "<tr style='background:#e0e0e0'>" : "<tr>";
            row.forEach(col => {
                html += `<td style="padding:6px">${col}</td>`;
            });
            html += "</tr>";
        });

        html += "</table>";

        document.getElementById("bomTable").innerHTML = html;

    } catch (err) {
        console.error("Error loading CSV:", err);
        document.getElementById("bomTable").innerHTML = "Failed to load BOM.csv";
    }
}

window.onload = loadCSV;
