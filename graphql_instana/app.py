from flask import Flask, jsonify
from models import db, Metric, Trace, Log
from flask_migrate import Migrate
from views.graphql_view import graphql_bp
from config import Config

app = Flask(__name__)
app.config.from_object(Config)
db.init_app(app)
migrate = Migrate(app, db)

# 注册蓝图
app.register_blueprint(graphql_bp, url_prefix='/graphql')

@app.route('/')
def index():
    return jsonify({"message": "Welcome to the Flask GraphQL API!"})

def insert_initial_data():
    with app.app_context():
        if Metric.query.count() == 0:  # 只在表中没有数据时插入
            # 插入示例数据
            metric = Metric(name="CPU Usage", value=75.5, timestamp="2024-08-06T12:00:00Z")
            trace = Trace(trace_id="1", span="span1", duration=123.4, timestamp="2024-08-06T12:00:00Z")
            log = Log(message="Error occurred", level="ERROR", timestamp="2024-08-06T12:00:00Z")
            
            db.session.add(metric)
            db.session.add(trace)
            db.session.add(log)
            db.session.commit()

if __name__ == '__main__':
    insert_initial_data()  # 插入初始数据
    app.run(debug=True)
