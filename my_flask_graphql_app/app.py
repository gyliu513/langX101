from flask import Flask, jsonify
from models import db, User
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
        if User.query.count() == 0:  # 只在表中没有数据时插入
            user1 = User(username='user1', email='user1@example.com')
            user2 = User(username='user2', email='user2@example.com')
            db.session.add(user1)
            db.session.add(user2)
            db.session.commit()
            print("Initial data inserted")

if __name__ == '__main__':
    insert_initial_data()  # 插入初始数据
    app.run(debug=True)
