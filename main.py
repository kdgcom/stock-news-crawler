import logging
import sys


def main():
    # Claude 모드 감지: --mode claude
    if "--mode" in sys.argv:
        try:
            idx = sys.argv.index("--mode")
            mode = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else ""
        except (IndexError, ValueError):
            mode = ""

        if mode == "claude":
            # claude 모드 전용 인자만 전달 (--mode claude 제거)
            claude_args = [
                a for i, a in enumerate(sys.argv[1:], 1)
                if not (a == "--mode" or (i > 1 and sys.argv[i - 1] == "--mode"))
            ]
            from src.claude_impl.app import run
            run(claude_args)
            return

    # 기존 모드 (default)
    from src.scraper import NewsScraper
    from src.news_analyzer import NewsAnalyzer
    from src.data_manager import DataManager

    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)

    scraper = NewsScraper()
    analyzer = NewsAnalyzer()
    data_manager = DataManager()

    news_site_url = "https://example.com/stock-news"

    try:
        links = scraper.get_news_links(news_site_url)
        logger.info(f"수집된 링크 수: {len(links)}")

        for url in links:
            try:
                article = scraper.parse_article(url)
                impact = analyzer.analyze_price_impact(article)
                article.price_impact = impact
                data_manager.save_to_mongodb(article)
                logger.info(f"기사 처리 완료: {article.title}")
            except Exception as e:
                logger.error(f"기사 처리 중 오류 발생: {str(e)}")
                continue

    except Exception as e:
        logger.error(f"프로그램 실행 중 오류 발생: {str(e)}")


if __name__ == "__main__":
    main() 