from flask import Flask

app = Flask(__name__, template_folder="../frontend", static_folder="../frontend/static")

@app.route("/")
def index():
    return "Çalışıyor"

if __name__ == "__main__":
    app.run(debug=True)