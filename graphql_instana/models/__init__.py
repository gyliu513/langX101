from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

# 导入模型
from .models import Metric, Trace, Log