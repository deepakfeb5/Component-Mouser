from flask import Flask, jsonify
import pandas as pd
import os

app = Flask(__name__)

@app.route("/api/bom", methods=["GET"])
def get_bom():
    try:
        if not os.path.exists("BOM.csv"):
            return jsonify({"error": "BOM.csv not found"}), 404

        df = pd.read_csv("BOM.csv")
        df.columns = [c.strip() for c in df.columns]

        if "Unit Price" in df.columns and "Quantity" in df.columns:
            df["Total Price"] = df["Unit Price"].fillna(0) * df["Quantity"].fillna(0)

        total_cost = df["Total Price"].sum() if "Total Price" in df.columns else 0

        return jsonify({
            "table": df.to_dict(orient="records"),
            "columns": list(df.columns),
            "total_cost": float(total_cost)
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/")
def home():
    return jsonify({
        "status": "OK",
        "message": "Component Mouser API running successfully.",
        "endpoints": ["/api/bom"]
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
``
