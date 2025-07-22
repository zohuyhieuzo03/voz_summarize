from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import os
from flask_migrate import Migrate
from voz_crawler import process_single_post
import threading
import uuid

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'voz_super_secret_key')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///voz_news.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)
migrate = Migrate(app, db)

class News(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    url = db.Column(db.String(512), unique=True, nullable=False)
    title = db.Column(db.String(512))
    content = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    comments = db.relationship('Comment', backref='news', lazy=True)
    ai_analysis = db.relationship('AIAnalysis', backref='news', uselist=False)

class Comment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    news_id = db.Column(db.Integer, db.ForeignKey('news.id'), nullable=False)
    reacts = db.Column(db.Integer)
    text = db.Column(db.Text)
    link = db.Column(db.String(512))
    is_positive = db.Column(db.Boolean, default=None)  # True: tích cực, False: tiêu cực, None: không xác định
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class AIAnalysis(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    news_id = db.Column(db.Integer, db.ForeignKey('news.id'), nullable=False)
    analysis = db.Column(db.Text)

progress_status = {}

@app.route('/')
def index():
    news_list = News.query.order_by(News.created_at.desc()).all()
    return render_template('index.html', news_list=news_list)

@app.route('/news/<int:news_id>')
def news_detail(news_id):
    news = News.query.get_or_404(news_id)
    # Sort comments by date ascending (oldest first)
    news.comments = sorted(news.comments, key=lambda c: getattr(c, 'created_at', None) or 0)
    return render_template('news_detail.html', news=news)

@app.route('/news/<int:news_id>/delete', methods=['POST'])
def delete_news(news_id):
    news = News.query.get_or_404(news_id)
    # Xoá toàn bộ comment và AIAnalysis liên quan
    Comment.query.filter_by(news_id=news.id).delete()
    AIAnalysis.query.filter_by(news_id=news.id).delete()
    db.session.delete(news)
    db.session.commit()
    flash('Đã xoá bài báo thành công!', 'success')
    return redirect(url_for('index'))

@app.route('/add_news', methods=['POST'])
def add_news():
    url = request.form.get('news_url')
    if url:
        task_id = str(uuid.uuid4())
        progress_status[task_id] = {'current': 0, 'total': 1, 'done': False}
        def crawl_task():
            def progress_callback(current, total):
                progress_status[task_id]['current'] = current
                progress_status[task_id]['total'] = total
            process_single_post(url, db, News, Comment, AIAnalysis, app, progress_callback=progress_callback)
            progress_status[task_id]['done'] = True
        threading.Thread(target=crawl_task, daemon=True).start()
        return jsonify({'task_id': task_id})
    else:
        return jsonify({'error': 'Vui lòng nhập link bài báo.'}), 400

@app.route('/progress/<task_id>')
def progress(task_id):
    status = progress_status.get(task_id)
    if not status:
        return jsonify({'error': 'Not found'}), 404
    return jsonify(status)

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True) 