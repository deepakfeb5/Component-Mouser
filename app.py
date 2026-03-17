from flask import Flask, jsonify
import pandas as pd
import os

app = Flask(__name__)

@app.route("/api/bom", methods=["GET"])
def get_bom():
    try:
        # Ensure file exists
        if not os.path.exists("BOM.csv"):
            return jsonify({"error": "BOM.csv not found"}), 404

        # Load the BOM CSV
        df = pd.read_csv("BOM.csv")

        # Normalize column names for safety
        df.columns = [c.strip() for c in df.columns]

        # Add Total Price if required fields exist
        if "Unit Price" in df.columns and "Quantity" in df.columns:
            df["Total Price"] = df["Unit Price"].fillna(0) * df["Quantity"].fillna(0)

        # Compute total BOM cost
        total_cost = df["Total Price"].sum() if "Total Price" in df.columns else 0

        return jsonify({
            "table": df.to_dict(orient="records"),
            "columns": list(df.columns),
            "total_cost": float(total_cost)
        })

    except Exception as e:
