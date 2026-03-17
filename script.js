// Load CSV file and convert to HTML table
async function loadCSV() {
    try {
        const response = await fetch("BOM.csv");
        const data = await response.text();

        const rows = data.split("\n").map(r => r.split(","));
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
        document.getElementById("bomTable").innerHTML = "Error loading BOM.csv";
        console.error(err);
    }
}

window.onload = loadCSV;
