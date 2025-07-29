from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, Response
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import os
from flask_migrate import Migrate
from voz_crawler import process_single_post, get_forum_threads, get_top_comments, analyze_content_with_gemini
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
    comments = db.relationship('Comment', backref='news', lazy=True, cascade="all, delete-orphan")
    ai_analysis = db.relationship('AIAnalysis', backref='news', uselist=False, cascade="all, delete-orphan")
    ai_chats = db.relationship('AIChat', backref='news', lazy=True, order_by='AIChat.created_at.desc()', cascade="all, delete-orphan")

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

class AIChat(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    news_id = db.Column(db.Integer, db.ForeignKey('news.id'), nullable=False)
    question = db.Column(db.Text, nullable=False)
    answer = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class ReadingSession(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    news_id = db.Column(db.Integer, db.ForeignKey('news.id'), nullable=False)
    start_time = db.Column(db.DateTime, default=datetime.utcnow)
    end_time = db.Column(db.DateTime)
    total_seconds = db.Column(db.Integer, default=0)
    is_active = db.Column(db.Boolean, default=True)

progress_status = {}

@app.route('/')
def index():
    news_list = News.query.order_by(News.created_at.desc()).all()
    return render_template('index.html', news_list=news_list)

@app.route('/news/<int:news_id>')
def news_detail(news_id):
    news = News.query.get_or_404(news_id)
    # Import function to get display comments
    from voz_crawler import get_display_comments
    # Get comments for display according to the old rule
    news.comments = get_display_comments(db, Comment, news_id)
    return render_template('news_detail.html', news=news)

@app.route('/news/<int:news_id>/delete', methods=['POST'])
def delete_news(news_id):
    news = News.query.get_or_404(news_id)
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

@app.route('/api/threads')
def api_threads():
    html = get_forum_threads(News, db, app)
    return Response(html, mimetype='text/html')

@app.route('/api/processed-news')
def api_processed_news():
    news_list = News.query.order_by(News.created_at.desc()).all()
    html = ''
    for news in news_list:
        html += f'''
        <li>
          <a href="{url_for('news_detail', news_id=news.id)}"><b>{news.title}</b></a>
          <span style="color:#888;font-size:0.95em;">({news.created_at.strftime('%d/%m/%Y %H:%M')})</span>
        </li>
        '''
    if not news_list:
        html = '<li>Chưa có bài nào được xử lý.</li>'
    return Response(html, mimetype='text/html')

@app.route('/api/find-news')
def api_find_news():
    url = request.args.get('url')
    if url:
        news = News.query.filter_by(url=url).first()
        if news:
            return jsonify({'news_id': news.id})
        else:
            return jsonify({'error': 'Not found'}), 404
    else:
        return jsonify({'error': 'URL parameter required'}), 400

@app.route('/api/today-stats')
def api_today_stats():
    from datetime import datetime, date
    today = date.today()
    today_news = News.query.filter(
        db.func.date(News.created_at) == today
    ).count()
    
    # Calculate total reading time today
    today_sessions = ReadingSession.query.filter(
        db.func.date(ReadingSession.start_time) == today
    ).all()
    
    total_reading_seconds = sum(session.total_seconds for session in today_sessions)
    total_reading_minutes = total_reading_seconds // 60
    total_reading_hours = total_reading_minutes // 60
    
    return jsonify({
        'today_count': today_news,
        'total_reading_seconds': total_reading_seconds,
        'total_reading_minutes': total_reading_minutes,
        'total_reading_hours': total_reading_hours
    })

@app.route('/api/reading/start', methods=['POST'])
def api_reading_start():
    news_id = request.json.get('news_id')
    if news_id:
        # End any existing active session for this news
        ReadingSession.query.filter_by(news_id=news_id, is_active=True).update({'is_active': False})
        
        # Start new session
        session = ReadingSession(news_id=news_id)
        db.session.add(session)
        db.session.commit()
        return jsonify({'session_id': session.id})
    return jsonify({'error': 'news_id required'}), 400

@app.route('/api/reading/stop', methods=['POST'])
def api_reading_stop():
    session_id = request.json.get('session_id')
    total_seconds = request.json.get('total_seconds', 0)
    
    if session_id:
        session = ReadingSession.query.get(session_id)
        if session:
            session.end_time = datetime.utcnow()
            session.total_seconds = total_seconds
            session.is_active = False
            db.session.commit()
            return jsonify({'success': True})
    return jsonify({'error': 'session_id required'}), 400

@app.route('/api/reading/total/<int:news_id>')
def api_reading_total(news_id):
    # Get total reading time for this news article
    sessions = ReadingSession.query.filter_by(news_id=news_id).all()
    total_seconds = sum(session.total_seconds for session in sessions)
    
    return jsonify({
        'total_seconds': total_seconds,
        'total_minutes': total_seconds // 60,
        'total_hours': (total_seconds // 60) // 60
    })

@app.route('/api/news/<int:news_id>/update_comments', methods=['POST'])
def update_comments(news_id):
    try:
        news = News.query.get_or_404(news_id)
        # Crawl lại comment mới từ VOZ
        news_title, news_content, top_comments = get_top_comments(news.url, num_comments=5)
        # Lấy các link comment đã có trong DB
        existing_links = set(c.link for c in Comment.query.filter_by(news_id=news.id).all())
        new_comments = [c for c in top_comments if c['link'] not in existing_links]
        # Nếu có comment mới thì thêm vào DB
        for c in new_comments:
            comment = Comment(
                news_id=news.id,
                reacts=c['reacts'],
                text=c['text'],
                link=c['link'],
                is_positive=c.get('is_positive'),
                created_at=c.get('date') if c.get('date') else None
            )
            db.session.add(comment)
        db.session.commit()
        # Nếu có comment mới, cập nhật lại AIAnalysis
        # if new_comments:
        #     all_comments = Comment.query.filter_by(news_id=news.id).all()
        #     ai_text = analyze_content_with_gemini(news.content, all_comments)
        #     ai = AIAnalysis.query.filter_by(news_id=news.id).first()
        #     if ai:
        #         ai.analysis = ai_text
        #     else:
        #         ai = AIAnalysis(news_id=news.id, analysis=ai_text)
        #         db.session.add(ai)
        #     db.session.commit()
        return jsonify({'success': True, 'new_comments': len(new_comments)})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/news/<int:news_id>/chat', methods=['POST'])
def ai_chat(news_id):
    try:
        news = News.query.get_or_404(news_id)
        question = request.json.get('question')
        
        if not question:
            return jsonify({'success': False, 'error': 'Question is required'}), 400
        
        # Import function from voz_crawler
        from voz_crawler import chat_with_ai_about_thread
        
        # Get AI response with all comments
        answer, comment_count = chat_with_ai_about_thread(
            news.title, 
            news.content, 
            news.comments, 
            question,
            url=news.url,
            db=db,
            Comment=Comment,
            news_id=news.id
        )
        
        # Save to database
        chat = AIChat(
            news_id=news.id,
            question=question,
            answer=answer
        )
        db.session.add(chat)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'answer': answer,
            'chat_id': chat.id,
            'comment_count': comment_count
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True, host='0.0.0.0', port=8080) 