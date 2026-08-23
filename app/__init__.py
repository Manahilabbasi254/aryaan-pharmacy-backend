from flask import Flask
from flask_cors import CORS

def create_app():
    app = Flask(__name__)
    CORS(app)

    @app.route("/api/v1/ping")
    def ping():
        return {"message": "Aryaan Pharmacy backend is running"}

    return app