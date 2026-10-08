from flask import Flask, request, jsonify, render_template
from app.agent import run_agent

app = Flask(__name__)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/chat", methods=["POST"])
def chat():
    data = request.get_json(silent=True) or {}

    user_input = data.get("message", "").strip()

    if not user_input:
        return jsonify({
            "success": False,
            "error": "消息不能为空"
        }), 400

    events = []

    def event_callback(event):
        events.append(event)

    try:
        answer = run_agent(
            user_input,
            event_callback=event_callback
        )

        return jsonify({
            "success": True,
            "answer": answer,
            "events": events
        })

    except Exception as e:

        return jsonify({
            "success": False,
            "error": str(e),
            "events": events
        }), 500


@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "service": "AI Agent"
    })


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=5001,
        debug=False
    )