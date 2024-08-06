from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

# 导入模型
from .user import User