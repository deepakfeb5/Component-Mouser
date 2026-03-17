from flask import Flask, jsonify
import pandas as pd
import os

app = Flask(__name__)

@app.route("/api/bom", methods=["GET"])
def get_bom():
    df = pd.read_csv("BOM.csv")

    # Clean column names
    df.columns = [c.strip() for c in df.columns]

    # Add Total Price if columns exist
    if "Unit Price" in df.columns and "Quantity" in df.columns:
        df["Total Price"] = df["Unit Price"].fillna(0) * df["Quantity"].fillna(0)

    total_cost = df["Total Price"].sum()

    return jsonify({
        "table": df.to_dict(orient="records"),
        "total_cost": float(total_cost)
    })

@app.route("/")
def home():
    return "BOM API running"

if __name__ == "__main__":
    # ✅ IMPORTANT: Use platform-assigned port
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
