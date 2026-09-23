import os

from flask import Flask, jsonify, request

from database import (
    get_user,
    create_or_update_user
)


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
def api_user():

    telegram_id = request.args.get("telegram_id")

    if not telegram_id:

        return jsonify({
            "success": False,
            "message": "telegram_id is required"
        }), 400

    try:

        telegram_id = int(telegram_id)

    except ValueError:

        return jsonify({
            "success": False,
            "message": "Invalid telegram_id"
        }), 400


    user = get_user(telegram_id)

    if not user:

        return jsonify({
            "success": False,
            "message": "User not found"
        }), 404


    return jsonify({
        "success": True,
        "user": dict(user)
    })


@app.route("/api/user/create", methods=["POST"])
def create_user():

    data = request.get_json(silent=True) or {}

    telegram_id = data.get("telegram_id")
    username = data.get("username")
    first_name = data.get("first_name")


    if not telegram_id:

        return jsonify({
            "success": False,
            "message": "telegram_id is required"
        }), 400


    try:

        telegram_id = int(telegram_id)

    except (ValueError, TypeError):

        return jsonify({
            "success": False,
            "message": "Invalid telegram_id"
        }), 400


    try:

        user = create_or_update_user(
            telegram_id=telegram_id,
            username=username,
            first_name=first_name
        )

        return jsonify({
            "success": True,
            "message": "User created/updated successfully",
            "user": dict(user)
        })

    except Exception as e:

        return jsonify({
            "success": False,
            "message": "Database error",
            "error": str(e)
        }), 500


if __name__ == "__main__":

    port = int(
        os.getenv("PORT", "10000")
    )

    app.run(
        host="0.0.0.0",
        port=port
    )
