import os

from flask import Flask, jsonify, request


app = Flask(__name__)


@app.route("/")
def home():

    return jsonify({
        "success": True,
        "message": "TaskCoin API is working"
    })


@app.route("/api/test")
def api_test():

    return jsonify({
        "success": True,
        "message": "TaskCoin API test successful"
    })


@app.route("/api/user")
def get_user():

    telegram_id = request.args.get("telegram_id")

    if not telegram_id:

        return jsonify({
            "success": False,
            "message": "telegram_id is required"
        }), 400


    return jsonify({
        "success": True,
        "telegram_id": telegram_id,
        "balance": 0
    })


if __name__ == "__main__":

    port = int(
        os.getenv("PORT", "10000")
    )

    app.run(
        host="0.0.0.0",
        port=port
    )
