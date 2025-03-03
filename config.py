from dotenv import load_dotenv
import os

load_dotenv()

# MongoDB 설정
MONGODB_URI = os.getenv('MONGODB_URI', 'mongodb://localhost:27017')
DB_NAME = 'stock_news_db'
COLLECTION_NAME = 'news_articles'

# 스크래핑 설정
USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36' 