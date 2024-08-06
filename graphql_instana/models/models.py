from . import db

class Metric(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(64))
    value = db.Column(db.Float)
    timestamp = db.Column(db.String(64))

class Trace(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    trace_id = db.Column(db.String(64))
    span = db.Column(db.String(64))
    duration = db.Column(db.Float)
    timestamp = db.Column(db.String(64))

class Log(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    message = db.Column(db.String(256))
    level = db.Column(db.String(16))
    timestamp = db.Column(db.String(64))
