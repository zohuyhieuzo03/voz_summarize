import os
import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from dotenv import load_dotenv
from main import process_single_post

# Load environment variables
load_dotenv()

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send a message when the command /start is issued."""
    await update.message.reply_text(
        'Xin chào! Tôi là bot phân tích bài viết VOZ.\n'
        'Gửi cho tôi link bài viết VOZ và tôi sẽ phân tích nội dung cùng các bình luận nổi bật.'
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send a message when the command /help is issued."""
    await update.message.reply_text(
        'Cách sử dụng:\n'
        '1. Gửi link bài viết VOZ cho tôi\n'
        '2. Tôi sẽ phân tích nội dung và các bình luận nổi bật\n'
        '3. Kết quả sẽ được gửi lại cho bạn'
    )

async def handle_voz_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle VOZ links and process them."""
    message_text = update.message.text
    
    # Check if the message contains a VOZ link
    if "voz.vn" in message_text:
        # Send processing message
        processing_message = await update.message.reply_text("Đang xử lý bài viết...")
        
        try:
            # Process the VOZ post
            process_single_post(message_text)
            
            # Find the most recent output file
            output_files = [f for f in os.listdir('.') if f.startswith('voz_single_post_')]
            if output_files:
                latest_file = max(output_files)
                
                # Read the content
                with open(latest_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # Split content into main content and AI analysis
                parts = content.split("AI Analysis:")
                main_content = parts[0].strip()
                ai_analysis = parts[1].strip() if len(parts) > 1 else ""
                
                # Split main content into news content and comments
                news_parts = main_content.split("Comments:")
                news_content = news_parts[0].strip()
                comments = news_parts[1].strip() if len(news_parts) > 1 else ""
                
                # Send news content
                await update.message.reply_text("📰 Nội dung bài viết:")
                news_chunks = [news_content[i:i+4000] for i in range(0, len(news_content), 4000)]
                for chunk in news_chunks:
                    await update.message.reply_text(chunk)
                
                # Send comments
                if comments:
                    await update.message.reply_text("💬 Các bình luận nổi bật:")
                    comment_chunks = [comments[i:i+4000] for i in range(0, len(comments), 4000)]
                    for chunk in comment_chunks:
                        await update.message.reply_text(chunk)
                
                # Send AI analysis as a separate message
                if ai_analysis:
                    await update.message.reply_text("🤖 AI Analysis:")
                    ai_chunks = [ai_analysis[i:i+4000] for i in range(0, len(ai_analysis), 4000)]
                    for chunk in ai_chunks:
                        await update.message.reply_text(chunk)
                
                # Delete the file after sending
                os.remove(latest_file)
            else:
                await update.message.reply_text("Không tìm thấy kết quả phân tích.")
                
        except Exception as e:
            await update.message.reply_text(f"Có lỗi xảy ra: {str(e)}")
        
        # Delete the processing message
        await processing_message.delete()
    else:
        await update.message.reply_text("Vui lòng gửi link bài viết VOZ hợp lệ.")

def main():
    """Start the bot."""
    try:
        # Create the Application
        token = os.getenv('TELEGRAM_BOT_TOKEN')
        if not token:
            raise ValueError("No TELEGRAM_BOT_TOKEN found in environment variables")
            
        application = Application.builder().token(token).build()

        # Add handlers
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("help", help_command))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_voz_link))

        # Start the Bot
        logger.info("Bot started successfully!")
        application.run_polling(allowed_updates=Update.ALL_TYPES)
        
    except Exception as e:
        logger.error(f"Error starting bot: {str(e)}")
        raise

if __name__ == '__main__':
    main() 