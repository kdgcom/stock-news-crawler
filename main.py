import logging
from src.scraper import NewsScraper
from src.news_analyzer import NewsAnalyzer
from src.data_manager import DataManager

def main():
    # 로깅 설정
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)

    # 객체 초기화
    scraper = NewsScraper()
    analyzer = NewsAnalyzer()
    data_manager = DataManager()

    # 뉴스 사이트 URL
    news_site_url = "https://example.com/stock-news"

    try:
        # 뉴스 링크 수집
        links = scraper.get_news_links(news_site_url)
        logger.info(f"수집된 링크 수: {len(links)}")

        # 각 링크에서 뉴스 파싱
        for url in links:
            try:
                # 기사 파싱
                article = scraper.parse_article(url)
                
                # 주가 영향도 분석
                impact = analyzer.analyze_price_impact(article)
                article.price_impact = impact

                # MongoDB에 저장
                data_manager.save_to_mongodb(article)
                
                logger.info(f"기사 처리 완료: {article.title}")
            
            except Exception as e:
                logger.error(f"기사 처리 중 오류 발생: {str(e)}")
                continue

    except Exception as e:
        logger.error(f"프로그램 실행 중 오류 발생: {str(e)}")

if __name__ == "__main__":
    main() 